import json
import mimetypes
import secrets
import base64
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select

from auth import (
    _get_user_allowed_calendars,
    _require_admin_user,
    _resolve_user_id_from_login_or_api_token,
    _session_user_for_login_or_api_token,
)
from config import APP_BASE_URL, DEFAULT_USER_ROLE
from database import (
    DB_LOCK,
    _db_session,
    _ensure_group_names,
    _generate_unique_local_email,
    _generate_unique_login_token,
    _get_user_calendar_ids,
    _get_user_group_names_from_links,
    _replace_user_calendar_links,
    _replace_user_group_links,
    _replace_calendar_group_links,
    _upsert_user_calendar_link,
    _upsert_user_group_link,
)
from models import CalendarORM, GroupORM, GroupUserLinkORM, UserCalendarLinkORM, UserORM
from realtime import _publish_user_resources_updated
from realtime import _publish_calendar_change
from schemas import (
    AdminUserCreateRequest,
    CalendarAdminUpdateRequest,
    CalendarGroupUpdate,
    CalendarAccessClaimRequest,
    GroupCreateRequest,
    GroupResourceCreateRequest,
    LinkCreateRequest,
    LinkResourceUpdate,
)
from utils import _sanitize_calendar_ids_input, _sanitize_email_input, _sanitize_id_input, _sanitize_text_input, _sanitize_token_input
from media_assets import (
    create_calendar_thumbnail_data_url,
)

router = APIRouter()
def _calendar_image_extension(upload: UploadFile) -> str:
    filename_suffix = Path(upload.filename or '').suffix.lower()
    if filename_suffix in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}:
        return '.jpg' if filename_suffix == '.jpeg' else filename_suffix
    guessed_suffix = mimetypes.guess_extension(upload.content_type or '') or ''
    if guessed_suffix == '.jpe':
        guessed_suffix = '.jpg'
    if guessed_suffix in {'.png', '.jpg', '.gif', '.webp', '.bmp', '.svg'}:
        return guessed_suffix
    raise HTTPException(status_code=400, detail='Please upload a valid image file.')


def _group_names_for_calendar_ids(session, calendar_ids: list[str]) -> list[str]:
    group_names = session.scalars(
        select(CalendarORM.group_name)
        .where(CalendarORM.id.in_(calendar_ids))
        .where(CalendarORM.group_name.isnot(None))
        .where(func.trim(CalendarORM.group_name) != '')
        .distinct()
        .order_by(CalendarORM.group_name.asc())
    ).all()
    return [group_name for group_name in group_names if group_name]


def _user_calendar_link(session, user_id: str, calendar_id: str) -> UserCalendarLinkORM | None:
    return session.get(UserCalendarLinkORM, (user_id, calendar_id))


def _user_group_link(session, user_id: str, group_name: str):
    return session.get(GroupUserLinkORM, (group_name, user_id))


def _link_state_to_request_state(status: str | None) -> str:
    normalized = str(status or '').strip().lower()
    if normalized in {'approved', 'requested', 'hidden'}:
        return normalized
    return 'available'


def _link_status_to_button_state(status: str | None, fallback_has_access: bool = False) -> str:
    normalized = str(status or '').strip().lower()
    if normalized in {'approved', 'requested', 'hidden'}:
        return normalized
    return 'granted' if fallback_has_access else 'available'


def _normalize_access_request_target_type(target_type: str) -> str:
    normalized = str(target_type or '').strip().lower()
    if normalized not in {'calendar', 'group'}:
        raise HTTPException(status_code=400, detail='Unsupported access request target.')
    return normalized


def _normalize_access_request_target_id(target_type: str, target_id: str) -> str:
    if target_type == 'calendar':
        return _sanitize_id_input(target_id, 'target_id')
    return _sanitize_text_input(target_id, 'target_id', min_length=1, max_length=120)


def _build_access_link_request_id(user_id: str, target_type: str, target_id: str) -> str:
    normalized_target_type = _normalize_access_request_target_type(target_type)
    normalized_target_id = _normalize_access_request_target_id(normalized_target_type, target_id)
    payload = {
        'u': _sanitize_id_input(user_id, 'user_id'),
        't': normalized_target_type,
        'i': normalized_target_id,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode('utf-8')).decode('ascii')
    return encoded.rstrip('=')


