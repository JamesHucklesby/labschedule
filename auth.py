import json
import os
from collections import deque
from datetime import datetime
from threading import Lock
from time import monotonic, time
from typing import Any
from urllib.parse import urlparse

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import (
    ADMIN_USER_EMAILS,
    ADMIN_USER_NAMES,
    ADMIN_USER_ROLE,
    APP_SECRET_KEY,
    DEFAULT_USER_ROLE,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_HOSTED_DOMAIN,
    GOOGLE_LOGIN_HINT,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_REDIRECT_URI,
    JWT_ALGORITHM,
    JWT_EXP_SECONDS,
    OAUTH_STATE_TTL_SECONDS,
    TOKEN_RATE_LIMIT_MAX_REQUESTS,
    TOKEN_RATE_LIMIT_WINDOW_SECONDS,
    TRUSTED_PROXY_IPS,
)
from database import _db_session
from models import CalendarGroupLinkORM, CalendarORM, GroupUserLinkORM, UserCalendarLinkORM, UserORM
from utils import _sanitize_token_input

# ── Local OAuth transport (must happen at import time) ─────────────────────────

def _is_local_oauth_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}


if _is_local_oauth_redirect(GOOGLE_REDIRECT_URI):
    os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

# Deferred imports for Google libraries (avoids import-time side-effects)
from google.auth.transport.requests import Request as GoogleRequest  # noqa: E402
from google.oauth2 import id_token as google_id_token  # noqa: E402
from google_auth_oauthlib.flow import Flow  # noqa: E402
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError  # noqa: E402

# ── OAuth state store ─────────────────────────────────────────────────────────

OAUTH_STATE_LOCK = Lock()
OAUTH_STATE_STORE: dict[str, float] = {}


def _prune_oauth_states() -> None:
    cutoff = monotonic() - OAUTH_STATE_TTL_SECONDS
    stale_states = [key for key, created_at in OAUTH_STATE_STORE.items() if created_at < cutoff]
    for key in stale_states:
        OAUTH_STATE_STORE.pop(key, None)


def _store_oauth_state(state: str) -> None:
    with OAUTH_STATE_LOCK:
        _prune_oauth_states()
        OAUTH_STATE_STORE[state] = monotonic()


def _consume_oauth_state(state: str) -> bool:
    with OAUTH_STATE_LOCK:
        _prune_oauth_states()
        created_at = OAUTH_STATE_STORE.pop(state, None)
    return created_at is not None


# ── Google OAuth flow ─────────────────────────────────────────────────────────

def _google_client_config() -> dict[str, Any]:
    return {
        'web': {
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [GOOGLE_REDIRECT_URI],
        }
    }


def _build_google_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(_google_client_config(), scopes=GOOGLE_OAUTH_SCOPES, state=state)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


# ── Role helper ───────────────────────────────────────────────────────────────

def _default_role_for_user(email: str, name: str) -> str:
    normalized_email = email.strip().lower()
    normalized_name = name.strip().lower()
    if normalized_email in ADMIN_USER_EMAILS:
        return ADMIN_USER_ROLE
    if normalized_name in {value.lower() for value in ADMIN_USER_NAMES}:
        return ADMIN_USER_ROLE
    return DEFAULT_USER_ROLE


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _is_jwt_token(token: str | None) -> bool:
    if not token:
        return False
    return token.count('.') == 2


