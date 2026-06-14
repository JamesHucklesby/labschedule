import json
import secrets
from datetime import datetime, timedelta
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
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
from config import APP_BASE_URL, DEFAULT_USER_ROLE, SESSION_COOKIE_SECURE
from database import DB_LOCK, _build_latest_events_stmt, _db_session, _get_user_calendar_ids
from models import CalendarGroupLinkORM, CalendarORM, GroupUserLinkORM, LabGroupORM, UserORM, UserPasskeyORM
from realtime import _publish_user_resources_updated
from schemas import TokenValidationResult
from utils import _sanitize_token_input
from utils import _sanitize_text_input
from utils import _compose_display_title, _orm_calendar_ids, _orm_contact, _orm_event_title, _orm_user_name, _parse_iso_datetime, expand_event_for_window
from media_assets import calendar_placeholder_data_url
from webauthn import generate_registration_options, options_to_json, verify_registration_response
from webauthn import generate_authentication_options, verify_authentication_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

router = APIRouter()
PASSKEY_CHALLENGE_LOCK = Lock()
PASSKEY_CHALLENGES: dict[str, dict[str, Any]] = {}
PASSKEY_CHALLENGE_TTL_SECONDS = 300
PASSKEY_AUTH_CHALLENGES: dict[str, dict[str, Any]] = {}
PASSKEY_AUTH_CHALLENGE_TTL_SECONDS = 300


def _prune_passkey_challenges(now: datetime | None = None) -> None:
    current = now or datetime.utcnow()
    expired_user_ids = [
        user_id
        for user_id, state in PASSKEY_CHALLENGES.items()
        if state.get('expires_at') is None or state['expires_at'] <= current
    ]
    for user_id in expired_user_ids:
        PASSKEY_CHALLENGES.pop(user_id, None)


def _prune_passkey_auth_challenges(now: datetime | None = None) -> None:
    current = now or datetime.utcnow()
    expired_state_ids = [
        state_id
        for state_id, state in PASSKEY_AUTH_CHALLENGES.items()
        if state.get('expires_at') is None or state['expires_at'] <= current
    ]
    for state_id in expired_state_ids:
        PASSKEY_AUTH_CHALLENGES.pop(state_id, None)


def _rp_id_for_request(request: Request) -> str:
    forwarded_host = (request.headers.get('x-forwarded-host') or '').split(',')[0].strip()
    if forwarded_host:
        return forwarded_host.split(':', 1)[0].lower()
    if request.url.hostname:
        return request.url.hostname.lower()
    parsed = urlparse(APP_BASE_URL)
    if parsed.hostname:
        return parsed.hostname.lower()
    return 'localhost'