def _decode_access_link_request_id(request_id: str) -> tuple[str, str, str]:
    encoded = str(request_id or '').strip()
    if not encoded:
        raise HTTPException(status_code=400, detail='Invalid access request identifier.')

    padded = encoded + ('=' * ((4 - len(encoded) % 4) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
        payload = json.loads(decoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid access request identifier.') from exc

    user_id = _sanitize_id_input(str(payload.get('u') or ''), 'user_id')
    target_type = _normalize_access_request_target_type(str(payload.get('t') or ''))
    target_id = _normalize_access_request_target_id(target_type, str(payload.get('i') or ''))
    return user_id, target_type, target_id


def _sanitize_group_names_input(session, group_names: list[str] | None) -> list[str]:
    sanitized = []
    seen: set[str] = set()
    for group_name in group_names or []:
        normalized = _sanitize_text_input(group_name, 'groupNames', min_length=1, max_length=120)
        if normalized in seen:
            continue
        seen.add(normalized)
        sanitized.append(normalized)
    if not sanitized:
        return []
    existing = set(session.scalars(select(GroupORM.name).where(GroupORM.name.in_(sanitized))).all())
    missing = [group_name for group_name in sanitized if group_name not in existing]
    if missing:
        raise HTTPException(status_code=404, detail=f'Unknown groups: {", ".join(missing)}')
    return sanitized


def _access_request_target_calendar_ids(session, target_type: str, target_id: str) -> list[str]:
    if target_type == 'calendar':
        calendar = session.get(CalendarORM, target_id)
        if calendar is None:
            raise HTTPException(status_code=404, detail='Requested calendar not found.')
        return [calendar.id]

    group = session.get(GroupORM, target_id)
    if group is None:
        raise HTTPException(status_code=404, detail='Requested group not found.')

    calendar_ids = session.scalars(
        select(CalendarORM.id)
        .where(CalendarORM.group_name == target_id)
        .order_by(CalendarORM.name.asc())
    ).all()
    return [str(calendar_id) for calendar_id in calendar_ids if calendar_id]


def _serialize_access_link_request(
    session,
    *,
    requester_user_id: str,
    target_type: str,
    target_id: str,
    status: str,
    requested_at: str | None,
    reviewed_at: str | None = None,
    reviewed_by_user_id: str | None = None,
) -> dict[str, Any]:
    requester = session.get(UserORM, requester_user_id)
    target_type = _normalize_access_request_target_type(target_type)
    target_id = _normalize_access_request_target_id(target_type, target_id)
    target_calendar_ids = _access_request_target_calendar_ids(session, target_type, target_id)
    if target_type == 'calendar':
        calendar = session.get(CalendarORM, target_id)
        target_label = calendar.name if calendar else target_id
        group_name = calendar.group_name if calendar else None
    else:
        target_label = target_id
        group_name = target_id
    return {
        'id': _build_access_link_request_id(requester_user_id, target_type, target_id),
        'targetType': target_type,
        'targetId': target_id,
        'targetLabel': target_label,
        'groupName': group_name,
        'calendarIds': target_calendar_ids,
        'requesterId': requester.id if requester else requester_user_id,
        'requesterName': requester.name if requester else '',
        'requesterEmail': requester.email if requester else '',
        'requestedAt': requested_at,
        'reviewedAt': reviewed_at,
        'reviewedByUserId': reviewed_by_user_id,
        'status': status,
    }


def _list_access_requests(session, statuses: set[str] | None = None) -> list[dict[str, Any]]:
    normalized_statuses = {str(status).strip().lower() for status in (statuses or {'requested', 'hidden', 'approved'})}
    normalized_statuses.discard('')

    requests: list[dict[str, Any]] = []
    calendar_links = session.scalars(
        select(UserCalendarLinkORM)
        .where(UserCalendarLinkORM.status.in_(sorted(normalized_statuses)))
    ).all()
    for link in calendar_links:
        requests.append(
            _serialize_access_link_request(
                session,
                requester_user_id=link.user_id,
                target_type='calendar',
                target_id=link.calendar_id,
                status=str(link.status or '').strip().lower(),
                requested_at=link.requested_at,
                reviewed_at=link.approved_at,
                reviewed_by_user_id=link.approved_by_user_id,
            )
        )

    group_links = session.scalars(
        select(GroupUserLinkORM)
        .where(GroupUserLinkORM.status.in_(sorted(normalized_statuses)))
    ).all()
    for link in group_links:
        requests.append(
            _serialize_access_link_request(
                session,
                requester_user_id=link.user_id,
                target_type='group',
                target_id=link.group_name,
                status=str(link.status or '').strip().lower(),
                requested_at=link.requested_at,
                reviewed_at=link.approved_at,
                reviewed_by_user_id=link.approved_by_user_id,
            )
        )

    requests.sort(key=lambda request: request.get('requestedAt') or '', reverse=True)
    requests.sort(key=lambda request: {'requested': 0, 'hidden': 1, 'approved': 2}.get(str(request.get('status') or ''), 3))
    return requests


def _list_admin_groups(session) -> list[dict[str, Any]]:
    group_rows = session.scalars(select(GroupORM).order_by(GroupORM.name.asc())).all()
    calendars = session.scalars(
        select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
    ).all()
    calendars_by_group: dict[str, list[dict[str, Any]]] = {}
    for calendar in calendars:
        calendars_by_group.setdefault(calendar.group_name or 'General', []).append({
            'id': calendar.id,
            'name': calendar.name,
            'group': calendar.group_name or 'General',
            'color': calendar.color,
        })

    groups: list[dict[str, Any]] = []
    for group in group_rows:
        group_calendars = calendars_by_group.get(group.name, [])
        groups.append({
            'name': group.name,
            'calendarIds': [calendar['id'] for calendar in group_calendars],
            'calendars': group_calendars,
            'resourceCount': len(group_calendars),
        })
    return groups


@router.get('/api/access/catalog')
def access_catalog_for_user(token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    with _db_session() as session:
        accessible_calendar_ids = set(_get_user_calendar_ids(session, session_user['id']) or [])
        group_rows = session.scalars(
            select(GroupORM).order_by(GroupORM.name.asc())
        ).all()
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
        ).all()
        calendar_links = {
            link.calendar_id: link
            for link in session.scalars(
                select(UserCalendarLinkORM)
                .where(UserCalendarLinkORM.user_id == session_user['id'])
            ).all()
        }
        group_links = {
            link.group_name: link
            for link in session.scalars(
                select(GroupUserLinkORM)
                .where(GroupUserLinkORM.user_id == session_user['id'])
            ).all()
        }

    grouped_calendars: dict[str, list[dict[str, Any]]] = {}
    group_names: list[str] = []
    seen_group_names: set[str] = set()
    for group in group_rows:
        if group.name not in seen_group_names:
            seen_group_names.add(group.name)
            group_names.append(group.name)
    for calendar in calendars:
        group_name = calendar.group_name or 'General'
        if group_name not in seen_group_names:
            seen_group_names.add(group_name)
            group_names.append(group_name)
        group_bucket = grouped_calendars.setdefault(group_name, [])
        calendar_link = calendar_links.get(calendar.id)
        group_link = group_links.get(group_name)
        calendar_request_status = _link_state_to_request_state(calendar_link.status if calendar_link else None)
        group_request_status = _link_state_to_request_state(group_link.status if group_link else None)
        has_access = calendar.id in accessible_calendar_ids
        calendar_request_id = _build_access_link_request_id(session_user['id'], 'calendar', calendar.id) if calendar_request_status in {'requested', 'approved', 'hidden'} else None
        group_request_id = _build_access_link_request_id(session_user['id'], 'group', group_name) if group_request_status in {'requested', 'approved', 'hidden'} else None
        request_id = calendar_request_id or group_request_id
        request_target_type = 'calendar' if calendar_request_id else 'group' if group_request_id else None
        request_state = calendar_request_status if calendar_request_status != 'available' else (
            group_request_status if group_request_status != 'available' else ('granted' if has_access else 'available')
        )
        group_bucket.append({
            'id': calendar.id,
            'name': calendar.name,
            'group': group_name,
            'color': calendar.color,
            'hasAccess': has_access,
            'requestId': request_id,
            'requestTargetType': request_target_type,
            'requestState': request_state,
        })

    groups: list[dict[str, Any]] = []
    for group_name in group_names:
        group_calendars = grouped_calendars.get(group_name, [])
        group_link = group_links.get(group_name)
        group_request_status = _link_state_to_request_state(group_link.status if group_link else None)
        has_access = group_request_status == 'approved'
        request_state = group_request_status
        group_request_id = _build_access_link_request_id(session_user['id'], 'group', group_name) if group_request_status in {'requested', 'approved', 'hidden'} else None
        groups.append({
            'name': group_name,
            'calendars': group_calendars,
            'hasAccess': has_access,
            'requestId': group_request_id,
            'requestTargetType': 'group' if group_request_id else None,
            'requestState': request_state,
        })

    return {'groups': groups}


@router.post('/api/access-requests')
def create_access_request(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    target_type = _normalize_access_request_target_type(str(payload.get('targetType') or ''))
    target_id = _normalize_access_request_target_id(target_type, str(payload.get('targetId') or ''))

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, session_user['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')

            target_calendar_ids = _access_request_target_calendar_ids(session, target_type, target_id)
            current_calendar_ids = set(_get_user_calendar_ids(session, user.id) or [])

            if target_type == 'calendar' and target_id in current_calendar_ids:
                raise HTTPException(status_code=409, detail='You already have access to this calendar.')
            if target_type == 'group':
                existing_group_link = _user_group_link(session, user.id, target_id)
                existing_group_status = str(existing_group_link.status or '').strip().lower() if existing_group_link else ''
                if existing_group_status == 'approved':
                    raise HTTPException(status_code=409, detail='You already have access to this group.')
                if existing_group_status == 'hidden':
                    raise HTTPException(status_code=409, detail='This access is hidden. Use Show Group to restore it.')
                if existing_group_status == 'requested':
                    raise HTTPException(status_code=409, detail='A request for this access is already pending.')

            if target_type == 'calendar':
                link_row = _user_calendar_link(session, user.id, target_id)
                existing_status = str(link_row.status or '').strip().lower() if link_row else ''
                if existing_status == 'requested':
                    raise HTTPException(status_code=409, detail='A request for this access is already pending.')
                if existing_status == 'hidden':
                    raise HTTPException(status_code=409, detail='This access is hidden. Use Show Group to restore it.')
                if existing_status == 'approved':
                    raise HTTPException(status_code=409, detail='You already have access. Use Hide Group to hide it.')
            else:
                link_row = _user_group_link(session, user.id, target_id)
                existing_status = str(link_row.status or '').strip().lower() if link_row else ''
                if existing_status == 'requested':
                    raise HTTPException(status_code=409, detail='A request for this access is already pending.')
                if existing_status == 'hidden':
                    raise HTTPException(status_code=409, detail='This access is hidden. Use Show Group to restore it.')
                if existing_status == 'approved':
                    raise HTTPException(status_code=409, detail='You already have access. Use Hide Group to hide it.')

            pending_group_links = session.scalars(
                select(GroupUserLinkORM)
                .where(GroupUserLinkORM.user_id == user.id)
                .where(GroupUserLinkORM.status == 'requested')
            ).all()
            pending_calendar_links = session.scalars(
                select(UserCalendarLinkORM)
                .where(UserCalendarLinkORM.user_id == user.id)
                .where(UserCalendarLinkORM.status == 'requested')
            ).all()

            for pending_group_link in pending_group_links:
                if target_type == 'calendar' and target_id in _access_request_target_calendar_ids(session, 'group', pending_group_link.group_name):
                    raise HTTPException(status_code=409, detail='A group request covering this calendar is already pending.')
            for pending_calendar_link in pending_calendar_links:
                if target_type == 'group' and pending_calendar_link.calendar_id in target_calendar_ids:
                    raise HTTPException(status_code=409, detail='Individual calendar requests are already pending for this group.')

            requested_at = datetime.now().astimezone().isoformat()
            if target_type == 'calendar':
                _upsert_user_calendar_link(
                    session,
                    user.id,
                    target_id,
                    status='requested',
                    requested_at=requested_at,
                )
            else:
                _upsert_user_group_link(
                    session,
                    user.id,
                    target_id,
                    status='requested',
                    requested_at=requested_at,
                )
            serialized = _serialize_access_link_request(
                session,
                requester_user_id=user.id,
                target_type=target_type,
                target_id=target_id,
                status='requested',
                requested_at=requested_at,
            )

    return {'ok': True, 'request': serialized}


@router.post('/api/access-requests/{request_id}/toggle-visibility')
def toggle_access_request_visibility_for_user(request_id: str, token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')
    requester_user_id, target_type, target_id = _decode_access_link_request_id(request_id)
    if requester_user_id != session_user['id']:
        raise HTTPException(status_code=403, detail='You can only change your own access requests.')

    with DB_LOCK:
        with _db_session() as session:
            if target_type == 'calendar':
                link_row = _user_calendar_link(session, session_user['id'], target_id)
            else:
                link_row = _user_group_link(session, session_user['id'], target_id)
            if link_row is None:
                raise HTTPException(status_code=404, detail='Access request not found.')

            current_status = str(link_row.status or '').strip().lower()
            if current_status not in {'approved', 'hidden'}:
                raise HTTPException(status_code=409, detail='Only granted access can be hidden or restored.')

            next_status = 'hidden' if current_status == 'approved' else 'approved'

            now_str = datetime.now().astimezone().isoformat()
            if target_type == 'calendar':
                _upsert_user_calendar_link(
                    session,
                    session_user['id'],
                    target_id,
                    status=next_status,
                    approved_by_user_id=session_user['id'],
                    approved_at=now_str,
                    requested_at=link_row.requested_at,
                )
            else:
                _upsert_user_group_link(
                    session,
                    session_user['id'],
                    target_id,
                    status=next_status,
                    approved_by_user_id=session_user['id'],
                    approved_at=now_str,
                    requested_at=link_row.requested_at,
                )
            updated_calendar_ids = sorted(_get_user_allowed_calendars(session, session_user['id']) or set())
            serialized = _serialize_access_link_request(
                session,
                requester_user_id=session_user['id'],
                target_type=target_type,
                target_id=target_id,
                status=next_status,
                requested_at=link_row.requested_at,
                reviewed_at=now_str,
                reviewed_by_user_id=session_user['id'],
            )

    _publish_user_resources_updated(session_user['id'])
    return {'ok': True, 'request': serialized, 'calendarIds': updated_calendar_ids}


@router.post('/api/access-requests/toggle-visibility')
def toggle_access_request_visibility_for_target(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')

    target_type = _normalize_access_request_target_type(str(payload.get('targetType') or ''))
    target_id = _normalize_access_request_target_id(target_type, str(payload.get('targetId') or ''))

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, session_user['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')

            existing_link = _user_calendar_link(session, user.id, target_id) if target_type == 'calendar' else _user_group_link(session, user.id, target_id)

            target_calendar_ids = _access_request_target_calendar_ids(session, target_type, target_id)
            current_calendar_ids = set(_get_user_calendar_ids(session, user.id) or [])
            current_status = str(existing_link.status or '').strip().lower() if existing_link else ''

            if not current_status and not all(calendar_id in current_calendar_ids for calendar_id in target_calendar_ids):
                raise HTTPException(status_code=409, detail='Only granted access can be hidden or restored.')

            if not current_status:
                next_status = 'hidden'
                requested_at = datetime.now().astimezone().isoformat()
            else:
                if current_status == 'approved':
                    next_status = 'hidden'
                elif current_status == 'hidden':
                    next_status = 'approved'
                else:
                    raise HTTPException(status_code=409, detail='Only granted access can be hidden or restored.')
                requested_at = existing_link.requested_at

            now_str = datetime.now().astimezone().isoformat()
            if target_type == 'calendar':
                _upsert_user_calendar_link(
                    session,
                    user.id,
                    target_id,
                    status=next_status,
                    approved_by_user_id=user.id if next_status == 'approved' else None,
                    approved_at=now_str if next_status == 'approved' else None,
                    requested_at=requested_at,
                )
            else:
                _upsert_user_group_link(
                    session,
                    user.id,
                    target_id,
                    status=next_status,
                    approved_by_user_id=user.id if next_status == 'approved' else None,
                    approved_at=now_str if next_status == 'approved' else None,
                    requested_at=requested_at,
                )
            updated_calendar_ids = sorted(_get_user_allowed_calendars(session, user.id) or set())
            serialized = _serialize_access_link_request(
                session,
                requester_user_id=user.id,
                target_type=target_type,
                target_id=target_id,
                status=next_status,
                requested_at=requested_at,
                reviewed_at=now_str,
                reviewed_by_user_id=user.id,
            )

    _publish_user_resources_updated(session_user['id'])
    return {'ok': True, 'request': serialized, 'calendarIds': updated_calendar_ids}


@router.delete('/api/access-requests/{request_id}')
def withdraw_access_request_for_user(request_id: str, token: str | None = None) -> dict[str, Any]:
    session_user = _session_user_for_login_or_api_token(token)
    if session_user is None:
        raise HTTPException(status_code=401, detail='Login required.')
    requester_user_id, target_type, target_id = _decode_access_link_request_id(request_id)
    if requester_user_id != session_user['id']:
        raise HTTPException(status_code=403, detail='You can only withdraw your own access requests.')

    with DB_LOCK:
        with _db_session() as session:
            if target_type == 'calendar':
                link_row = _user_calendar_link(session, session_user['id'], target_id)
            else:
                link_row = _user_group_link(session, session_user['id'], target_id)
            if link_row is None:
                raise HTTPException(status_code=404, detail='Access request not found.')
            if str(link_row.status or '').strip().lower() != 'requested':
                raise HTTPException(status_code=409, detail='Only pending access requests can be withdrawn.')

            request_payload = _serialize_access_link_request(
                session,
                requester_user_id=session_user['id'],
                target_type=target_type,
                target_id=target_id,
                status='requested',
                requested_at=link_row.requested_at,
            )
            session.delete(link_row)

    return {'ok': True, 'withdrawn': True, 'request': request_payload}


@router.post('/api/admin/access-requests/{request_id}/approve')
def approve_access_request_for_admin(request_id: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    admin_user = _session_user_for_login_or_api_token(token)
    target_user_id, target_type, target_id = _decode_access_link_request_id(request_id)

    with DB_LOCK:
        with _db_session() as session:
            target_user = session.get(UserORM, target_user_id)
            if target_user is None:
                raise HTTPException(status_code=404, detail='User not found.')

            if target_type == 'calendar':
                link_row = _user_calendar_link(session, target_user.id, target_id)
            else:
                link_row = _user_group_link(session, target_user.id, target_id)
            if link_row is None or str(link_row.status or '').strip().lower() != 'requested':
                raise HTTPException(status_code=404, detail='Access request not found.')

            approved_at = datetime.now().astimezone().isoformat()
            if target_type == 'calendar':
                _upsert_user_calendar_link(
                    session,
                    target_user.id,
                    target_id,
                    status='approved',
                    approved_by_user_id=admin_user['id'] if admin_user else None,
                    approved_at=approved_at,
                    requested_at=link_row.requested_at,
                )
            else:
                _upsert_user_group_link(
                    session,
                    target_user.id,
                    target_id,
                    status='approved',
                    approved_by_user_id=admin_user['id'] if admin_user else None,
                    approved_at=approved_at,
                    requested_at=link_row.requested_at,
                )
            merged_calendar_ids = sorted(_get_user_allowed_calendars(session, target_user.id) or set())


    _publish_user_resources_updated(target_user.id)
    return {'ok': True, 'approved': True, 'requestId': request_id, 'userId': target_user.id, 'calendarIds': merged_calendar_ids}


def _refresh_user_group_names(session, user_ids: list[str] | None = None) -> None:
    # Group membership now lives only in group_user_links; this helper keeps the
    # call sites stable while making the refresh a no-op.
    return


def _prefer_admin_session_cookie(request: Request, token: str | None) -> str | None:
    cookie_token = request.cookies.get('session_token')
    if cookie_token:
        cookie_user = _session_user_for_login_or_api_token(cookie_token)
        if cookie_user is not None and cookie_user.get('role') == 'admin':
            return cookie_token
    header_token = request.headers.get('x-session-token') or request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if header_token:
        return header_token
    return token or cookie_token


@router.get('/api/admin/links')
def list_links_for_admin(token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    with _db_session() as session:
        link_users = session.scalars(
            select(UserORM)
            .where(UserORM.login_token.isnot(None))
            .where(func.trim(UserORM.login_token) != '')
            .order_by(UserORM.name.asc(), UserORM.login_token.asc())
        ).all()
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color} for c in calendars]

        resource_groups: dict[str, list[str]] = {}
        for resource in resources:
            resource_groups.setdefault(resource['group'] or 'General', []).append(resource['id'])

        links: list[dict[str, Any]] = []
        for u in link_users:
            calendar_ids = _get_user_calendar_ids(session, u.id)
            links.append({
                'token': u.login_token,
                'name': u.name,
                'calendarIds': calendar_ids,
                'userEmail': u.email,
                'userName': u.name,
            })

    return {'links': links, 'resources': resources, 'resourceGroups': resource_groups}


@router.put('/api/admin/links/{link_token}/resources')
def update_link_resources_for_admin(
    link_token: str, payload: LinkResourceUpdate, token: str | None = None
) -> dict[str, Any]:
    _require_admin_user(token)
    admin_user = _session_user_for_login_or_api_token(token)
    link_token = _sanitize_token_input(link_token, 'link_token')
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.calendarIds))
    with DB_LOCK:
        with _db_session() as session:
            user = session.scalar(select(UserORM).where(UserORM.login_token == link_token))
            if user is None:
                raise HTTPException(status_code=404, detail='Link not found.')
            valid_ids = set(session.scalars(select(CalendarORM.id)).all())
            invalid_ids = [cal_id for cal_id in calendar_ids if cal_id not in valid_ids]
            if invalid_ids:
                raise HTTPException(status_code=400, detail=f'Unknown resources: {", ".join(invalid_ids)}')
            now_str = datetime.now().astimezone().isoformat()
            _replace_user_calendar_links(
                session,
                user.id,
                calendar_ids,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )

    return {'ok': True, 'token': link_token, 'calendarIds': calendar_ids}


@router.post('/api/admin/links')
def create_link_for_admin(payload: LinkCreateRequest, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    admin_user = _session_user_for_login_or_api_token(token)
    link_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    requested_token = _sanitize_token_input(payload.token, 'token') if payload.token else ''
    link_token = requested_token or secrets.token_hex(16)
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.calendarIds))

    with DB_LOCK:
            now_str = datetime.now().astimezone().isoformat()
            _replace_user_calendar_links(
                session,
                user.id,
                calendar_ids,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )
            existing = session.scalar(select(UserORM.id).where(UserORM.login_token == link_token))
            if existing is not None:
                raise HTTPException(status_code=409, detail='Token already exists. Choose a different token.')
            valid_ids = set(session.scalars(select(CalendarORM.id)).all())
            invalid_ids = [cal_id for cal_id in calendar_ids if cal_id not in valid_ids]
            if invalid_ids:
                raise HTTPException(status_code=400, detail=f'Unknown resources: {", ".join(invalid_ids)}')
            now_str = datetime.now().astimezone().isoformat()
            user = UserORM(
                id=str(uuid4()),
                google_id=f'link:{uuid4()}',
                email=f'link-{uuid4().hex[:12]}@local.invalid',
                name=link_name,
                role='user',
                login_token=link_token,
                picture_url=None,
                created_at=now_str,
                last_login=now_str,
            )
            session.add(user)
            now_str = datetime.now().astimezone().isoformat()
            _replace_user_calendar_links(
                session,
                user.id,
                calendar_ids,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )

    return {'ok': True, 'token': link_token, 'name': link_name, 'calendarIds': calendar_ids}


@router.delete('/api/admin/links/{link_token}')
def delete_link_for_admin(link_token: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    link_token = _sanitize_token_input(link_token, 'link_token')

    with DB_LOCK:
        with _db_session() as session:
            user = session.scalar(select(UserORM).where(UserORM.login_token == link_token))
            if user is None:
                raise HTTPException(status_code=404, detail='Link not found.')
            if not str(user.google_id).startswith('link:'):
                raise HTTPException(
                    status_code=400,
                    detail='Cannot delete a real user login token from Link Access Manager.',
                )
            session.delete(user)

    return {'ok': True, 'token': link_token}


@router.get('/api/admin/users')
def list_users_for_admin(token: str | None = None) -> dict[str, Any]:
    from sqlalchemy import case as sa_case
    _require_admin_user(token)
    with _db_session() as session:
        user_rows = session.scalars(
            select(UserORM).order_by(
                sa_case((UserORM.role == 'admin', 0), else_=1).asc(),
                UserORM.name.asc(),
                UserORM.email.asc(),
            )
        ).all()
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color} for c in calendars]

        resource_groups: dict[str, list[str]] = {}
        for resource in resources:
            resource_groups.setdefault(resource['group'] or 'General', []).append(resource['id'])

        users: list[dict[str, Any]] = []
        for u in user_rows:
            calendar_ids = _get_user_calendar_ids(session, u.id)
            group_names = _get_user_group_names_from_links(session, u.id)
            users.append({
                'id': u.id,
                'email': u.email,
                'name': u.name,
                'role': u.role or DEFAULT_USER_ROLE,
                'pictureUrl': u.picture_url,
                'calendarIds': calendar_ids,
                'groupName': group_names[0] if group_names else None,
                'groupNames': group_names,
                'createdAt': u.created_at,
                'lastLogin': u.last_login,
                'loginToken': u.login_token,
                'loginUrl': f'{APP_BASE_URL}/?token={u.login_token}' if u.login_token else '',
            })

        groups = _list_admin_groups(session)
        access_requests = _list_access_requests(session, {'requested', 'hidden', 'approved'})

    return {'users': users, 'resources': resources, 'resourceGroups': resource_groups, 'groups': groups, 'accessRequests': access_requests}


@router.get('/api/admin/groups')
def list_groups_for_admin(token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    with _db_session() as session:
        groups = _list_admin_groups(session)
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.group_name.asc(), CalendarORM.name.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color} for c in calendars]

    resource_groups: dict[str, list[str]] = {}
    for resource in resources:
        resource_groups.setdefault(resource['group'] or 'General', []).append(resource['id'])

    return {'groups': groups, 'resources': resources, 'resourceGroups': resource_groups}


@router.post('/api/admin/groups')
def create_group_for_admin(payload: GroupCreateRequest, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    group_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    with DB_LOCK:
        with _db_session() as session:
            existing = session.scalar(select(GroupORM.name).where(GroupORM.name == group_name))
            if existing is not None:
                raise HTTPException(status_code=409, detail='Group already exists.')
            session.add(GroupORM(name=group_name))
    return {'ok': True, 'group': {'name': group_name, 'calendarIds': [], 'calendars': [], 'resourceCount': 0}}


@router.put('/api/admin/groups/{group_name}')
def rename_group_for_admin(group_name: str, payload: GroupCreateRequest, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    old_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    new_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    if old_name == 'General':
        raise HTTPException(status_code=400, detail='The General group cannot be renamed.')
    if new_name == 'General':
        raise HTTPException(status_code=400, detail='Use the existing General group instead of renaming to it.')

    with DB_LOCK:
        with _db_session() as session:
            group = session.scalar(select(GroupORM).where(GroupORM.name == old_name))
            if group is None:
                raise HTTPException(status_code=404, detail='Group not found.')
            if old_name == new_name:
                return {'ok': True, 'group': {'name': old_name}}
            existing = session.scalar(select(GroupORM.name).where(GroupORM.name == new_name))
            if existing is not None:
                raise HTTPException(status_code=409, detail='Group already exists.')

            group.name = new_name
            calendars = session.scalars(select(CalendarORM).where(CalendarORM.group_name == old_name)).all()
            for calendar in calendars:
                calendar.group_name = new_name
                _replace_calendar_group_links(session, calendar.id, [new_name])
            users_in_group = session.scalars(
                select(GroupUserLinkORM.user_id).where(GroupUserLinkORM.group_name == old_name)
            ).all()
            for user_id in users_in_group:
                _replace_user_group_links(session, user_id, [new_name])
            _refresh_user_group_names(session, [str(user_id) for user_id in users_in_group])

    return {'ok': True, 'group': {'name': new_name}}


@router.delete('/api/admin/groups/{group_name}')
def delete_group_for_admin(group_name: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    group_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    if group_name == 'General':
        raise HTTPException(status_code=400, detail='The General group cannot be deleted.')

    with DB_LOCK:
        with _db_session() as session:
            group = session.scalar(select(GroupORM).where(GroupORM.name == group_name))
            if group is None:
                raise HTTPException(status_code=404, detail='Group not found.')

            _ensure_group_names(session, ['General'])
            calendars = session.scalars(select(CalendarORM).where(CalendarORM.group_name == group_name)).all()
            moved_calendar_ids = [calendar.id for calendar in calendars]
            for calendar in calendars:
                calendar.group_name = 'General'
                _replace_calendar_group_links(session, calendar.id, ['General'])
            session.delete(group)
            users_in_group = session.scalars(
                select(GroupUserLinkORM.user_id).where(GroupUserLinkORM.group_name == group_name)
            ).all()
            for user_id in users_in_group:
                _replace_user_group_links(session, user_id, [])
            _refresh_user_group_names(session, [str(user_id) for user_id in users_in_group])

    return {'ok': True, 'groupName': group_name, 'movedTo': 'General', 'calendarIds': moved_calendar_ids}


@router.put('/api/admin/calendars/{calendar_id}/group')
def update_calendar_group_for_admin(
    calendar_id: str,
    payload: CalendarGroupUpdate,
    request: Request,
    token: str | None = None,
) -> dict[str, Any]:
    token = _prefer_admin_session_cookie(request, token)
    _require_admin_user(token)
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')
    group_name = _sanitize_text_input(payload.groupName, 'groupName', min_length=1, max_length=120)
    with DB_LOCK:
        with _db_session() as session:
            calendar = session.get(CalendarORM, calendar_id)
            if calendar is None:
                raise HTTPException(status_code=404, detail='Calendar not found.')
            group_exists = session.scalar(select(GroupORM.name).where(GroupORM.name == group_name))
            if group_exists is None:
                raise HTTPException(status_code=404, detail='Group not found.')
            calendar.group_name = group_name
            _replace_calendar_group_links(session, calendar.id, [group_name])

    return {'ok': True, 'calendarId': calendar_id, 'groupName': group_name}


@router.put('/api/admin/calendars/{calendar_id}')
def update_calendar_for_admin(
    calendar_id: str,
    payload: CalendarAdminUpdateRequest,
    request: Request,
    token: str | None = None,
) -> dict[str, Any]:
    token = _prefer_admin_session_cookie(request, token)
    _require_admin_user(token)
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')
    name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    group_name = _sanitize_text_input(payload.groupName, 'groupName', min_length=1, max_length=120)
    color = _sanitize_text_input(payload.color, 'color', min_length=4, max_length=40)
    blurb = _sanitize_text_input(payload.blurb, 'blurb', min_length=0, max_length=500)
    image_url = _sanitize_text_input(payload.imageUrl, 'imageUrl', min_length=0, max_length=5_000_000)

    with DB_LOCK:
        with _db_session() as session:
            calendar = session.get(CalendarORM, calendar_id)
            if calendar is None:
                raise HTTPException(status_code=404, detail='Calendar not found.')

            existing = session.scalar(
                select(CalendarORM.id)
                .where(CalendarORM.name == name)
                .where(CalendarORM.id != calendar_id)
            )
            if existing is not None:
                raise HTTPException(status_code=409, detail='Another calendar already uses that name.')

            _ensure_group_names(session, [group_name])
            calendar.name = name
            calendar.group_name = group_name
            _replace_calendar_group_links(session, calendar.id, [group_name])
            calendar.color = color
            calendar.blurb = blurb
            calendar.image_url = image_url

    _publish_calendar_change('calendar_changed', entity_id=calendar_id, calendar_ids=[calendar_id])
    return {
        'ok': True,
        'calendar': {
            'id': calendar_id,
            'name': name,
            'group': group_name,
            'color': color,
            'blurb': blurb,
            'imageUrl': image_url,
        },
    }


@router.post('/api/admin/calendars/{calendar_id}/image')
async def upload_calendar_image_for_admin(
    calendar_id: str,
    request: Request,
    file: UploadFile = File(...),
    token: str | None = None,
) -> dict[str, Any]:
    token = _prefer_admin_session_cookie(request, token)
    _require_admin_user(token)
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail='Please upload an image file.')

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail='Uploaded file was empty.')

    image_url, image_thumb_url = create_calendar_thumbnail_data_url(
        file_bytes,
        filename=file.filename,
        content_type=file.content_type,
    )

    with DB_LOCK:
        with _db_session() as session:
            calendar = session.get(CalendarORM, calendar_id)
            if calendar is None:
                raise HTTPException(status_code=404, detail='Calendar not found.')
            calendar.image_url = image_url
            calendar.image_thumb_url = image_thumb_url

    return {
        'ok': True,
        'calendarId': calendar_id,
        'imageUrl': image_url,
        'imageThumbUrl': image_thumb_url,
        'filename': file.filename or 'uploaded-image',
    }


@router.post('/api/admin/groups/{group_name}/resources')
def create_group_resource_for_admin(
    group_name: str, payload: GroupResourceCreateRequest, token: str | None = None
) -> dict[str, Any]:
    _require_admin_user(token)
    group_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    resource_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)

    with DB_LOCK:
        with _db_session() as session:
            group_exists = session.scalar(select(GroupORM.name).where(GroupORM.name == group_name))
            if group_exists is None:
                raise HTTPException(status_code=404, detail='Group not found.')

            existing_resource = session.scalar(
                select(CalendarORM).where(func.lower(CalendarORM.name) == resource_name.lower())
            )
            if existing_resource is not None:
                existing_resource.group_name = group_name
                _replace_calendar_group_links(session, existing_resource.id, [group_name])
                created = False
                calendar_id = existing_resource.id
            else:
                calendar_id = str(uuid4())
                session.add(CalendarORM(id=calendar_id, name=resource_name, group_name=group_name))
                _replace_calendar_group_links(session, calendar_id, [group_name])
                created = True

    return {
        'ok': True,
        'created': created,
        'calendarId': calendar_id,
        'name': resource_name,
        'groupName': group_name,
    }


@router.post('/api/admin/users')
def create_user_for_admin(payload: AdminUserCreateRequest, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    admin_user = _session_user_for_login_or_api_token(token)
    user_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    requested_email = _sanitize_email_input(payload.email, 'email') if payload.email else ''
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.calendarIds))

    with DB_LOCK:
        with _db_session() as session:
            valid_ids = set(session.scalars(select(CalendarORM.id)).all())
            invalid_ids = [cal_id for cal_id in calendar_ids if cal_id not in valid_ids]
            if invalid_ids:
                raise HTTPException(status_code=400, detail=f'Unknown resources: {", ".join(invalid_ids)}')
            group_names = _sanitize_group_names_input(session, payload.groupNames)

            if requested_email:
                email_exists = session.scalar(
                    select(UserORM.id).where(func.lower(UserORM.email) == requested_email)
                )
                if email_exists is not None:
                    raise HTTPException(status_code=409, detail='Email already exists.')
                user_email = requested_email
            else:
                user_email = _generate_unique_local_email(session)

            user_id = str(uuid4())
            login_token = _generate_unique_login_token(session)
            local_google_id = f'local:{uuid4()}'
            now_str = datetime.now().astimezone().isoformat()

            user = UserORM(
                id=user_id,
                google_id=local_google_id,
                email=user_email,
                name=user_name,
                role=DEFAULT_USER_ROLE,
                login_token=login_token,
                picture_url=None,
                group_name=None,
                created_at=now_str,
                last_login=now_str,
            )
            session.add(user)
            _replace_user_calendar_links(
                session,
                user.id,
                calendar_ids,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )
            _replace_user_group_links(
                session,
                user.id,
                group_names,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )
            _refresh_user_group_names(session, [user.id])

    return {
        'ok': True,
        'user': {
            'id': user_id,
            'email': user_email,
            'name': user_name,
            'role': DEFAULT_USER_ROLE,
            'calendarIds': calendar_ids,
            'groupNames': group_names,
        },
        'token': login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={login_token}',
    }


