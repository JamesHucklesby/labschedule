import json
import mimetypes
import secrets
import base64
import colorsys
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from auth import (
    _get_user_allowed_calendars,
    _require_admin_user,
    _require_authenticated_user,
    _resolve_user_id_from_login_or_api_token,
    _session_user_for_login_or_api_token,
)
from config import (
    ADMIN_USER_EMAILS,
    APP_BASE_URL,
    DEFAULT_USER_ROLE,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_STARTTLS,
)
from database import (
    DB_LOCK,
    _db_session,
    _ensure_group_names,
    _generate_unique_local_email,
    _generate_unique_login_token,
    _get_user_calendar_ids,
    _get_user_group_names_from_links,
    _merge_user_access_from_source,
    _record_user_saved_share_link,
    _replace_user_calendar_links,
    _replace_user_group_links,
    _replace_calendar_group_links,
    _upsert_user_calendar_link,
    _upsert_user_group_link,
)
from models import ENGINE, CalendarGroupLinkORM, CalendarORM, EventORM, GroupORM, GroupUserLinkORM, UserCalendarLinkORM, UserORM, UserPasskeyORM, UserSavedShareLinkORM
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


def _send_group_access_request_admin_notification(
    *,
    recipients: list[str],
    requester_name: str,
    requester_email: str,
    group_name: str,
    requested_at: str,
) -> None:
    normalized_recipients = sorted({str(value or '').strip().lower() for value in recipients if str(value or '').strip()})
    if not normalized_recipients:
        return
    if not SMTP_FROM_EMAIL or not SMTP_USERNAME or not SMTP_PASSWORD:
        print('[access-request-email] SMTP not fully configured; skipping admin notification.', flush=True)
        return

    requester_label = requester_name.strip() or requester_email.strip() or 'Unknown user'
    message = EmailMessage()
    message['Subject'] = f'Group access request: {group_name}'
    message['From'] = f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>' if SMTP_FROM_NAME else SMTP_FROM_EMAIL
    message['To'] = ', '.join(normalized_recipients)
    message.set_content(
        f'A new group access request was submitted.\n\n'
        f'Requester: {requester_label}\n'
        f'Requester email: {requester_email or "(none)"}\n'
        f'Group: {group_name}\n'
        f'Requested at: {requested_at}\n\n'
        f'Review requests in Admin: {APP_BASE_URL}/?admin=1\n'
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if SMTP_USE_STARTTLS:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)
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
    if not calendar_ids:
        return []
    linked_group_names = session.scalars(
        select(CalendarGroupLinkORM.group_name)
        .where(CalendarGroupLinkORM.calendar_id.in_(calendar_ids))
        .distinct()
        .order_by(CalendarGroupLinkORM.group_name.asc())
    ).all()
    names = sorted({str(value).strip() for value in linked_group_names if str(value or '').strip()})
    return names


def _approved_user_ids_for_group(session, group_name: str) -> list[str]:
    user_ids = session.scalars(
        select(GroupUserLinkORM.user_id)
        .where(GroupUserLinkORM.group_name == group_name)
        .where(GroupUserLinkORM.status == 'approved')
        .distinct()
        .order_by(GroupUserLinkORM.user_id.asc())
    ).all()
    return [str(user_id) for user_id in user_ids if user_id]


def _publish_user_resource_updates(user_ids: list[str]) -> None:
    seen: set[str] = set()
    for user_id in user_ids:
        normalized = str(user_id or '').strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        _publish_user_resources_updated(normalized)


def _user_calendar_link(session, user_id: str, calendar_id: str) -> UserCalendarLinkORM | None:
    return session.get(UserCalendarLinkORM, (user_id, calendar_id))


def _user_group_link(session, user_id: str, group_name: str):
    return session.get(GroupUserLinkORM, (group_name, user_id))


def _parse_hex_color(value: str | None) -> tuple[int, int, int] | None:
    raw = str(value or '').strip()
    if not raw.startswith('#'):
        return None
    hex_value = raw[1:]
    if len(hex_value) == 3:
        hex_value = ''.join(ch * 2 for ch in hex_value)
    if len(hex_value) != 6:
        return None
    try:
        return (
            int(hex_value[0:2], 16),
            int(hex_value[2:4], 16),
            int(hex_value[4:6], 16),
        )
    except ValueError:
        return None


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    return f'#{color[0]:02x}{color[1]:02x}{color[2]:02x}'