def _decode_api_jwt(token: str | None) -> dict[str, Any] | None:
    if not token or not _is_jwt_token(token):
        return None
    try:
        payload = jwt.decode(token, APP_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if isinstance(payload, dict) else None


def _issue_api_jwt(user_id: str, role: str) -> str:
    now = int(time())
    payload = {
        'sub': user_id,
        'role': role,
        'iat': now,
        'exp': now + JWT_EXP_SECONDS,
        'iss': 'lab-scheduler',
    }
    return str(jwt.encode(payload, APP_SECRET_KEY, algorithm=JWT_ALGORITHM))


# ── Token resolution ──────────────────────────────────────────────────────────

def _resolve_user_id_from_api_token(token: str | None) -> str | None:
    payload = _decode_api_jwt(token)
    if payload is not None:
        user_id = payload.get('sub')
        return str(user_id) if user_id else None
    return None


def _resolve_user_id_from_login_token(session: Session, token: str | None) -> str | None:
    if not token:
        return None
    user_id = session.scalar(select(UserORM.id).where(UserORM.login_token == token))
    return str(user_id) if user_id else None


def _resolve_user_id_from_login_or_api_token(session: Session, token: str | None) -> str | None:
    user_id = _resolve_user_id_from_api_token(token)
    if user_id:
        return user_id
    return _resolve_user_id_from_login_token(session, token)


# ── Calendar access helpers ───────────────────────────────────────────────────

def _get_user_allowed_calendars(session: Session, user_id: str) -> set[str] | None:
    user = session.get(UserORM, user_id)
    if user is None:
        return None
    direct_calendar_ids = session.scalars(
        select(UserCalendarLinkORM.calendar_id)
        .where(UserCalendarLinkORM.user_id == user_id)
        .where(UserCalendarLinkORM.status == 'approved')
        .order_by(UserCalendarLinkORM.calendar_id.asc())
    ).all()
    approved_group_names = session.scalars(
        select(GroupUserLinkORM.group_name)
        .where(GroupUserLinkORM.user_id == user_id)
        .where(GroupUserLinkORM.status == 'approved')
        .order_by(GroupUserLinkORM.group_name.asc())
    ).all()
    group_calendar_ids = session.scalars(
        select(CalendarGroupLinkORM.calendar_id)
        .where(CalendarGroupLinkORM.group_name.in_(approved_group_names))
        .order_by(CalendarGroupLinkORM.calendar_id.asc())
    ).all() if approved_group_names else []
    fallback_group_calendar_ids = session.scalars(
        select(CalendarORM.id)
        .where(CalendarORM.group_name.in_(approved_group_names))
        .order_by(CalendarORM.id.asc())
    ).all() if approved_group_names else []
    hidden_calendar_ids = session.scalars(
        select(UserCalendarLinkORM.calendar_id)
        .where(UserCalendarLinkORM.user_id == user_id)
        .where(UserCalendarLinkORM.status == 'hidden')
        .order_by(UserCalendarLinkORM.calendar_id.asc())
    ).all()
    return (
        {str(cal_id) for cal_id in direct_calendar_ids if cal_id}
        | {str(cal_id) for cal_id in group_calendar_ids if cal_id}
        | {str(cal_id) for cal_id in fallback_group_calendar_ids if cal_id}
    ) - {str(cal_id) for cal_id in hidden_calendar_ids if cal_id}


def _get_token_allowed_calendars(token: str | None) -> set[str] | None:
    """Return allowed calendar IDs for a JWT token, or None if invalid."""
    if not token:
        return None
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        return None
    user_id = _resolve_user_id_from_api_token(token)
    if not user_id:
        return None
    with _db_session() as session:
        return _get_user_allowed_calendars(session, user_id)


def _get_token_owner_user_id(token: str | None) -> str | None:
    """Return user_id for a JWT token, or None if not found."""
    if not token:
        return None
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        return None
    return _resolve_user_id_from_api_token(token)


def _get_login_or_api_token_allowed_calendars(token: str | None) -> set[str] | None:
    if not token:
        return None
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        return None
    with _db_session() as session:
        user_id = _resolve_user_id_from_login_or_api_token(session, token)
        if not user_id:
            return None
        return _get_user_allowed_calendars(session, user_id)


def _get_login_or_api_token_owner_user_id(token: str | None) -> str | None:
    if not token:
        return None
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        return None
    with _db_session() as session:
        user_id = _resolve_user_id_from_login_or_api_token(session, token)
        return str(user_id) if user_id else None


def _validate_token_access(token: str | None, calendar_ids: list[str]) -> None:
    if not token:
        raise HTTPException(status_code=403, detail='Token is required.')
    allowed = _get_token_allowed_calendars(token)
    if allowed is None:
        raise HTTPException(status_code=403, detail='Invalid or expired token.')
    for cal_id in calendar_ids:
        if cal_id not in allowed:
            raise HTTPException(status_code=403, detail='Token does not permit access to this calendar.')


def _require_valid_token(token: str | None) -> set[str]:
    """Return allowed calendar IDs for a valid token or raise 403."""
    if not token:
        raise HTTPException(status_code=403, detail='Token is required.')
    token = _sanitize_token_input(token)
    allowed = _get_token_allowed_calendars(token)
    if allowed is None:
        raise HTTPException(status_code=403, detail='Invalid or expired token.')
    return allowed


def _validate_read_token_access(token: str | None, calendar_ids: list[str]) -> set[str]:
    """Raise HTTPException 403 unless token grants access to at least one calendar."""
    allowed = _require_valid_token(token)
    if not any(cal_id in allowed for cal_id in calendar_ids):
        raise HTTPException(status_code=403, detail='Token does not permit access to this calendar.')
    return allowed


# ── Session user helpers ──────────────────────────────────────────────────────

def _session_user_for_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        return None
    user_id = _resolve_user_id_from_api_token(token)
    if not user_id:
        return None
    with _db_session() as session:
        user = session.get(UserORM, user_id)
        if user is None:
            return None
        return {
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'role': user.role or DEFAULT_USER_ROLE,
            'isTokenOnlyAccount': (
                str(user.google_id or '').startswith('link:')
                or str(user.google_id or '').startswith('local:')
            ),
        }


def _session_user_for_login_or_api_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _db_session() as session:
        user_id = _resolve_user_id_from_api_token(token)
        if not user_id:
            user_id = _resolve_user_id_from_login_token(session, token)
        if not user_id:
            return None
        user = session.get(UserORM, user_id)
        if user is None:
            return None
        return {
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'role': user.role or DEFAULT_USER_ROLE,
            'isTokenOnlyAccount': (
                str(user.google_id or '').startswith('link:')
                or str(user.google_id or '').startswith('local:')
            ),
        }


def _require_admin_user(token: str | None) -> dict[str, Any]:
    user = _session_user_for_login_or_api_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail='Admin access requires an authenticated user token.')
    if user['role'] != ADMIN_USER_ROLE:
        raise HTTPException(status_code=403, detail='Admin access required.')
    return user