@router.put('/api/admin/users/{user_id}/resources')
def update_user_resources_for_admin(
    user_id: str, payload: LinkResourceUpdate, token: str | None = None
) -> dict[str, Any]:
    _require_admin_user(token)
    admin_user = _session_user_for_login_or_api_token(token)
    user_id = _sanitize_id_input(user_id, 'user_id')
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.calendarIds))
    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            valid_ids = set(session.scalars(select(CalendarORM.id)).all())
            invalid_ids = [cal_id for cal_id in calendar_ids if cal_id not in valid_ids]
            if invalid_ids:
                raise HTTPException(status_code=400, detail=f'Unknown resources: {", ".join(invalid_ids)}')
            group_names = _sanitize_group_names_input(session, payload.groupNames)
            now_str = datetime.now().astimezone().isoformat()
            _replace_user_calendar_links(
                session,
                user.id,
                calendar_ids,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )
            _replace_user_group_links(
                session,
                user.id,
                group_names,
                approved_by_user_id=admin_user['id'] if admin_user else None,
                approved_at=now_str,
                requested_at=now_str,
            )
            _refresh_user_group_names(session, [user.id])

    _publish_user_resources_updated(user_id)
    return {'ok': True, 'userId': user_id, 'calendarIds': calendar_ids, 'groupNames': group_names}