def _rgb_distance_sq(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (
        (left[0] - right[0]) ** 2
        + (left[1] - right[1]) ** 2
        + (left[2] - right[2]) ** 2
    )


def _pleasant_candidate_colors() -> list[tuple[int, int, int]]:
    candidates: list[tuple[int, int, int]] = []
    # Golden-angle hue sweep keeps colors distributed around the wheel.
    for index in range(36):
        hue = (index * 0.61803398875) % 1.0
        lightness = 0.52 if index % 2 == 0 else 0.58
        saturation = 0.68 if index % 3 else 0.74
        red_f, green_f, blue_f = colorsys.hls_to_rgb(hue, lightness, saturation)
        candidates.append((
            int(round(red_f * 255)),
            int(round(green_f * 255)),
            int(round(blue_f * 255)),
        ))
    return candidates


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

    linked_calendar_ids = session.scalars(
        select(CalendarGroupLinkORM.calendar_id)
        .where(CalendarGroupLinkORM.group_name == target_id)
        .order_by(CalendarGroupLinkORM.calendar_id.asc())
    ).all()
    return sorted({str(calendar_id) for calendar_id in linked_calendar_ids if calendar_id})


def _user_has_group_calendar_access(session, user_id: str, calendar_id: str) -> bool:
    approved_group_names = [
        str(group_name).strip()
        for group_name in session.scalars(
            select(GroupUserLinkORM.group_name)
            .where(GroupUserLinkORM.user_id == user_id)
            .where(GroupUserLinkORM.status == 'approved')
            .order_by(GroupUserLinkORM.group_name.asc())
        ).all()
        if str(group_name or '').strip()
    ]
    if not approved_group_names:
        return False

    linked_calendar_id = session.scalar(
        select(CalendarGroupLinkORM.calendar_id)
        .where(CalendarGroupLinkORM.calendar_id == calendar_id)
        .where(CalendarGroupLinkORM.group_name.in_(approved_group_names))
        .limit(1)
    )
    if linked_calendar_id is not None:
        return True
    return False


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
    reviewer = session.get(UserORM, reviewed_by_user_id) if reviewed_by_user_id else None
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

    approval_source = ''
    if str(status or '').strip().lower() == 'approved':
        # Auto-approval flows stamp requested_at and approved_at at the same time
        # (link creation, add-to-account claims, OAuth conversion merges).
        if reviewed_at and requested_at and reviewed_at == requested_at:
            approval_source = 'auto_link_addition'
        elif reviewer and str(reviewer.role or '').strip().lower() == 'admin':
            approval_source = 'manual'
        else:
            approval_source = 'auto_link_addition'

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
        'reviewedByName': reviewer.name if reviewer else '',
        'reviewedByEmail': reviewer.email if reviewer else '',
        'approvalSource': approval_source,
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
    requests.sort(key=lambda request: 0 if str(request.get('status') or '').strip().lower() != 'approved' else 1)
    return requests


def _list_admin_groups(session) -> list[dict[str, Any]]:
    group_rows = session.scalars(select(GroupORM).order_by(GroupORM.name.asc())).all()
    calendars = session.scalars(
        select(CalendarORM).order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
    ).all()
    calendar_group_links = session.scalars(
        select(CalendarGroupLinkORM).order_by(CalendarGroupLinkORM.group_name.asc(), CalendarGroupLinkORM.calendar_id.asc())
    ).all()
    calendar_by_id = {calendar.id: calendar for calendar in calendars}
    calendars_by_group: dict[str, list[dict[str, Any]]] = {}
    seen_per_group: dict[str, set[str]] = {}
    for link in calendar_group_links:
        calendar = calendar_by_id.get(link.calendar_id)
        if calendar is None:
            continue
        group_name = str(link.group_name or '').strip()
        if not group_name:
            continue
        group_seen = seen_per_group.setdefault(group_name, set())
        if calendar.id in group_seen:
            continue
        group_seen.add(calendar.id)
        calendars_by_group.setdefault(group_name, []).append({
            'id': calendar.id,
            'name': calendar.name,
            'group': group_name,
            'color': calendar.color,
            'sortOrder': int(calendar.sort_order or 0),
        })

    for group_calendars in calendars_by_group.values():
        group_calendars.sort(key=lambda calendar: (
            int(calendar.get('sortOrder') or 0),
            str(calendar.get('name') or '').lower(),
            str(calendar.get('id') or ''),
        ))

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
            select(CalendarORM).order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all()
        calendar_group_links = session.scalars(
            select(CalendarGroupLinkORM).order_by(CalendarGroupLinkORM.group_name.asc(), CalendarGroupLinkORM.calendar_id.asc())
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
    grouped_calendar_seen: dict[str, set[str]] = {}
    group_names: list[str] = []
    seen_group_names: set[str] = set()
    for group in group_rows:
        if group.name not in seen_group_names:
            seen_group_names.add(group.name)
            group_names.append(group.name)

    group_names_by_calendar_id: dict[str, set[str]] = {}
    for link in calendar_group_links:
        group_name = str(link.group_name or '').strip()
        calendar_id = str(link.calendar_id or '').strip()
        if not group_name or not calendar_id:
            continue
        group_names_by_calendar_id.setdefault(calendar_id, set()).add(group_name)

    for calendar in calendars:
        calendar_group_names = set(group_names_by_calendar_id.get(calendar.id, set()))
        fallback_group_name = str(calendar.group_name or 'General').strip() or 'General'
        if not calendar_group_names:
            calendar_group_names.add(fallback_group_name)
        for group_name in sorted(calendar_group_names):
            if group_name not in seen_group_names:
                seen_group_names.add(group_name)
                group_names.append(group_name)
            group_bucket = grouped_calendars.setdefault(group_name, [])
            group_seen = grouped_calendar_seen.setdefault(group_name, set())
            if calendar.id in group_seen:
                continue
            group_seen.add(calendar.id)
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
    admin_notification_payload: dict[str, Any] | None = None

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

            if target_type == 'group':
                admin_emails = {
                    str(value or '').strip().lower()
                    for value in session.scalars(
                        select(UserORM.email)
                        .where(func.lower(UserORM.role) == 'admin')
                        .where(UserORM.email.isnot(None))
                        .order_by(UserORM.email.asc())
                    ).all()
                    if str(value or '').strip()
                }
                admin_emails.update({value.strip().lower() for value in ADMIN_USER_EMAILS if value.strip()})
                admin_notification_payload = {
                    'recipients': sorted(admin_emails),
                    'requesterName': str(user.name or '').strip(),
                    'requesterEmail': str(user.email or '').strip(),
                    'groupName': target_id,
                    'requestedAt': requested_at,
                }

    if admin_notification_payload:
        try:
            _send_group_access_request_admin_notification(
                recipients=admin_notification_payload.get('recipients') or [],
                requester_name=str(admin_notification_payload.get('requesterName') or ''),
                requester_email=str(admin_notification_payload.get('requesterEmail') or ''),
                group_name=str(admin_notification_payload.get('groupName') or ''),
                requested_at=str(admin_notification_payload.get('requestedAt') or ''),
            )
        except Exception as exc:
            print(f'[access-request-email] Failed to notify admins: {exc}', flush=True)

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
                restore_via_group = next_status == 'approved' and _user_has_group_calendar_access(session, session_user['id'], target_id)
                if restore_via_group:
                    # Remove the hide override so group-derived access becomes visible again.
                    session.delete(link_row)
                else:
                    _upsert_user_calendar_link(
                        session,
                        session_user['id'],
                        target_id,
                        status=next_status,
                        approved_by_user_id=session_user['id'] if next_status == 'approved' else None,
                        approved_at=now_str if next_status == 'approved' else None,
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
            current_allowed_calendar_ids = set(_get_user_allowed_calendars(session, user.id) or set())
            current_status = str(existing_link.status or '').strip().lower() if existing_link else ''

            if not current_status and not all(calendar_id in current_allowed_calendar_ids for calendar_id in target_calendar_ids):
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
                restore_via_group = (
                    current_status == 'hidden'
                    and next_status == 'approved'
                    and existing_link is not None
                    and _user_has_group_calendar_access(session, user.id, target_id)
                )
                if restore_via_group:
                    # For group-derived access, restore by removing the hide override only.
                    session.delete(existing_link)
                else:
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


@router.post('/api/admin/access-requests/{request_id}/decline')
def decline_access_request_for_admin(request_id: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
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

            session.delete(link_row)

    _publish_user_resources_updated(target_user_id)
    return {'ok': True, 'declined': True, 'requestId': request_id, 'userId': target_user_id}


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
            select(CalendarORM).order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color, 'sortOrder': int(c.sort_order or 0)} for c in calendars]

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
    link_token = requested_token
    calendar_ids = sorted(_sanitize_calendar_ids_input(payload.calendarIds))

    with DB_LOCK:
        with _db_session() as session:
            if not link_token:
                link_token = _generate_unique_login_token(session)
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
            select(CalendarORM).order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color, 'sortOrder': int(c.sort_order or 0)} for c in calendars]

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
                'serviceAccount': bool(u.service_account),
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