def _expected_origins_for_request(request: Request) -> list[str]:
    origins: list[str] = []
    origin_header = (request.headers.get('origin') or '').strip()
    if origin_header:
        origins.append(origin_header.rstrip('/'))
    if APP_BASE_URL:
        origins.append(APP_BASE_URL.rstrip('/'))
    # Preserve order while deduplicating.
    return list(dict.fromkeys(origins))


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
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=403, detail='Invalid or expired token.')

    with _db_session() as session:
        calendars = session.scalars(
            select(CalendarORM)
            .where(CalendarORM.id.in_(sorted(allowed)))
            .order_by(CalendarORM.sort_order.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all()

        approved_group_names = set(session.scalars(
            select(GroupUserLinkORM.group_name)
            .where(GroupUserLinkORM.user_id == session_user['id'])
            .where(GroupUserLinkORM.status == 'approved')
            .order_by(GroupUserLinkORM.group_name.asc())
        ).all())

        calendar_group_links = session.scalars(
            select(CalendarGroupLinkORM)
            .where(CalendarGroupLinkORM.calendar_id.in_(sorted(allowed)))
            .order_by(CalendarGroupLinkORM.calendar_id.asc(), CalendarGroupLinkORM.group_name.asc())
        ).all()

    approved_groups_by_calendar_id: dict[str, list[str]] = {}
    for link in calendar_group_links:
        calendar_id = str(link.calendar_id or '').strip()
        group_name = str(link.group_name or '').strip()
        if not calendar_id or not group_name:
            continue
        if approved_group_names and group_name not in approved_group_names:
            continue
        approved_groups_by_calendar_id.setdefault(calendar_id, []).append(group_name)

    deduped: dict[str, dict[str, Any]] = {}
    for calendar in calendars:
        if calendar.id in deduped:
            continue
        approved_groups = sorted({name for name in approved_groups_by_calendar_id.get(calendar.id, []) if name})
        display_group = approved_groups[0] if approved_groups else (calendar.group_name or 'General')
        deduped[calendar.id] = {
            'id': calendar.id,
            'name': calendar.name,
            'sortOrder': int(calendar.sort_order or 0),
            'group': display_group,
            'groups': approved_groups,
            'color': calendar.color,
            'blurb': calendar.blurb,
            'imageUrl': calendar.image_url,
            'imageThumbUrl': calendar.image_thumb_url or calendar.image_url,
            'imageFallbackUrl': calendar_placeholder_data_url(calendar.name, display_group, calendar.color),
        }

    return list(deduped.values())


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


@router.get('/api/users/me/profile')
def get_my_profile(token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    with _db_session() as session:
        user = session.get(UserORM, session_user['id'])
        if user is None:
            raise HTTPException(status_code=404, detail='User not found.')

        name = str(user.name or '').strip()
        email = str(user.email or '').strip()
        contact = str(user.contact or '').strip()
        lab_group = str(user.lab_group or '').strip()
        lab_group_values = session.scalars(
            select(LabGroupORM.name)
            .distinct()
            .order_by(LabGroupORM.name.asc())
        ).all()
        lab_groups = sorted({str(value).strip() for value in lab_group_values if str(value or '').strip()})

    return {
        'user': {
            'id': session_user['id'],
            'name': name,
            'email': email,
            'contact': contact,
            'labGroup': lab_group,
        },
        'labGroups': lab_groups,
        'needsProfile': not (name and contact and lab_group),
    }


@router.put('/api/users/me/profile')
def update_my_profile(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    name = _sanitize_text_input(str(payload.get('name') or ''), 'name', min_length=1, max_length=120)
    contact = _sanitize_text_input(str(payload.get('contact') or ''), 'contact', min_length=1, max_length=254)
    lab_group = _sanitize_text_input(str(payload.get('labGroup') or ''), 'labGroup', min_length=1, max_length=120)

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, session_user['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            old_name = str(user.name or '').strip()
            session.merge(LabGroupORM(name=lab_group))
            session.flush()
            user.name = name
            user.contact = contact
            user.lab_group = lab_group

            if old_name and old_name.casefold() != name.casefold():
                base_stmt, event_alias, _ = _build_latest_events_stmt()
                latest_events = session.scalars(
                    base_stmt.where(event_alias.deleted == 0)
                ).all()
                for event in latest_events:
                    event_user_name = str(_orm_user_name(event) or '').strip()
                    if not event_user_name or event_user_name.casefold() != old_name.casefold():
                        continue
                    event_title = _orm_event_title(event)
                    event.user_name = name
                    event.title = _compose_display_title(name, event_title) or event.title

            lab_group_values = session.scalars(
                select(LabGroupORM.name)
                .distinct()
                .order_by(LabGroupORM.name.asc())
            ).all()
            lab_groups = sorted({str(value).strip() for value in lab_group_values if str(value or '').strip()})

    _publish_user_resources_updated(session_user['id'])
    return {
        'ok': True,
        'user': {
            'id': session_user['id'],
            'name': name,
            'email': str(session_user.get('email') or '').strip(),
            'contact': contact,
            'labGroup': lab_group,
            'profileComplete': True,
        },
        'labGroups': lab_groups,
        'needsProfile': False,
    }


@router.get('/api/users/me/upcoming-bookings')
def list_my_upcoming_bookings(token: str | None = None, horizon_days: int = 90) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    safe_horizon_days = max(1, min(int(horizon_days), 365))
    now = datetime.now().astimezone()
    window_end = now + timedelta(days=safe_horizon_days)

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, session_user['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            if bool(user.service_account):
                return {'bookings': [], 'userName': str(user.name or '').strip(), 'horizonDays': safe_horizon_days}

            user_name = str(user.name or '').strip()
            if not user_name:
                return {'bookings': [], 'userName': '', 'horizonDays': safe_horizon_days}

            allowed_calendar_ids = set(_get_user_allowed_calendars(session, user.id) or set())
            if not allowed_calendar_ids:
                return {'bookings': [], 'userName': user_name, 'horizonDays': safe_horizon_days}

            allowed_calendars = session.scalars(
                select(CalendarORM)
                .where(CalendarORM.id.in_(sorted(allowed_calendar_ids)))
                .order_by(CalendarORM.sort_order.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
            ).all()
            calendar_name_by_id = {calendar.id: str(calendar.name or '').strip() for calendar in allowed_calendars}

            base_stmt, event_alias, _ = _build_latest_events_stmt()
            latest_events = session.scalars(
                base_stmt.where(event_alias.deleted == 0)
                .order_by(event_alias.start.asc())
            ).all()

            normalized_target_name = user_name.casefold()
            bookings: list[dict[str, Any]] = []
            for event in latest_events:
                booking_user_name = str(_orm_user_name(event) or '').strip()
                if not booking_user_name or booking_user_name.casefold() != normalized_target_name:
                    continue

                event_calendar_ids = [
                    calendar_id
                    for calendar_id in _orm_calendar_ids(event)
                    if calendar_id in allowed_calendar_ids
                ]
                if not event_calendar_ids:
                    continue

                instances = expand_event_for_window(event, now, window_end)
                for instance in instances:
                    instance_start = _parse_iso_datetime(instance['start'])
                    instance_end = _parse_iso_datetime(instance['end']) if instance.get('end') else instance_start
                    if instance_end < now:
                        continue

                    instance_calendar_ids = [
                        calendar_id
                        for calendar_id in (instance.get('calendarIds') or [])
                        if calendar_id in allowed_calendar_ids
                    ]
                    if not instance_calendar_ids:
                        continue

                    calendar_names = [
                        calendar_name_by_id.get(calendar_id, calendar_id)
                        for calendar_id in instance_calendar_ids
                    ]
                    bookings.append({
                        'id': instance.get('id'),
                        'title': str(instance.get('title') or ''),
                        'name': booking_user_name,
                        'eventTitle': str(_orm_event_title(event) or ''),
                        'contact': str(_orm_contact(event) or ''),
                        'start': instance.get('start'),
                        'end': instance.get('end'),
                        'allDay': bool(instance.get('allDay')),
                        'committed': bool(instance.get('committed')),
                        'calendarIds': instance_calendar_ids,
                        'calendarNames': calendar_names,
                    })

    bookings.sort(key=lambda booking: str(booking.get('start') or ''))
    return {
        'bookings': bookings,
        'userName': user_name,
        'horizonDays': safe_horizon_days,
    }


@router.get('/api/share-links')
def list_share_links(token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    with _db_session() as session:
        user = session.get(UserORM, session_user['id'])
        if user is None:
            raise HTTPException(status_code=404, detail='User not found.')

        viewer_group_names = {
            str(group_name or '').strip()
            for group_name in session.scalars(
                select(GroupUserLinkORM.group_name)
                .where(GroupUserLinkORM.user_id == user.id)
                .where(GroupUserLinkORM.status == 'approved')
                .order_by(GroupUserLinkORM.group_name.asc())
            ).all()
            if str(group_name or '').strip()
        }

        if bool(user.service_account):
            candidate_service_users = [user]
        else:
            candidate_service_users = session.scalars(
                select(UserORM)
                .where(UserORM.service_account.is_(True))
                .order_by(UserORM.name.asc(), UserORM.id.asc())
            ).all()

        candidate_user_ids = [str(candidate.id) for candidate in candidate_service_users if str(candidate.id or '').strip()]
        group_rows = session.execute(
            select(GroupUserLinkORM.user_id, GroupUserLinkORM.group_name)
            .where(GroupUserLinkORM.status == 'approved')
            .where(GroupUserLinkORM.user_id.in_(candidate_user_ids))
            .order_by(GroupUserLinkORM.user_id.asc(), GroupUserLinkORM.group_name.asc())
        ).all() if candidate_user_ids else []

        groups_by_service_user: dict[str, list[str]] = {}
        for service_user_id, group_name in group_rows:
            normalized_service_user_id = str(service_user_id or '').strip()
            normalized_group_name = str(group_name or '').strip()
            if not normalized_service_user_id or not normalized_group_name:
                continue
            groups_by_service_user.setdefault(normalized_service_user_id, []).append(normalized_group_name)

        eligible_users: list[tuple[UserORM, list[str]]] = []
        all_group_names: set[str] = set()
        for candidate in candidate_service_users:
            candidate_id = str(candidate.id or '').strip()
            candidate_group_names = sorted({
                name for name in groups_by_service_user.get(candidate_id, []) if name
            })
            if not candidate_group_names:
                continue

            # Non-service accounts may only see service-account links when they
            # are approved for every group that the service account carries.
            if not bool(user.service_account):
                if any(group_name not in viewer_group_names for group_name in candidate_group_names):
                    continue

            all_group_names.update(candidate_group_names)
            eligible_users.append((candidate, candidate_group_names))

        calendar_rows = session.execute(
            select(CalendarGroupLinkORM.group_name, CalendarORM.id, CalendarORM.name)
            .join(CalendarORM, CalendarORM.id == CalendarGroupLinkORM.calendar_id)
            .where(CalendarGroupLinkORM.group_name.in_(sorted(all_group_names)))
            .order_by(CalendarGroupLinkORM.group_name.asc(), CalendarORM.sort_order.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all() if all_group_names else []

    calendars_by_group_name: dict[str, list[dict[str, str]]] = {}
    seen_calendar_by_group: dict[str, set[str]] = {}
    for group_name, calendar_id, calendar_name in calendar_rows:
        normalized_group_name = str(group_name or '').strip()
        normalized_calendar_id = str(calendar_id or '').strip()
        if not normalized_group_name or not normalized_calendar_id:
            continue
        bucket = calendars_by_group_name.setdefault(normalized_group_name, [])
        seen_bucket = seen_calendar_by_group.setdefault(normalized_group_name, set())
        if normalized_calendar_id in seen_bucket:
            continue
        seen_bucket.add(normalized_calendar_id)
        bucket.append({
            'id': normalized_calendar_id,
            'name': str(calendar_name or normalized_calendar_id),
        })

    links: list[dict[str, Any]] = []
    for source_user, group_names in eligible_users:
        login_token = str(source_user.login_token or '').strip()
        if not login_token:
            continue
        groups_payload = [
            {
                'name': group_name,
                'calendars': calendars_by_group_name.get(group_name, []),
            }
            for group_name in group_names
        ]
        links.append({
            'token': login_token,
            'name': source_user.name,
            'loginUrl': f'{APP_BASE_URL}/?token={login_token}',
            'type': 'service-account',
            'groups': groups_payload,
        })

    return {'links': links, 'serviceAccount': bool(user.service_account)}


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
    api_token = (
        token
        if _decode_api_jwt(token) is not None
        else _issue_api_jwt(user['id'], user.get('role', DEFAULT_USER_ROLE))
    )
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
        value=user['id'],
        httponly=True,
        samesite='lax',
        secure=secure_cookie,
        path='/',
    )
    return {
        'valid': True,
        'token': token,
        'apiToken': api_token,
        'name': user.get('name'),
        'calendarIds': sorted(allowed_calendars),
    }


@router.get('/api/passkeys')
def list_user_passkeys(token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    with _db_session() as session:
        passkeys = session.scalars(
            select(UserPasskeyORM)
            .where(UserPasskeyORM.user_id == session_user['id'])
            .order_by(UserPasskeyORM.created_at.asc(), UserPasskeyORM.credential_id.asc())
        ).all()

    return {
        'passkeys': [
            {
                'credentialId': passkey.credential_id,
                'name': passkey.name,
                'createdAt': passkey.created_at,
            }
            for passkey in passkeys
        ]
    }


@router.delete('/api/passkeys/{credential_id}')
def delete_user_passkey(credential_id: str, token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    credential_id = _sanitize_text_input(credential_id, 'credential_id', min_length=8, max_length=2048)

    with _db_session() as session:
        passkey = session.scalar(
            select(UserPasskeyORM)
            .where(UserPasskeyORM.credential_id == credential_id)
            .limit(1)
        )
        if passkey is None or passkey.user_id != session_user['id']:
            raise HTTPException(status_code=404, detail='Passkey not found.')
        session.delete(passkey)

    return {'ok': True, 'credentialId': credential_id}


@router.post('/api/passkeys/auth/options')
def passkey_authentication_options(request: Request) -> dict[str, Any]:
    with _db_session() as session:
        passkeys = session.scalars(
            select(UserPasskeyORM)
            .order_by(UserPasskeyORM.credential_id.asc())
        ).all()

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(passkey.credential_id),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for passkey in passkeys
    ]

    rp_id = _rp_id_for_request(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    state_id = secrets.token_urlsafe(24)
    with PASSKEY_CHALLENGE_LOCK:
        _prune_passkey_auth_challenges()
        PASSKEY_AUTH_CHALLENGES[state_id] = {
            'challenge': options.challenge,
            'rp_id': rp_id,
            'expires_at': datetime.utcnow() + timedelta(seconds=PASSKEY_AUTH_CHALLENGE_TTL_SECONDS),
        }

    return {
        'stateId': state_id,
        'publicKey': json.loads(options_to_json(options)),
    }


@router.post('/api/passkeys/auth/verify')
def passkey_authentication_verify(payload: dict[str, Any], request: Request) -> Response:
    state_id = str(payload.get('stateId') or '').strip()
    if not state_id:
        raise HTTPException(status_code=400, detail='Missing passkey auth state.')
    credential_payload = payload.get('credential')
    if not isinstance(credential_payload, dict):
        raise HTTPException(status_code=400, detail='Missing credential payload.')

    with PASSKEY_CHALLENGE_LOCK:
        _prune_passkey_auth_challenges()
        state = PASSKEY_AUTH_CHALLENGES.pop(state_id, None)
    if state is None:
        raise HTTPException(status_code=400, detail='Passkey authentication challenge expired. Please retry.')

    challenge = state.get('challenge')
    rp_id = state.get('rp_id')
    if not isinstance(challenge, bytes) or not isinstance(rp_id, str) or not rp_id:
        raise HTTPException(status_code=400, detail='Invalid passkey authentication challenge.')

    expected_origins = _expected_origins_for_request(request)
    if not expected_origins:
        raise HTTPException(status_code=400, detail='Cannot validate authentication origin.')

    credential_id = str(credential_payload.get('id') or '').strip()
    if not credential_id:
        raise HTTPException(status_code=400, detail='Missing passkey credential ID.')

    with _db_session() as session:
        passkey = session.scalar(
            select(UserPasskeyORM)
            .where(UserPasskeyORM.credential_id == credential_id)
            .limit(1)
        )
        if passkey is None:
            raise HTTPException(status_code=404, detail='Passkey not found.')

        try:
            verification = verify_authentication_response(
                credential=credential_payload,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=expected_origins,
                credential_public_key=base64url_to_bytes(passkey.public_key),
                credential_current_sign_count=int(passkey.sign_count or 0),
                require_user_verification=False,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f'Passkey authentication failed: {exc}') from exc

        passkey.sign_count = int(verification.new_sign_count)
        user = session.get(UserORM, passkey.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail='Passkey user not found.')
        user.last_login = datetime.now().astimezone().isoformat()

        api_token = _issue_api_jwt(user.id, user.role or DEFAULT_USER_ROLE)
        response = JSONResponse({
            'authenticated': True,
            'apiToken': api_token,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'role': user.role or DEFAULT_USER_ROLE,
                'isTokenOnlyAccount': (
                    str(user.google_id or '').startswith('link:')
                    or str(user.google_id or '').startswith('local:')
                ),
            },
        })
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
            value=user.id,
            httponly=True,
            samesite='lax',
            secure=secure_cookie,
            path='/',
        )
        return response


@router.post('/api/passkeys/register/options')
def passkey_registration_options(request: Request, token: str | None = None) -> dict[str, Any]:
    """
    Generate passkey registration options.
    Supports both platform authenticators (biometric/PIN on device) and cross-platform authenticators (security keys).
    Uses resident_key=PREFERRED to enable passkey-style credentials saved to the device.
    """
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    with _db_session() as session:
        user_row = session.get(UserORM, session_user['id'])
        if user_row is None:
            raise HTTPException(status_code=404, detail='User not found.')
        existing_passkeys = session.scalars(
            select(UserPasskeyORM)
            .where(UserPasskeyORM.user_id == user_row.id)
            .order_by(UserPasskeyORM.credential_id.asc())
        ).all()

    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(passkey.credential_id),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for passkey in existing_passkeys
    ]

    rp_id = _rp_id_for_request(request)
    # Platform authenticators: Windows Hello, Touch ID, Face ID, Android biometric
    # Cross-platform authenticators: USB security keys, NFC keys
    # resident_key=PREFERRED enables discoverable credentials (passkeys stored on device)
    # user_verification=PREFERRED enables biometric/PIN protection
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name='Lab Scheduler',
        user_id=str(session_user['id']).encode('utf-8'),
        user_name=str(session_user.get('email') or session_user.get('name') or session_user['id']),
        user_display_name=str(session_user.get('name') or session_user.get('email') or session_user['id']),
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
    )

    with PASSKEY_CHALLENGE_LOCK:
        _prune_passkey_challenges()
        PASSKEY_CHALLENGES[session_user['id']] = {
            'challenge': options.challenge,
            'rp_id': rp_id,
            'expires_at': datetime.utcnow() + timedelta(seconds=PASSKEY_CHALLENGE_TTL_SECONDS),
        }

    return {
        'publicKey': json.loads(options_to_json(options)),
    }


@router.post('/api/passkeys/register/verify')
def passkey_registration_verify(payload: dict[str, Any], request: Request, token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    credential_payload = payload.get('credential')
    if not isinstance(credential_payload, dict):
        raise HTTPException(status_code=400, detail='Missing credential payload.')
    raw_passkey_name = str(payload.get('passkeyName') or '').strip()
    passkey_name = _sanitize_text_input(raw_passkey_name, 'passkeyName', min_length=1, max_length=80) if raw_passkey_name else 'Passkey'

    with PASSKEY_CHALLENGE_LOCK:
        _prune_passkey_challenges()
        state = PASSKEY_CHALLENGES.get(session_user['id'])
        if state is None:
            raise HTTPException(status_code=400, detail='No active passkey registration challenge. Please retry.')
        challenge = state.get('challenge')
        rp_id = state.get('rp_id')

    if not isinstance(challenge, bytes) or not isinstance(rp_id, str) or not rp_id:
        raise HTTPException(status_code=400, detail='Invalid passkey challenge state. Please retry.')

    expected_origins = _expected_origins_for_request(request)
    if not expected_origins:
        raise HTTPException(status_code=400, detail='Cannot validate registration origin.')

    try:
        verification = verify_registration_response(
            credential=credential_payload,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origins,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Passkey validation failed: {exc}') from exc

    credential_id = bytes_to_base64url(verification.credential_id)
    public_key = bytes_to_base64url(verification.credential_public_key)
    sign_count = int(verification.sign_count or 0)
    transports = []
    response_payload = credential_payload.get('response')
    if isinstance(response_payload, dict):
        raw_transports = response_payload.get('transports')
        if isinstance(raw_transports, list):
            transports = [str(value) for value in raw_transports if str(value).strip()]

    with _db_session() as session:
        existing = session.scalar(
            select(UserPasskeyORM)
            .where(UserPasskeyORM.credential_id == credential_id)
            .limit(1)
        )
        if existing is not None and existing.user_id != session_user['id']:
            raise HTTPException(status_code=409, detail='Passkey already registered to another user.')

        if existing is None:
            session.add(UserPasskeyORM(
                credential_id=credential_id,
                user_id=session_user['id'],
                name=passkey_name,
                public_key=public_key,
                sign_count=sign_count,
                transports=json.dumps(transports),
            ))
        else:
            existing.name = passkey_name
            existing.public_key = public_key
            existing.sign_count = sign_count
            existing.transports = json.dumps(transports)

    with PASSKEY_CHALLENGE_LOCK:
        PASSKEY_CHALLENGES.pop(session_user['id'], None)

    return {
        'ok': True,
        'credentialId': credential_id,
    }
