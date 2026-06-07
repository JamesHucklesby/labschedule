import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from auth import (
    _build_google_flow,
    _consume_oauth_state,
    _default_role_for_user,
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
)
from database import DB_LOCK, _db_session, _generate_unique_login_token
from models import UserORM

router = APIRouter()


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
    print(f'[oauth] callback start email={email} google_id={google_id}')
    with DB_LOCK:
        with _db_session() as session:
            existing = session.scalar(select(UserORM).where(UserORM.google_id == google_id))

            if existing:
                user_id = existing.id
                login_token = (existing.login_token or '').strip()
                print(f'[oauth] existing user found user_id={user_id}')
                existing.email = email
                existing.name = name
                if email in ADMIN_USER_EMAILS or name in ADMIN_USER_NAMES:
                    existing.role = 'admin'
                existing.picture_url = picture_url
                existing.last_login = datetime.now().astimezone().isoformat()
            else:
                login_token = _generate_unique_login_token(session)
                print(f'[oauth] creating first-time user user_id={user_id}')
                now_str = datetime.now().astimezone().isoformat()
                session.add(UserORM(
                    id=user_id,
                    google_id=google_id,
                    email=email,
                    name=name,
                    role=role,
                    login_token=login_token,
                    picture_url=picture_url,
                    calendar_ids=json.dumps([]),
                    created_at=now_str,
                    last_login=now_str,
                ))

            if not login_token:
                login_token = _generate_unique_login_token(session)
                if existing:
                    existing.login_token = login_token
            print(f'[oauth] commit complete user_id={user_id}')

    resolved_session_token = login_token
    if not resolved_session_token:
        print(f'[oauth] ERROR no resolved session token for user_id={user_id}')
        raise HTTPException(status_code=500, detail='Failed to resolve a session token for this account.')

    response = RedirectResponse(url=f'/?token={resolved_session_token}&user_id={user_id}')
    response.set_cookie(
        key='session_token',
        value=resolved_session_token,
        httponly=True,
        samesite='lax',
        secure=False,
        path='/',
    )
    response.set_cookie(
        key='user_id',
        value=user_id,
        httponly=True,
        samesite='lax',
        secure=False,
        path='/',
    )
    return response
