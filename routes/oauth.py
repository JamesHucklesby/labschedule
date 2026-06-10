import asyncio
from datetime import datetime
import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from auth import (
    _build_google_flow,
    _consume_oauth_state,
    _default_role_for_user,
    _issue_api_jwt,
    _resolve_user_id_from_login_or_api_token,
    _store_oauth_state,
    GoogleRequest,
    google_id_token,
    InvalidGrantError,
)
from config import (
    ADMIN_USER_EMAILS,
    ADMIN_USER_NAMES,
    APP_BASE_URL,
    DEFAULT_USER_ROLE,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_HOSTED_DOMAIN,
    GOOGLE_LOGIN_HINT,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_STARTTLS,
    SESSION_COOKIE_SECURE,
)
from database import (
    DB_LOCK,
    _db_session,
    _generate_unique_login_token,
    _merge_user_access_from_source,
    _record_user_saved_share_link,
)
from models import UserORM
from realtime import _publish_user_resources_updated
from utils import _sanitize_calendar_ids_input, _sanitize_email_input, _sanitize_id_input, _sanitize_text_input, _sanitize_token_input

router = APIRouter()
_EMAIL_LOGIN_TOKEN_PATTERN = re.compile(r'^[0-9a-f]{32,128}$')
_LOG = logging.getLogger(__name__)
_EMAIL_TASKS: set[asyncio.Task[None]] = set()


def _track_email_task(task: asyncio.Task[None]) -> None:
    _EMAIL_TASKS.add(task)

    def _on_done(done_task: asyncio.Task[None]) -> None:
        _EMAIL_TASKS.discard(done_task)
        try:
            done_task.result()
        except Exception as exc:
            _LOG.exception('Asynchronous email delivery failed: %s', exc)

    task.add_done_callback(_on_done)


def _enqueue_email_send(*, created_new_user: bool, email: str, name: str, login_url: str) -> None:
    async def _send() -> None:
        if created_new_user:
            await asyncio.to_thread(_send_email_signup_link, email=email, name=name, login_url=login_url)
        else:
            await asyncio.to_thread(_send_email_login_link, email=email, name=name, login_url=login_url)

    _track_email_task(asyncio.create_task(_send()))