@router.get('/api/admin/postgres-performance')
def list_postgres_performance_for_admin(token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)

    def _interval_to_ms(value: Any) -> int:
        if value is None:
            return 0
        total_seconds = getattr(value, 'total_seconds', None)
        if callable(total_seconds):
            return int(total_seconds() * 1000)
        try:
            return int(float(value) * 1000)
        except Exception:
            return 0

    def _to_int(value: Any) -> int:
        if value is None:
            return 0
        try:
            return int(value)
        except Exception:
            return 0

    def _format_timestamp(value: Any) -> str:
        if not value:
            return ''
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    with _db_session() as session:
        db_stats_row = session.execute(
            text(
                '''
                SELECT
                    numbackends,
                    xact_commit,
                    xact_rollback,
                    blks_read,
                    blks_hit,
                    tup_returned,
                    tup_fetched,
                    tup_inserted,
                    tup_updated,
                    tup_deleted,
                    deadlocks,
                    temp_files,
                    temp_bytes
                FROM pg_stat_database
                WHERE datname = current_database()
                '''
            )
        ).mappings().first()
        vacuum_stats = session.execute(
            text(
                '''
                SELECT
                    COUNT(*) AS table_count,
                    COALESCE(SUM(n_live_tup), 0) AS live_tuples,
                    COALESCE(SUM(n_dead_tup), 0) AS dead_tuples,
                    COALESCE(SUM(vacuum_count), 0) AS vacuum_count,
                    COALESCE(SUM(autovacuum_count), 0) AS autovacuum_count,
                    COALESCE(SUM(analyze_count), 0) AS analyze_count,
                    COALESCE(SUM(autoanalyze_count), 0) AS autoanalyze_count,
                    MAX(last_vacuum) AS last_vacuum,
                    MAX(last_autovacuum) AS last_autovacuum,
                    MAX(last_analyze) AS last_analyze,
                    MAX(last_autoanalyze) AS last_autoanalyze
                FROM pg_stat_user_tables
                '''
            )
        ).mappings().first() or {}

        table_stats_rows = session.execute(
            text(
                '''
                SELECT
                    schemaname,
                    relname,
                    n_live_tup,
                    n_dead_tup,
                    vacuum_count,
                    autovacuum_count,
                    analyze_count,
                    autoanalyze_count,
                    last_vacuum,
                    last_autovacuum,
                    last_analyze,
                    last_autoanalyze
                FROM pg_stat_user_tables
                ORDER BY n_dead_tup DESC, n_live_tup DESC, schemaname ASC, relname ASC
                LIMIT 25
                '''
            )
        ).mappings().all()

        active_autovacuum_workers = _to_int(
            session.scalar(
                text(
                    '''
                    SELECT COUNT(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND backend_type = 'autovacuum worker'
                    '''
                )
            )
        )

        activity_rows = session.execute(
            text(
                '''
                SELECT
                    pid,
                    usename,
                    application_name,
                    state,
                    wait_event_type,
                    wait_event,
                    backend_type,
                    now() - query_start AS query_age,
                    now() - xact_start AS xact_age,
                    LEFT(REGEXP_REPLACE(COALESCE(query, ''), '\\s+', ' ', 'g'), 320) AS query_snippet
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                ORDER BY query_start DESC NULLS LAST
                LIMIT 30
                '''
            )
        ).mappings().all()

        top_statements: list[dict[str, Any]] = []
        top_statements_error = ''
        try:
            statement_rows = session.execute(
                text(
                    '''
                    SELECT
                        REGEXP_REPLACE(COALESCE(query, ''), '\\s+', ' ', 'g') AS query_text,
                        calls,
                        total_exec_time,
                        mean_exec_time,
                        rows
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC
                    LIMIT 50
                    '''
                )
            ).mappings().all()
            for row in statement_rows:
                top_statements.append({
                    'query': str(row.get('query_text') or '').strip(),
                    'calls': _to_int(row.get('calls')),
                    'totalExecMs': float(row.get('total_exec_time') or 0.0),
                    'meanExecMs': float(row.get('mean_exec_time') or 0.0),
                    'rows': _to_int(row.get('rows')),
                })
        except SQLAlchemyError:
            top_statements_error = 'pg_stat_statements not available on this server.'

    active_queries: list[dict[str, Any]] = []
    active_sessions = 0
    blocked_sessions = 0
    idle_in_transaction_sessions = 0
    max_transaction_age_ms = 0

    for row in activity_rows:
        state = str(row.get('state') or '').strip().lower()
        wait_event_type = str(row.get('wait_event_type') or '').strip()
        query_duration_ms = _interval_to_ms(row.get('query_age'))
        transaction_age_ms = _interval_to_ms(row.get('xact_age'))
        if state == 'active':
            active_sessions += 1
        if state == 'idle in transaction':
            idle_in_transaction_sessions += 1
        if wait_event_type.lower() == 'lock':
            blocked_sessions += 1
        if transaction_age_ms > max_transaction_age_ms:
            max_transaction_age_ms = transaction_age_ms

        query_text = str(row.get('query_snippet') or '').strip()
        if not query_text or query_text.upper() in {'', '<IDLE>'}:
            continue

        active_queries.append({
            'pid': _to_int(row.get('pid')),
            'user': str(row.get('usename') or '').strip(),
            'application': str(row.get('application_name') or '').strip(),
            'state': state or 'unknown',
            'waitEventType': wait_event_type,
            'waitEvent': str(row.get('wait_event') or '').strip(),
            'backendType': str(row.get('backend_type') or '').strip(),
            'queryDurationMs': query_duration_ms,
            'transactionAgeMs': transaction_age_ms,
            'query': query_text,
        })

    blks_read = _to_int((db_stats_row or {}).get('blks_read'))
    blks_hit = _to_int((db_stats_row or {}).get('blks_hit'))
    cache_hit_ratio = 0.0
    if (blks_read + blks_hit) > 0:
        cache_hit_ratio = (blks_hit / (blks_read + blks_hit)) * 100.0

    table_stats = []
    for row in table_stats_rows:
        table_stats.append({
            'schemaName': str(row.get('schemaname') or '').strip(),
            'tableName': str(row.get('relname') or '').strip(),
            'liveTuples': _to_int(row.get('n_live_tup')),
            'deadTuples': _to_int(row.get('n_dead_tup')),
            'vacuumCount': _to_int(row.get('vacuum_count')),
            'autovacuumCount': _to_int(row.get('autovacuum_count')),
            'analyzeCount': _to_int(row.get('analyze_count')),
            'autoanalyzeCount': _to_int(row.get('autoanalyze_count')),
            'lastVacuum': _format_timestamp(row.get('last_vacuum')),
            'lastAutovacuum': _format_timestamp(row.get('last_autovacuum')),
            'lastAnalyze': _format_timestamp(row.get('last_analyze')),
            'lastAutoanalyze': _format_timestamp(row.get('last_autoanalyze')),
        })

    return {
        'capturedAt': datetime.now().astimezone().isoformat(),
        'summary': {
            'connections': _to_int((db_stats_row or {}).get('numbackends')),
            'autovacuumWorkers': active_autovacuum_workers,
            'tableCount': _to_int(vacuum_stats.get('table_count')),
            'liveTuples': _to_int(vacuum_stats.get('live_tuples')),
            'deadTuples': _to_int(vacuum_stats.get('dead_tuples')),
            'vacuumCount': _to_int(vacuum_stats.get('vacuum_count')),
            'autovacuumCount': _to_int(vacuum_stats.get('autovacuum_count')),
            'analyzeCount': _to_int(vacuum_stats.get('analyze_count')),
            'autoanalyzeCount': _to_int(vacuum_stats.get('autoanalyze_count')),
            'lastVacuum': vacuum_stats.get('last_vacuum').isoformat() if vacuum_stats.get('last_vacuum') else '',
            'lastAutovacuum': vacuum_stats.get('last_autovacuum').isoformat() if vacuum_stats.get('last_autovacuum') else '',
            'lastAnalyze': vacuum_stats.get('last_analyze').isoformat() if vacuum_stats.get('last_analyze') else '',
            'lastAutoanalyze': vacuum_stats.get('last_autoanalyze').isoformat() if vacuum_stats.get('last_autoanalyze') else '',
            'activeSessions': active_sessions,
            'blockedSessions': blocked_sessions,
            'idleInTransaction': idle_in_transaction_sessions,
            'maxTransactionAgeMs': max_transaction_age_ms,
            'cacheHitRatioPct': round(cache_hit_ratio, 2),
            'xactCommit': _to_int((db_stats_row or {}).get('xact_commit')),
            'xactRollback': _to_int((db_stats_row or {}).get('xact_rollback')),
            'deadlocks': _to_int((db_stats_row or {}).get('deadlocks')),
            'tempFiles': _to_int((db_stats_row or {}).get('temp_files')),
            'tempBytes': _to_int((db_stats_row or {}).get('temp_bytes')),
            'tupInserted': _to_int((db_stats_row or {}).get('tup_inserted')),
            'tupUpdated': _to_int((db_stats_row or {}).get('tup_updated')),
            'tupDeleted': _to_int((db_stats_row or {}).get('tup_deleted')),
        },
        'tableStats': table_stats,
        'activeQueries': active_queries,
        'topStatements': top_statements,
        'topStatementsError': top_statements_error,
    }