def _require_authenticated_user(token: str | None) -> dict[str, Any]:
    user = _session_user_for_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail='Authenticated user token is required.')
    return user


# ── Rate limiting ─────────────────────────────────────────────────────────────

TOKEN_RATE_LIMIT_LOCK = Lock()
TOKEN_RATE_LIMIT_BY_IP: dict[str, deque[float]] = {}


def _client_ip_address(request: Request) -> str:
    remote_ip = request.client.host if request.client and request.client.host else 'unknown'
    forwarded_for = request.headers.get('x-forwarded-for', '').strip()
    if forwarded_for and remote_ip in TRUSTED_PROXY_IPS:
        return forwarded_for.split(',')[0].strip() or 'unknown'
    return remote_ip


def _enforce_token_validation_rate_limit(client_ip: str) -> None:
    now = monotonic()
    cutoff = now - TOKEN_RATE_LIMIT_WINDOW_SECONDS
    with TOKEN_RATE_LIMIT_LOCK:
        bucket = TOKEN_RATE_LIMIT_BY_IP.setdefault(client_ip, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= TOKEN_RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail='Too many token validation requests. Try again shortly.',
                headers={'Retry-After': '1'},
            )
        bucket.append(now)


# ── Re-exports for convenience ────────────────────────────────────────────────
# These are used by routes/oauth.py to avoid importing Google libs directly.
__all__ = [
    'OAUTH_STATE_LOCK',
    'OAUTH_STATE_STORE',
    'GoogleRequest',
    'google_id_token',
    'Flow',
    'InvalidGrantError',
    '_prune_oauth_states',
    '_store_oauth_state',
    '_consume_oauth_state',
    '_google_client_config',
    '_build_google_flow',
    '_default_role_for_user',
    '_is_jwt_token',
    '_decode_api_jwt',
    '_issue_api_jwt',
    '_resolve_user_id_from_api_token',
    '_resolve_user_id_from_login_token',
    '_resolve_user_id_from_login_or_api_token',
    '_get_user_allowed_calendars',
    '_get_token_allowed_calendars',
    '_get_token_owner_user_id',
    '_validate_token_access',
    '_require_valid_token',
    '_validate_read_token_access',
    '_session_user_for_token',
    '_session_user_for_login_or_api_token',
    '_require_admin_user',
    '_require_authenticated_user',
    '_client_ip_address',
    '_enforce_token_validation_rate_limit',
    'TOKEN_RATE_LIMIT_LOCK',
    'TOKEN_RATE_LIMIT_BY_IP',
]