def _send_email_login_link(*, email: str, name: str, login_url: str) -> None:
    if not SMTP_FROM_EMAIL:
        raise RuntimeError('SMTP_FROM_EMAIL is not configured.')
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        raise RuntimeError('SMTP credentials are not configured.')

    message = EmailMessage()
    message['Subject'] = 'Your Lab Scheduler login link'
    message['From'] = f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>' if SMTP_FROM_NAME else SMTP_FROM_EMAIL
    message['To'] = email
    greeting_name = (name or '').strip() or 'there'
    message.set_content(
        f'Hi {greeting_name},\n\n'
        f'Use this secure login link to sign in:\n\n{login_url}\n\n'
        'This login token does not expire unless regenerated.\n\n'
        'If you did not request this, you can ignore this email.\n'
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if SMTP_USE_STARTTLS:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def _send_email_signup_link(*, email: str, name: str, login_url: str) -> None:
    if not SMTP_FROM_EMAIL:
        raise RuntimeError('SMTP_FROM_EMAIL is not configured.')
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        raise RuntimeError('SMTP credentials are not configured.')

    message = EmailMessage()
    message['Subject'] = 'Welcome to Lab Scheduler - complete signup'
    message['From'] = f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>' if SMTP_FROM_NAME else SMTP_FROM_EMAIL
    message['To'] = email
    greeting_name = (name or '').strip() or 'there'
    message.set_content(
        f'Hi {greeting_name},\n\n'
        'We created your Lab Scheduler account from your email login request.\n'
        'Use this link to sign in and finish your profile:\n\n'
        f'{login_url}\n\n'
        'This login token does not expire unless regenerated.\n\n'
        'If you did not request this, you can ignore this email.\n'
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if SMTP_USE_STARTTLS:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def _cookie_secure_flag(request: Request) -> bool:
    if SESSION_COOKIE_SECURE == 'true':
        return True
    if SESSION_COOKIE_SECURE == 'false':
        return False
    forwarded_proto = (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip().lower()
    if forwarded_proto in {'http', 'https'}:
        return forwarded_proto == 'https'
    return request.url.scheme == 'https'


def _public_callback_url(request: Request) -> str:
    forwarded_proto = (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip().lower()
    forwarded_host = (request.headers.get('x-forwarded-host') or '').split(',')[0].strip()
    host = forwarded_host or request.headers.get('host') or request.url.netloc
    scheme = forwarded_proto if forwarded_proto in {'http', 'https'} else request.url.scheme
    path = request.url.path
    query = f'?{request.url.query}' if request.url.query else ''
    return f'{scheme}://{host}{path}{query}'


@router.post('/auth/preserve-link-token')
async def preserve_link_token(payload: dict[str, Any], request: Request) -> JSONResponse:
    raw_token = str(payload.get('token') or '').strip()
    token_candidates = [raw_token, str(request.cookies.get('session_token') or '').strip()]
    source_user_id = ''
    sanitized_token = ''
    with DB_LOCK:
        with _db_session() as session:
            for candidate in token_candidates:
                if not candidate:
                    continue
                try:
                    normalized_candidate = _sanitize_token_input(candidate, 'token')
                except HTTPException:
                    continue
                resolved_user_id = _resolve_user_id_from_login_or_api_token(session, normalized_candidate)
                if resolved_user_id:
                    source_user_id = str(resolved_user_id)
                    sanitized_token = normalized_candidate
                    break

    if not source_user_id:
        raise HTTPException(status_code=400, detail='A valid token or session is required.')

    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.get('calendarIds') or []))

    response = JSONResponse({'ok': True})
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='pending_link_token',
        value=sanitized_token,
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
        max_age=600,
    )
    response.set_cookie(
        key='pending_link_source_user_id',
        value=source_user_id,
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


@router.post('/auth/local-signup')
async def local_signup(payload: dict[str, Any], request: Request) -> JSONResponse:
    name = _sanitize_text_input(str(payload.get('name') or ''), 'name', min_length=1, max_length=120)
    email = _sanitize_email_input(str(payload.get('email') or ''), 'email')

    with DB_LOCK:
        with _db_session() as session:
            existing = session.scalar(select(UserORM.id).where(UserORM.email == email))
            if existing is not None:
                raise HTTPException(status_code=409, detail='An account with that email already exists. Please use login.')

            user_id = str(uuid4())
            now_str = datetime.now().astimezone().isoformat()
            login_token = _generate_unique_login_token(session)
            role = _default_role_for_user(email, name) or DEFAULT_USER_ROLE
            session.add(UserORM(
                id=user_id,
                google_id=f'local:{uuid4()}',
                email=email,
                name=name,
                role=role,
                login_token=login_token,
                picture_url=None,
                created_at=now_str,
                last_login=now_str,
            ))

    api_token = _issue_api_jwt(user_id, role)
    secure_cookie = _cookie_secure_flag(request)
    response = JSONResponse({
        'ok': True,
        'userId': user_id,
        'name': name,
        'email': email,
        'loginToken': login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={login_token}',
        'apiToken': api_token,
    })
    response.set_cookie(
        key='session_token',
        value=api_token,
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
    _publish_user_resources_updated(user_id)
    return response


@router.post('/auth/email-login/request')
async def request_email_login_link(payload: dict[str, Any]) -> dict[str, Any]:
    email = _sanitize_email_input(str(payload.get('email') or ''), 'email')
    login_url = ''
    user_name = ''
    created_new_user = False

    with DB_LOCK:
        with _db_session() as session:
            user = session.scalar(select(UserORM).where(UserORM.email == email).limit(1))
            if user is None:
                local_name = str(email.split('@', 1)[0] or '').replace('.', ' ').replace('_', ' ').strip()
                user_name = local_name[:120] or 'New User'
                user_id = str(uuid4())
                login_token = _generate_unique_login_token(session)
                now_str = datetime.now().astimezone().isoformat()
                role = _default_role_for_user(email, user_name) or DEFAULT_USER_ROLE
                session.add(UserORM(
                    id=user_id,
                    google_id=f'local:{uuid4()}',
                    email=email,
                    name=user_name,
                    role=role,
                    login_token=login_token,
                    picture_url=None,
                    created_at=now_str,
                    last_login=now_str,
                ))
                login_url = f'{APP_BASE_URL}/?token={login_token}'
                created_new_user = True
            else:
                if not (user.login_token or '').strip():
                    user.login_token = _generate_unique_login_token(session)
                login_url = f'{APP_BASE_URL}/?token={user.login_token}'
                user_name = str(user.name or '').strip()

    if login_url:
        _enqueue_email_send(
            created_new_user=created_new_user,
            email=email,
            name=user_name,
            login_url=login_url,
        )

    return {
        'ok': True,
        'message': 'If your email was valid, a sign-in link has been sent.',
    }


@router.get('/auth/email-login/verify')
async def verify_email_login_link(token: str, request: Request) -> RedirectResponse:
    normalized_token = str(token or '').strip().lower()
    if not _EMAIL_LOGIN_TOKEN_PATTERN.fullmatch(normalized_token):
        return RedirectResponse(url='/?email_login=invalid')

    now = datetime.now().astimezone()
    user_id = ''
    resolved_session_token = ''

    with DB_LOCK:
        with _db_session() as session:
            user = session.scalar(select(UserORM).where(UserORM.email_login_token == normalized_token).limit(1))
            if user is None:
                return RedirectResponse(url='/?email_login=invalid')

            expires_at_raw = str(user.email_login_expires_at or '').strip()
            try:
                expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
            except ValueError:
                expires_at = None

            if expires_at is None or expires_at <= now:
                user.email_login_token = None
                user.email_login_expires_at = None
                return RedirectResponse(url='/?email_login=expired')

            if not (user.login_token or '').strip():
                user.login_token = _generate_unique_login_token(session)

            user.last_login = now.isoformat()
            user.email_login_token = None
            user.email_login_expires_at = None
            user_id = str(user.id)
            resolved_session_token = str(user.login_token or '').strip()

    if not user_id or not resolved_session_token:
        return RedirectResponse(url='/?email_login=invalid')

    api_token = _issue_api_jwt(user_id, user.role or DEFAULT_USER_ROLE)
    response = RedirectResponse(url=f'/?user_id={user_id}')
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='session_token',
        value=api_token,
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
    _publish_user_resources_updated(user_id)
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
        flow.fetch_token(authorization_response=_public_callback_url(request))
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

            pending_link_source_user_id = request.cookies.get('pending_link_source_user_id')
            source_user_id = ''
            if pending_link_source_user_id:
                try:
                    candidate_source_user_id = _sanitize_id_input(pending_link_source_user_id, 'pending_link_source_user_id')
                except HTTPException:
                    candidate_source_user_id = ''
                if candidate_source_user_id and session.get(UserORM, candidate_source_user_id) is not None:
                    source_user_id = candidate_source_user_id

            pending_link_token = request.cookies.get('pending_link_token')
            if not source_user_id and pending_link_token:
                try:
                    pending_link_token = _sanitize_token_input(pending_link_token, 'pending_link_token')
                except HTTPException:
                    pending_link_token = ''
                resolved_source_user_id = _resolve_user_id_from_login_or_api_token(session, pending_link_token)
                if resolved_source_user_id:
                    source_user_id = str(resolved_source_user_id)

            if source_user_id and source_user_id != user_id:
                pending_link_calendar_ids_raw = str(request.cookies.get('pending_link_calendar_ids') or '').strip()
                pending_link_calendar_ids = [
                    value.strip()
                    for value in pending_link_calendar_ids_raw.split(',')
                    if value.strip()
                ]
                requested_calendar_ids = sorted(_sanitize_calendar_ids_input(pending_link_calendar_ids)) if pending_link_calendar_ids else None

                _merge_user_access_from_source(
                    session,
                    source_user_id=source_user_id,
                    target_user_id=user_id,
                    requested_calendar_ids=requested_calendar_ids,
                    approved_by_user_id=user_id,
                )
                _record_user_saved_share_link(session, user_id, source_user_id)

    resolved_session_token = login_token
    if not resolved_session_token:
        raise HTTPException(status_code=500, detail='Failed to resolve a session token for this account.')

    api_token = _issue_api_jwt(user_id, role)
    response = RedirectResponse(url=f'/?user_id={user_id}')
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='session_token',
        value=api_token,
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
    response.delete_cookie(key='pending_link_source_user_id', path='/')
    response.delete_cookie(key='pending_link_calendar_ids', path='/')
    _publish_user_resources_updated(user_id)
    return response
