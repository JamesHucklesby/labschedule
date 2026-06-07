from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from auth import (
    _build_google_flow,
    _consume_oauth_state,
    _default_role_for_user,
    _get_user_allowed_calendars,
    _resolve_user_id_from_login_or_api_token,
    _store_oauth_state,
    GoogleRequest,
    google_id_token,
    InvalidGrantError,
)
from config import (
    ADMIN_USER_EMAILS,
    ADMIN_USER_NAMES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_HOSTED_DOMAIN,
    GOOGLE_LOGIN_HINT,
    SESSION_COOKIE_SECURE,
)
from database import DB_LOCK, _db_session, _generate_unique_login_token, _replace_user_calendar_links
from models import UserORM
from utils import _sanitize_calendar_ids_input, _sanitize_token_input

router = APIRouter()


def _cookie_secure_flag(request: Request) -> bool:
    if SESSION_COOKIE_SECURE == 'true':
        return True
    if SESSION_COOKIE_SECURE == 'false':
        return False
    forwarded_proto = (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip().lower()
    if forwarded_proto in {'http', 'https'}:
        return forwarded_proto == 'https'
    return request.url.scheme == 'https'


@router.post('/auth/preserve-link-token')
async def preserve_link_token(payload: dict[str, Any], request: Request) -> JSONResponse:
    raw_token = str(payload.get('token') or '').strip()
    if not raw_token:
        raise HTTPException(status_code=400, detail='Token is required.')
    token = _sanitize_token_input(raw_token, 'token')
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.get('calendarIds') or []))

    response = JSONResponse({'ok': True})
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='pending_link_token',
        value=token,
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
        max_age=600,
    )
    response.set_cookie(
        key='pending_link_calendar_ids',
        value=','.join(calendar_ids),
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
        max_age=600,
    )
    return response


@router.get('/auth/google-login')
async def google_login() -> RedirectResponse:
    """Initiate Google OAuth flow."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail='Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env',
        )

    flow = _build_google_flow()
    auth_kwargs: dict[str, Any] = {
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'select_account',
        'hd': GOOGLE_HOSTED_DOMAIN,
    }
    if GOOGLE_LOGIN_HINT:
        auth_kwargs['login_hint'] = GOOGLE_LOGIN_HINT

    auth_url, state = flow.authorization_url(**auth_kwargs)
    _store_oauth_state(state)
    return RedirectResponse(url=auth_url)


@router.get('/auth/callback')
async def oauth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    """Handle Google OAuth callback."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail='Google OAuth not configured.')

    if not _consume_oauth_state(state):
        raise HTTPException(
            status_code=400,
            detail='OAuth login expired or was already used. Please try signing in again.',
        )

    flow = _build_google_flow(state=state)
    try:
        flow.fetch_token(authorization_response=str(request.url))
    except InvalidGrantError as exc:
        raise HTTPException(
            status_code=400,
            detail='OAuth login expired or was already used. Please sign in again.',
        ) from exc

    credentials = flow.credentials
    if not credentials.id_token:
        raise HTTPException(status_code=400, detail='Google OAuth did not return an ID token.')

    user_info = google_id_token.verify_oauth2_token(
        credentials.id_token,
        GoogleRequest(),
        GOOGLE_CLIENT_ID,
    )

    email = user_info.get('email', '')
    if not email.endswith('@aucklanduni.ac.nz'):
        raise HTTPException(status_code=403, detail='Only aucklanduni.ac.nz email addresses are allowed.')

    google_id = user_info.get('sub', '')
    name = user_info.get('name', email.split('@')[0])
    picture_url = user_info.get('picture', '')
    role = _default_role_for_user(email, name)
    login_token = ''

    user_id = str(uuid4())
    with DB_LOCK:
        with _db_session() as session:
            existing = session.scalar(select(UserORM).where(UserORM.google_id == google_id))

            if existing:
                user_id = existing.id
                login_token = (existing.login_token or '').strip()
                existing.email = email
                existing.name = name
                if email in ADMIN_USER_EMAILS or name in ADMIN_USER_NAMES:
                    existing.role = 'admin'
                existing.picture_url = picture_url
                existing.last_login = datetime.now().astimezone().isoformat()
            else:
                login_token = _generate_unique_login_token(session)
                now_str = datetime.now().astimezone().isoformat()
                session.add(UserORM(
                    id=user_id,
                    google_id=google_id,
                    email=email,
                    name=name,
                    role=role,
                    login_token=login_token,
                    picture_url=picture_url,
                    created_at=now_str,
                    last_login=now_str,
                ))

            if not login_token:
                login_token = _generate_unique_login_token(session)
                if existing:
                    existing.login_token = login_token

            pending_link_token = request.cookies.get('pending_link_token')
            pending_link_calendar_ids_raw = request.cookies.get('pending_link_calendar_ids') or ''
            pending_link_calendar_ids = [
                value.strip() for value in pending_link_calendar_ids_raw.split(',') if value.strip()
            ]
            if pending_link_token:
                try:
                    pending_link_token = _sanitize_token_input(pending_link_token, 'pending_link_token')
                except HTTPException:
                    pending_link_token = ''
                source_user_id = _resolve_user_id_from_login_or_api_token(session, pending_link_token)
                if source_user_id and source_user_id != user_id:
                    source_calendar_ids = sorted(_get_user_allowed_calendars(session, source_user_id) or set())
                    if pending_link_calendar_ids:
                        source_calendar_set = set(source_calendar_ids)
                        requested_calendar_ids = [
                            cal_id for cal_id in pending_link_calendar_ids if cal_id in source_calendar_set
                        ]
                    else:
                        requested_calendar_ids = source_calendar_ids
                    if requested_calendar_ids:
                        current_calendar_ids = sorted(_get_user_allowed_calendars(session, user_id) or set())
                        merged_calendar_ids = sorted(set(current_calendar_ids).union(requested_calendar_ids))
                        now_str = datetime.now().astimezone().isoformat()
                        _replace_user_calendar_links(
                            session,
                            user_id,
                            merged_calendar_ids,
                            approved_by_user_id=user_id,
                            approved_at=now_str,
                            requested_at=now_str,
                        )

    resolved_session_token = login_token
    if not resolved_session_token:
        raise HTTPException(status_code=500, detail='Failed to resolve a session token for this account.')

    response = RedirectResponse(url=f'/?user_id={user_id}')
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='session_token',
        value=resolved_session_token,
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
    )
    response.set_cookie(
        key='user_id',
        value=user_id,
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
    )
    response.delete_cookie(key='pending_link_token', path='/')
    response.delete_cookie(key='pending_link_calendar_ids', path='/')
    return response