@router.post('/api/admin/postgres-explain')
def run_postgres_explain_for_admin(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    query_text = str(payload.get('query') or '').strip()
    if not query_text:
        raise HTTPException(status_code=400, detail='query is required.')
    if len(query_text) > 8192:
        raise HTTPException(status_code=400, detail='Query too long (max 8192 characters).')
    normalized_start = query_text.upper().lstrip()
    allowed_prefixes = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH', 'TABLE', 'VALUES')
    if not any(normalized_start.startswith(kw) for kw in allowed_prefixes):
        raise HTTPException(status_code=400, detail='Only SELECT/DML statements can be explained.')
    try:
        plan, strategy = _explain_plan(query_text)
    except ValueError as exc:
        return {'ok': False, 'error': str(exc)}
    return {'ok': True, 'plan': plan, 'strategy': strategy}




def _explain_plan(query_text: str) -> tuple[str, str]:
    """Return (plan_text, strategy_label).

    Strategy order:
    1. EXPLAIN (GENERIC_PLAN) — PG 16+; works with $N parameters natively.
    2. EXPLAIN plain on the query after replacing every $N placeholder with NULL::text
       so the planner sees a syntactically valid literal.
    3. Hard error with the last exception message.
    """
    import re as _re

    def _run(session: Any, sql: str) -> list[str]:
        session.execute(text('SAVEPOINT _explain_sp'))
        try:
            rows = session.execute(text(sql)).fetchall()
            session.execute(text('RELEASE SAVEPOINT _explain_sp'))
            return [str(r[0]) for r in rows]
        except SQLAlchemyError:
            session.execute(text('ROLLBACK TO SAVEPOINT _explain_sp'))
            raise

    def _null_substitute(q: str) -> str:
        """Replace every $N parameter reference with NULL::text."""
        return _re.sub(r'\$\d+', 'NULL::text', q)

    with _db_session() as session:
        # Strategy 1 – GENERIC_PLAN (PostgreSQL 16+)
        try:
            lines = _run(session, f'EXPLAIN (FORMAT TEXT, GENERIC_PLAN) {query_text}')
            return '\n'.join(lines), 'GENERIC_PLAN'
        except SQLAlchemyError:
            pass

        # Strategy 2 – substitute $N → NULL::text and use plain EXPLAIN
        null_query = _null_substitute(query_text)
        try:
            lines = _run(session, f'EXPLAIN (FORMAT TEXT) {null_query}')
            note = '-- Note: $N parameters replaced with NULL::text for planning\n'
            return note + '\n'.join(lines), 'NULL_SUBSTITUTION'
        except SQLAlchemyError as exc2:
            orig = getattr(exc2, 'orig', None)
            raise ValueError(str(orig) if orig else str(exc2)) from exc2


@router.post('/api/admin/postgres-vacuum')
def run_postgres_vacuum_for_admin(token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    with DB_LOCK:
        with ENGINE.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            connection.execute(text('VACUUM (ANALYZE)'))
    return {'ok': True, 'message': 'VACUUM (ANALYZE) completed.'}


@router.post('/api/admin/postgres-vacuum/table')
def run_postgres_table_vacuum_for_admin(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    schema_name = _sanitize_text_input(str(payload.get('schemaName') or ''), 'schemaName', min_length=1, max_length=128)
    table_name = _sanitize_text_input(str(payload.get('tableName') or ''), 'tableName', min_length=1, max_length=128)

    with DB_LOCK:
        with _db_session() as session:
            table_exists = session.scalar(
                text(
                    '''
                    SELECT 1
                    FROM pg_stat_user_tables
                    WHERE schemaname = :schema_name
                      AND relname = :table_name
                    LIMIT 1
                    '''
                ),
                {'schema_name': schema_name, 'table_name': table_name},
            )
            if table_exists is None:
                raise HTTPException(status_code=404, detail='Table not found in database statistics.')

        escaped_schema_name = schema_name.replace('"', '""')
        escaped_table_name = table_name.replace('"', '""')
        qualified_name = f'"{escaped_schema_name}"."{escaped_table_name}"'
        with ENGINE.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            connection.execute(text(f'VACUUM (ANALYZE) {qualified_name}'))

    return {'ok': True, 'message': f'VACUUM (ANALYZE) completed for {schema_name}.{table_name}.'}


@router.get('/api/admin/groups')
def list_groups_for_admin(token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    with _db_session() as session:
        groups = _list_admin_groups(session)
        calendars = session.scalars(
            select(CalendarORM).order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
        ).all()
        resources = [{'id': c.id, 'name': c.name, 'group': c.group_name, 'color': c.color, 'sortOrder': int(c.sort_order or 0)} for c in calendars]

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


@router.post('/api/admin/calendars/suggest-color')
def suggest_calendar_color_for_group(
    payload: dict[str, Any],
    request: Request,
    token: str | None = None,
) -> dict[str, Any]:
    token = _prefer_admin_session_cookie(request, token)
    _require_admin_user(token)
    group_name = _sanitize_text_input(str(payload.get('groupName') or ''), 'groupName', min_length=1, max_length=120)
    exclude_calendar_id_raw = str(payload.get('excludeCalendarId') or '').strip()
    exclude_calendar_id = _sanitize_id_input(exclude_calendar_id_raw, 'excludeCalendarId') if exclude_calendar_id_raw else ''
    avoid_color = _parse_hex_color(str(payload.get('avoidColor') or '').strip())

    with _db_session() as session:
        linked_calendar_ids = session.scalars(
            select(CalendarGroupLinkORM.calendar_id)
            .where(CalendarGroupLinkORM.group_name == group_name)
            .order_by(CalendarGroupLinkORM.calendar_id.asc())
        ).all()
        fallback_calendar_ids = session.scalars(
            select(CalendarORM.id)
            .where(CalendarORM.group_name == group_name)
            .order_by(CalendarORM.id.asc())
        ).all()
        calendar_ids = {str(calendar_id) for calendar_id in [*linked_calendar_ids, *fallback_calendar_ids] if calendar_id}
        if exclude_calendar_id:
            calendar_ids.discard(exclude_calendar_id)

        existing_colors_raw = session.scalars(
            select(CalendarORM.color)
            .where(CalendarORM.id.in_(sorted(calendar_ids)))
            .order_by(CalendarORM.id.asc())
        ).all() if calendar_ids else []

        all_color_rows = session.execute(
            select(CalendarORM.id, CalendarORM.color)
            .where(CalendarORM.color.isnot(None))
            .order_by(CalendarORM.id.asc())
        ).all()

    shared_group_colors = [parsed for parsed in (_parse_hex_color(value) for value in existing_colors_raw) if parsed is not None]
    all_other_colors: list[tuple[int, int, int]] = []
    for calendar_id_value, raw_color in all_color_rows:
        calendar_id_text = str(calendar_id_value or '').strip()
        if exclude_calendar_id and calendar_id_text == exclude_calendar_id:
            continue
        if calendar_id_text in calendar_ids:
            continue
        parsed_color = _parse_hex_color(raw_color)
        if parsed_color is not None:
            all_other_colors.append(parsed_color)

    candidates = _pleasant_candidate_colors()
    for _ in range(96):
        hue = secrets.randbelow(360) / 360.0
        lightness = (46 + secrets.randbelow(15)) / 100.0
        saturation = (62 + secrets.randbelow(23)) / 100.0
        red_f, green_f, blue_f = colorsys.hls_to_rgb(hue, lightness, saturation)
        candidates.append((
            int(round(red_f * 255)),
            int(round(green_f * 255)),
            int(round(blue_f * 255)),
        ))
    candidates = list(dict.fromkeys(candidates))

    if not shared_group_colors and not all_other_colors and avoid_color is None:
        return {'ok': True, 'color': _rgb_to_hex(candidates[secrets.randbelow(len(candidates))])}

    scored: list[tuple[float, tuple[int, int, int]]] = []
    for candidate in candidates:
        shared_min = min((_rgb_distance_sq(candidate, target) for target in shared_group_colors), default=0)
        global_min = min((_rgb_distance_sq(candidate, target) for target in all_other_colors), default=0)
        avoid_dist = _rgb_distance_sq(candidate, avoid_color) if avoid_color is not None else 0
        # Keep the selected/shared group as the strongest distinctness signal.
        candidate_score = (shared_min * 1.0) + (global_min * 0.35) + (avoid_dist * 0.45)
        scored.append((candidate_score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    top_count = max(8, min(18, len(scored)))
    chosen_score, chosen_candidate = scored[secrets.randbelow(top_count)]
    # Avoid near-identical suggestions when possible.
    if avoid_color is not None and _rgb_distance_sq(chosen_candidate, avoid_color) < 2000 and len(scored) > top_count:
        chosen_score, chosen_candidate = scored[top_count]

    return {'ok': True, 'color': _rgb_to_hex(chosen_candidate), 'score': chosen_score}


@router.put('/api/admin/calendars/order')
def update_calendar_order_for_admin(payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    raw_calendar_ids = payload.get('calendarIds')
    if not isinstance(raw_calendar_ids, list):
        raise HTTPException(status_code=400, detail='calendarIds must be an array of calendar IDs.')

    provided_calendar_ids = _sanitize_calendar_ids_input(raw_calendar_ids)
    if not provided_calendar_ids:
        raise HTTPException(status_code=400, detail='calendarIds cannot be empty.')

    with DB_LOCK:
        with _db_session() as session:
            calendars = session.scalars(
                select(CalendarORM)
                .order_by(CalendarORM.sort_order.asc(), CalendarORM.group_name.asc(), CalendarORM.name.asc(), CalendarORM.id.asc())
            ).all()
            calendar_by_id = {calendar.id: calendar for calendar in calendars}
            all_calendar_ids = [calendar.id for calendar in calendars]

            invalid_ids = [calendar_id for calendar_id in provided_calendar_ids if calendar_id not in calendar_by_id]
            if invalid_ids:
                raise HTTPException(status_code=400, detail=f'Unknown calendars: {", ".join(invalid_ids)}')

            ordered_calendar_ids = [calendar_id for calendar_id in provided_calendar_ids]
            ordered_calendar_ids.extend([calendar_id for calendar_id in all_calendar_ids if calendar_id not in ordered_calendar_ids])

            for index, calendar_id in enumerate(ordered_calendar_ids, start=1):
                calendar_by_id[calendar_id].sort_order = index

    _publish_calendar_change('calendar_changed', entity_id='calendar-order', calendar_ids=ordered_calendar_ids)
    return {'ok': True, 'calendarIds': ordered_calendar_ids}


@router.put('/api/admin/groups/{group_name}')
def rename_group_for_admin(group_name: str, payload: GroupCreateRequest, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    old_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    new_name = _sanitize_text_input(payload.name, 'name', min_length=1, max_length=120)
    if old_name == 'General':
        raise HTTPException(status_code=400, detail='The General group cannot be renamed.')
    if new_name == 'General':
        raise HTTPException(status_code=400, detail='Use the existing General group instead of renaming to it.')

    affected_user_ids: list[str] = []
    moved_calendar_ids: list[str] = []

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

            affected_user_ids.extend(_approved_user_ids_for_group(session, old_name))

            session.add(GroupORM(name=new_name))

            calendars = session.scalars(select(CalendarORM).where(CalendarORM.group_name == old_name)).all()
            moved_calendar_ids = [calendar.id for calendar in calendars]
            for calendar in calendars:
                calendar.group_name = new_name

            calendar_links = session.scalars(
                select(CalendarGroupLinkORM).where(CalendarGroupLinkORM.group_name == old_name)
            ).all()
            for link in calendar_links:
                existing_new_link = session.get(CalendarGroupLinkORM, (link.calendar_id, new_name))
                if existing_new_link is not None:
                    session.delete(link)
                else:
                    link.group_name = new_name
                moved_calendar_ids.append(str(link.calendar_id))

            user_links = session.scalars(
                select(GroupUserLinkORM).where(GroupUserLinkORM.group_name == old_name)
            ).all()
            for link in user_links:
                existing_new_link = session.get(GroupUserLinkORM, (new_name, link.user_id))
                if existing_new_link is not None:
                    existing_status = str(existing_new_link.status or '').strip().lower()
                    old_status = str(link.status or '').strip().lower()
                    if existing_status != 'approved' and old_status == 'approved':
                        existing_new_link.status = 'approved'
                        existing_new_link.requested_at = link.requested_at
                        existing_new_link.approved_by_user_id = link.approved_by_user_id
                        existing_new_link.approved_at = link.approved_at
                    session.delete(link)
                else:
                    link.group_name = new_name

            session.delete(group)
            affected_user_ids.extend(_approved_user_ids_for_group(session, new_name))

    moved_calendar_ids = sorted({calendar_id for calendar_id in moved_calendar_ids if calendar_id})
    if moved_calendar_ids:
        _publish_calendar_change('calendar_changed', entity_id=old_name, calendar_ids=moved_calendar_ids)
    _publish_user_resource_updates(affected_user_ids)

    return {'ok': True, 'group': {'name': new_name}}


@router.delete('/api/admin/groups/{group_name}')
def delete_group_for_admin(group_name: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    group_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    if group_name == 'General':
        raise HTTPException(status_code=400, detail='The General group cannot be deleted.')

    affected_user_ids: list[str] = []
    moved_calendar_ids: list[str] = []

    with DB_LOCK:
        with _db_session() as session:
            group = session.scalar(select(GroupORM).where(GroupORM.name == group_name))
            if group is None:
                raise HTTPException(status_code=404, detail='Group not found.')

            affected_user_ids.extend(_approved_user_ids_for_group(session, group_name))
            affected_user_ids.extend(_approved_user_ids_for_group(session, 'General'))

            _ensure_group_names(session, ['General'])

            calendar_links = session.scalars(
                select(CalendarGroupLinkORM).where(CalendarGroupLinkORM.group_name == group_name)
            ).all()
            linked_calendar_ids = sorted({str(link.calendar_id) for link in calendar_links if link.calendar_id})
            for link in calendar_links:
                session.delete(link)

            calendars_with_primary_group = session.scalars(
                select(CalendarORM).where(CalendarORM.group_name == group_name)
            ).all()
            moved_calendar_ids = [calendar.id for calendar in calendars_with_primary_group]
            for calendar in calendars_with_primary_group:
                remaining_group_names = session.scalars(
                    select(CalendarGroupLinkORM.group_name)
                    .where(CalendarGroupLinkORM.calendar_id == calendar.id)
                    .order_by(CalendarGroupLinkORM.group_name.asc())
                ).all()
                next_primary_group = str(remaining_group_names[0]) if remaining_group_names else 'General'
                calendar.group_name = next_primary_group
                if next_primary_group == 'General' and session.get(CalendarGroupLinkORM, (calendar.id, 'General')) is None:
                    session.add(CalendarGroupLinkORM(calendar_id=calendar.id, group_name='General'))

            user_links = session.scalars(
                select(GroupUserLinkORM).where(GroupUserLinkORM.group_name == group_name)
            ).all()
            for link in user_links:
                session.delete(link)

            session.delete(group)
            moved_calendar_ids.extend(linked_calendar_ids)

    moved_calendar_ids = sorted({calendar_id for calendar_id in moved_calendar_ids if calendar_id})
    if moved_calendar_ids:
        _publish_calendar_change('calendar_changed', entity_id=group_name, calendar_ids=moved_calendar_ids)
    _publish_user_resource_updates(affected_user_ids)

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
    affected_user_ids: list[str] = []
    with DB_LOCK:
        with _db_session() as session:
            calendar = session.get(CalendarORM, calendar_id)
            if calendar is None:
                raise HTTPException(status_code=404, detail='Calendar not found.')
            group_exists = session.scalar(select(GroupORM.name).where(GroupORM.name == group_name))
            if group_exists is None:
                raise HTTPException(status_code=404, detail='Group not found.')
            existing_group_names = set(session.scalars(
                select(CalendarGroupLinkORM.group_name)
                .where(CalendarGroupLinkORM.calendar_id == calendar.id)
            ).all())
            if group_name not in existing_group_names:
                existing_group_names.add(group_name)
                _replace_calendar_group_links(session, calendar.id, sorted(existing_group_names))
            affected_groups = set(existing_group_names)
            affected_groups.add(str(calendar.group_name or 'General'))
            for affected_group in affected_groups:
                affected_user_ids.extend(_approved_user_ids_for_group(session, affected_group))

    _publish_calendar_change('calendar_changed', entity_id=calendar_id, calendar_ids=[calendar_id])
    _publish_user_resource_updates(affected_user_ids)
    return {'ok': True, 'calendarId': calendar_id, 'groupName': group_name}


@router.delete('/api/admin/calendars/{calendar_id}/groups/{group_name}')
def remove_calendar_from_group_for_admin(
    calendar_id: str,
    group_name: str,
    request: Request,
    token: str | None = None,
) -> dict[str, Any]:
    token = _prefer_admin_session_cookie(request, token)
    _require_admin_user(token)
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')
    group_name = _sanitize_text_input(group_name, 'group_name', min_length=1, max_length=120)
    affected_user_ids: list[str] = []

    with DB_LOCK:
        with _db_session() as session:
            calendar = session.get(CalendarORM, calendar_id)
            if calendar is None:
                raise HTTPException(status_code=404, detail='Calendar not found.')

            existing_group_names = {
                str(value).strip()
                for value in session.scalars(
                    select(CalendarGroupLinkORM.group_name)
                    .where(CalendarGroupLinkORM.calendar_id == calendar.id)
                ).all()
                if str(value or '').strip()
            }
            current_primary_group = str(calendar.group_name or 'General').strip() or 'General'
            if current_primary_group:
                existing_group_names.add(current_primary_group)

            if group_name not in existing_group_names:
                raise HTTPException(status_code=404, detail='Calendar is not assigned to that group.')

            updated_group_names = set(existing_group_names)
            updated_group_names.discard(group_name)

            _replace_calendar_group_links(session, calendar.id, sorted(updated_group_names))

            if updated_group_names and current_primary_group not in updated_group_names:
                calendar.group_name = sorted(updated_group_names)[0]

            affected_groups = {group_name, *updated_group_names, current_primary_group, str(calendar.group_name or 'General')}
            for affected_group in affected_groups:
                affected_user_ids.extend(_approved_user_ids_for_group(session, affected_group))

    _publish_calendar_change('calendar_changed', entity_id=calendar_id, calendar_ids=[calendar_id])
    _publish_user_resource_updates(affected_user_ids)
    return {'ok': True, 'calendarId': calendar_id, 'removedGroupName': group_name}


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
    affected_user_ids: list[str] = []

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
            prior_group_name = str(calendar.group_name or 'General')
            calendar.name = name
            calendar.group_name = group_name
            existing_group_names = set(session.scalars(
                select(CalendarGroupLinkORM.group_name)
                .where(CalendarGroupLinkORM.calendar_id == calendar.id)
            ).all())
            existing_group_names.add(group_name)
            _replace_calendar_group_links(session, calendar.id, sorted(existing_group_names))
            calendar.color = color
            calendar.blurb = blurb
            calendar.image_url = image_url
            affected_groups = {prior_group_name, *existing_group_names}
            for affected_group in affected_groups:
                affected_user_ids.extend(_approved_user_ids_for_group(session, affected_group))

    _publish_calendar_change('calendar_changed', entity_id=calendar_id, calendar_ids=[calendar_id])
    _publish_user_resource_updates(affected_user_ids)
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
    affected_user_ids: list[str] = []

    with DB_LOCK:
        with _db_session() as session:
            group_exists = session.scalar(select(GroupORM.name).where(GroupORM.name == group_name))
            if group_exists is None:
                raise HTTPException(status_code=404, detail='Group not found.')

            existing_resource = session.scalar(
                select(CalendarORM).where(func.lower(CalendarORM.name) == resource_name.lower())
            )
            if existing_resource is not None:
                existing_group_names = set(session.scalars(
                    select(CalendarGroupLinkORM.group_name)
                    .where(CalendarGroupLinkORM.calendar_id == existing_resource.id)
                ).all())
                existing_group_names.add(group_name)
                _replace_calendar_group_links(session, existing_resource.id, sorted(existing_group_names))
                created = False
                calendar_id = existing_resource.id
                affected_groups = set(existing_group_names)
                affected_groups.add(str(existing_resource.group_name or 'General'))
            else:
                calendar_id = str(uuid4())
                next_sort_order = session.scalar(select(func.coalesce(func.max(CalendarORM.sort_order), 0))) or 0
                session.add(CalendarORM(
                    id=calendar_id,
                    name=resource_name,
                    group_name=group_name,
                    sort_order=int(next_sort_order) + 1,
                ))
                _replace_calendar_group_links(session, calendar_id, [group_name])
                created = True
                affected_groups = {group_name}
            for affected_group in affected_groups:
                affected_user_ids.extend(_approved_user_ids_for_group(session, affected_group))

    _publish_calendar_change('calendar_changed', entity_id=calendar_id, calendar_ids=[calendar_id])
    _publish_user_resource_updates(affected_user_ids)

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
                created_at=now_str,
                last_login=now_str,
            )
            session.add(user)
            # Flush first so dependent link-table inserts can satisfy FK constraints.
            session.flush()
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
            'serviceAccount': False,
            'calendarIds': calendar_ids,
            'groupNames': group_names,
        },
        'token': login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={login_token}',
    }


@router.delete('/api/admin/users/{user_id}')
def delete_user_for_admin(user_id: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    actor = _session_user_for_login_or_api_token(token)
    user_id = _sanitize_id_input(user_id, 'user_id')

    if actor and actor.get('id') == user_id:
        raise HTTPException(status_code=400, detail='You cannot delete your own user account.')

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')

            if str(user.role or DEFAULT_USER_ROLE) == 'admin':
                admin_count = session.scalar(
                    select(func.count())
                    .select_from(UserORM)
                    .where(UserORM.role == 'admin')
                ) or 0
                if int(admin_count) <= 1:
                    raise HTTPException(status_code=400, detail='Cannot delete the last admin user.')

            session.query(UserCalendarLinkORM).filter(UserCalendarLinkORM.user_id == user_id).delete(synchronize_session=False)
            session.query(GroupUserLinkORM).filter(GroupUserLinkORM.user_id == user_id).delete(synchronize_session=False)
            session.query(UserPasskeyORM).filter(UserPasskeyORM.user_id == user_id).delete(synchronize_session=False)
            session.query(UserSavedShareLinkORM).filter(
                or_(
                    UserSavedShareLinkORM.user_id == user_id,
                    UserSavedShareLinkORM.source_user_id == user_id,
                )
            ).delete(synchronize_session=False)

            session.execute(
                update(EventORM)
                .where(EventORM.modified_by_user_id == user_id)
                .values(modified_by_user_id=None)
            )

            session.delete(user)

    _publish_user_resources_updated(user_id)
    return {'ok': True, 'userId': user_id}


@router.put('/api/admin/users/{user_id}/service-account')
def update_user_service_account_for_admin(
    user_id: str,
    payload: dict[str, Any],
    token: str | None = None,
) -> dict[str, Any]:
    _require_admin_user(token)
    user_id = _sanitize_id_input(user_id, 'user_id')
    service_account = bool(payload.get('serviceAccount'))

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            user.service_account = service_account

    return {'ok': True, 'userId': user_id, 'serviceAccount': service_account}


@router.get('/api/users/me/login-token')
def get_own_login_token(token: str | None = None) -> dict[str, Any]:
    actor = _require_authenticated_user(token)

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, actor['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            login_token = str(user.login_token or '').strip()
            if not login_token:
                login_token = _generate_unique_login_token(session)
                user.login_token = login_token

    return {
        'ok': True,
        'userId': actor['id'],
        'loginToken': login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={login_token}',
    }


@router.post('/api/users/me/login-token/regenerate')
def regenerate_own_login_token(token: str | None = None) -> dict[str, Any]:
    actor = _require_authenticated_user(token)

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, actor['id'])
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            new_login_token = _generate_unique_login_token(session)
            user.login_token = new_login_token

    return {
        'ok': True,
        'userId': actor['id'],
        'loginToken': new_login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={new_login_token}',
    }


@router.post('/api/admin/users/{user_id}/login-token/regenerate')
def regenerate_user_login_token_for_admin(user_id: str, token: str | None = None) -> dict[str, Any]:
    _require_admin_user(token)
    user_id = _sanitize_id_input(user_id, 'user_id')

    with DB_LOCK:
        with _db_session() as session:
            user = session.get(UserORM, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail='User not found.')
            new_login_token = _generate_unique_login_token(session)
            user.login_token = new_login_token

    return {
        'ok': True,
        'userId': user_id,
        'loginToken': new_login_token,
        'loginUrl': f'{APP_BASE_URL}/?token={new_login_token}',
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
    token: str | None = None,
) -> dict[str, Any]:
    url_token = _sanitize_token_input(url_token, 'url_token')
    session_token = str(token or '').strip()
    if session_token:
        try:
            session_token = _sanitize_token_input(session_token, 'token')
        except HTTPException:
            session_token = ''
    if not session_token:
        session_token = str(request.cookies.get('session_token') or '').strip()
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

            target_user = session.get(UserORM, session_user['id'])
            if target_user:
                merge_result = _merge_user_access_from_source(
                    session,
                    source_user_id=source_user_id,
                    target_user_id=target_user.id,
                    requested_calendar_ids=claim_calendar_ids if claim_calendar_ids else None,
                    approved_by_user_id=target_user.id,
                )
                _record_user_saved_share_link(session, target_user.id, source_user_id)
                claim_calendar_ids = sorted(merge_result.get('claimedCalendarIds') or [])

    _publish_user_resources_updated(session_user['id'])
    return {'ok': True, 'claimed': True, 'userId': session_user['id'], 'calendarIds': claim_calendar_ids}


@router.post('/api/logout')
def logout_user(response: Response) -> dict[str, Any]:
    """Clear auth cookies for the current browser session."""
    response.delete_cookie(key='session_token', path='/')
    response.delete_cookie(key='user_id', path='/')
    return {'ok': True}