@router.post('/api/tokens/claim-url-token/{url_token}')
def claim_url_token_resources_for_cookie_user(
    url_token: str,
    request: Request,
    payload: CalendarAccessClaimRequest | None = None,
) -> dict[str, Any]:
    url_token = _sanitize_token_input(url_token, 'url_token')
    session_token = request.cookies.get('session_token')
    if not session_token:
        raise HTTPException(status_code=401, detail='Login required.')

    claim_calendar_ids = sorted(
        _sanitize_calendar_ids_input(payload.calendarIds) if payload else []
    )

    with DB_LOCK:
        with _db_session() as session:
            source_user_id = _resolve_user_id_from_login_or_api_token(session, url_token)
            if not source_user_id:
                raise HTTPException(status_code=404, detail='Link not found.')

            session_user = _session_user_for_login_or_api_token(session_token)
            if session_user is None:
                raise HTTPException(status_code=401, detail='Login required.')

            source_calendar_ids = sorted(_get_user_allowed_calendars(session, source_user_id) or set())
            if claim_calendar_ids:
                invalid_ids = [
                    cal_id for cal_id in claim_calendar_ids
                    if cal_id not in source_calendar_ids
                ]
                if invalid_ids:
                    raise HTTPException(status_code=400, detail=f'Unknown resources: {", ".join(invalid_ids)}')
            else:
                claim_calendar_ids = source_calendar_ids

            current_calendar_ids = sorted(_get_user_allowed_calendars(session, session_user['id']) or set())
            merged_calendar_ids = sorted(set(current_calendar_ids).union(claim_calendar_ids))
            target_user = session.get(UserORM, session_user['id'])
            if target_user:
                now_str = datetime.now().astimezone().isoformat()
                _replace_user_calendar_links(
                    session,
                    target_user.id,
                    merged_calendar_ids,
                    approved_by_user_id=target_user.id,
                    approved_at=now_str,
                    requested_at=now_str,
                )

    _publish_user_resources_updated(session_user['id'])
    return {'ok': True, 'claimed': True, 'userId': session_user['id'], 'calendarIds': claim_calendar_ids}


@router.post('/api/logout')
def logout_user(response: Response) -> dict[str, Any]:
    """Clear auth cookies for the current browser session."""
    response.delete_cookie(key='session_token', path='/')
    response.delete_cookie(key='user_id', path='/')
    return {'ok': True}
