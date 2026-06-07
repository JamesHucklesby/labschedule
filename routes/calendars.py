import json
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from fastapi import HTTPException
from auth import (
    _decode_api_jwt,
    _enforce_token_validation_rate_limit,
    _client_ip_address,
    _get_user_allowed_calendars,
    _issue_api_jwt,
    _require_valid_token,
    _session_user_for_login_or_api_token,
)
from config import DEFAULT_USER_ROLE, SESSION_COOKIE_SECURE
from database import _db_session, _get_user_calendar_ids
from models import CalendarORM, UserORM
from schemas import TokenValidationResult
from utils import _sanitize_token_input
from media_assets import calendar_placeholder_data_url

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


@router.get('/api/calendars')
def list_calendars(token: str | None = None) -> list[dict[str, Any]]:
    allowed = _require_valid_token(token)
    with _db_session() as session:
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
        ).all()
    result = [
        {
            'id': c.id,
            'name': c.name,
            'group': c.group_name,
            'color': c.color,
            'blurb': c.blurb,
            'imageUrl': c.image_url,
            'imageThumbUrl': c.image_thumb_url or c.image_url,
            'imageFallbackUrl': calendar_placeholder_data_url(c.name, c.group_name, c.color),
        }
        for c in calendars
    ]
    return [cal for cal in result if cal['id'] in allowed]


@router.get('/api/links')
def list_links(token: str | None = None) -> list[dict[str, Any]]:
    _require_valid_token(token)
    with _db_session() as session:
        user = session.scalar(select(UserORM).where(UserORM.login_token == token))
    if user is None:
        return []
    with _db_session() as session:
        calendar_ids = _get_user_calendar_ids(session, user.id)
    return [{'token': user.login_token, 'name': user.name, 'calendarIds': calendar_ids}]


@router.get('/api/links/{token}')
def get_link(token: str) -> dict[str, Any]:
    token = _sanitize_token_input(token)
    with _db_session() as session:
        user = session.scalar(select(UserORM).where(UserORM.login_token == token))
    if user is None:
        raise HTTPException(status_code=404, detail='Link not found.')
    with _db_session() as session:
        calendar_ids = _get_user_calendar_ids(session, user.id)
    return {'token': user.login_token, 'name': user.name, 'calendarIds': calendar_ids}


@router.get('/api/session/user')
def get_session_user(token: str | None = None) -> dict[str, Any]:
    user = _session_user_for_login_or_api_token(token)
    if user is None:
        return {'authenticated': False, 'user': None}
    return {'authenticated': True, 'user': user}


@router.get('/api/auth/check-session')
def check_session(request: Request) -> dict[str, Any]:
    """Check if user has a valid session cookie. If so, return user info and token."""
    session_token = request.cookies.get('session_token')
    if not session_token:
        return {'authenticated': False, 'user': None, 'token': None}

    user = _session_user_for_login_or_api_token(session_token)
    if user is None:
        return {'authenticated': False, 'user': None, 'token': None}

    return {
        'authenticated': True,
        'user': user,
        'apiToken': _issue_api_jwt(user['id'], user.get('role', DEFAULT_USER_ROLE)),
    }


@router.get('/api/token/validate/{token}', response_model=TokenValidationResult)
def validate_token_for_landing(token: str, request: Request, response: Response) -> dict[str, Any]:
    _enforce_token_validation_rate_limit(_client_ip_address(request))
    try:
        token = _sanitize_token_input(token)
    except HTTPException:
        response.delete_cookie(key='session_token', path='/')
        response.delete_cookie(key='user_id', path='/')
        return {'valid': False, 'token': token, 'apiToken': None, 'name': None, 'calendarIds': []}
    user = _session_user_for_login_or_api_token(token)
    if user is None:
        response.delete_cookie(key='session_token', path='/')
        response.delete_cookie(key='user_id', path='/')
        return {'valid': False, 'token': token, 'apiToken': None, 'name': None, 'calendarIds': []}

    with _db_session() as session:
        allowed_calendars = _get_user_allowed_calendars(session, user['id']) or set()
    secure_cookie = _cookie_secure_flag(request)
    response.set_cookie(
        key='session_token',
        value=token,
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
    )
    response.set_cookie(
        key='user_id',
        value=user['id'],
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
    )
    api_token = (
        token
        if _decode_api_jwt(token) is not None
        else _issue_api_jwt(user['id'], user.get('role', DEFAULT_USER_ROLE))
    )

    return {
        'valid': True,
        'token': token,
        'apiToken': api_token,
        'name': user.get('name'),
        'calendarIds': sorted(allowed_calendars),
    }
