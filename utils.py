import calendar
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import (
    MAX_TEXT_INPUT_LENGTH,
    MAX_TOKEN_INPUT_LENGTH,
    MAX_CALENDAR_IDS_PER_REQUEST,
    MAX_NOTES_INPUT_LENGTH,
    _CONTROL_CHAR_PATTERN,
    _UNSAFE_NOTES_CONTROL_CHAR_PATTERN,
    _ID_PATTERN,
    _TOKEN_PATTERN,
    _EMAIL_PATTERN,
)
from models import CalendarORM, EventORM
from schemas import RecurrenceRule


# ── Input sanitization ────────────────────────────────────────────────────────

def _sanitize_text_input(
    value: str,
    field_name: str,
    *,
    min_length: int = 1,
    max_length: int = MAX_TEXT_INPUT_LENGTH,
) -> str:
    normalized = value.strip()
    if len(normalized) < min_length:
        raise HTTPException(status_code=400, detail=f'{field_name} is required.')
    if len(normalized) > max_length:
        raise HTTPException(status_code=400, detail=f'{field_name} is too long.')
    if _CONTROL_CHAR_PATTERN.search(normalized):
        raise HTTPException(status_code=400, detail=f'{field_name} contains invalid characters.')
    return normalized


def _sanitize_id_input(value: str, field_name: str) -> str:
    normalized = _sanitize_text_input(value, field_name, min_length=1, max_length=128)
    if not _ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f'{field_name} has an invalid format.')
    return normalized


def _sanitize_token_input(value: str, field_name: str = 'token') -> str:
    normalized = _sanitize_text_input(value, field_name, min_length=16, max_length=MAX_TOKEN_INPUT_LENGTH)
    # Preserve JWT tokens exactly because lowercasing/stripping changes signature bytes.
    if normalized.count('.') == 2:
        if not re.fullmatch(r'[A-Za-z0-9._-]{16,1024}', normalized):
            raise HTTPException(status_code=400, detail=f'{field_name} has an invalid format.')
        return normalized

    cleaned = re.sub(r'[^A-Za-z0-9]', '', normalized).lower()
    if len(cleaned) < 16:
        raise HTTPException(status_code=400, detail=f'{field_name} has an invalid format.')
    if not _TOKEN_PATTERN.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail=f'{field_name} has an invalid format.')
    return cleaned


def _sanitize_email_input(value: str, field_name: str = 'email') -> str:
    normalized = _sanitize_text_input(value.lower(), field_name, min_length=3, max_length=254)
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail='Invalid email format.')
    return normalized


def _sanitize_calendar_ids_input(calendar_ids: list[str], field_name: str = 'calendarIds') -> list[str]:
    if len(calendar_ids) > MAX_CALENDAR_IDS_PER_REQUEST:
        raise HTTPException(status_code=400, detail='Too many calendars provided.')
    sanitized: list[str] = []
    seen: set[str] = set()
    for index, calendar_id in enumerate(calendar_ids):
        normalized = _sanitize_id_input(str(calendar_id), f'{field_name}[{index}]')
        if normalized in seen:
            continue
        seen.add(normalized)
        sanitized.append(normalized)
    return sanitized


def _sanitize_notes_input(value: str | None, field_name: str = 'notes') -> str:
    if value is None:
        return ''
    normalized = str(value).strip()
    if len(normalized) > MAX_NOTES_INPUT_LENGTH:
        raise HTTPException(status_code=400, detail=f'{field_name} is too long.')
    if _UNSAFE_NOTES_CONTROL_CHAR_PATTERN.search(normalized):
        raise HTTPException(status_code=400, detail=f'{field_name} contains invalid characters.')
    return normalized


# ── Datetime helpers ──────────────────────────────────────────────────────────

def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _validate_iso_datetime(value: str, field_name: str) -> None:
    try:
        _parse_iso_datetime(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f'Invalid {field_name} datetime format.'
        ) from exc


def _validate_range(start: str, end: str | None) -> None:
    if end is None:
        return
    if _parse_iso_datetime(end) < _parse_iso_datetime(start):
        raise HTTPException(status_code=400, detail='end must be greater than or equal to start.')


def _normalize_recurrence(recurrence: RecurrenceRule | None) -> dict[str, Any] | None:
    if recurrence is None:
        return None
    if recurrence.until is not None:
        _validate_iso_datetime(recurrence.until, 'recurrence.until')
    return {
        'freq': recurrence.freq,
        'interval': recurrence.interval,
        'until': recurrence.until,
    }


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _next_occurrence(value: datetime, freq: str, interval: int) -> datetime:
    if freq == 'daily':
        return value + timedelta(days=interval)
    if freq == 'weekly':
        return value + timedelta(weeks=interval)
    return _add_months(value, interval)


def _overlaps_window(
    start: datetime,
    end: datetime | None,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    actual_end = end if end is not None else start
    return start < window_end and actual_end >= window_start


# ── Calendar / event ID helpers ───────────────────────────────────────────────

def _dedupe_calendar_ids(calendar_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for calendar_id in calendar_ids:
        if not calendar_id or calendar_id in seen:
            continue
        seen.add(calendar_id)
        deduped.append(calendar_id)
    return deduped


def _event_calendar_ids(calendar_ids: list[str] | None, calendar_id: str | None) -> list[str]:
    source = calendar_ids if calendar_ids is not None else ([calendar_id] if calendar_id else [])
    return _sanitize_calendar_ids_input(source)


def _calendar_colors_for_ids(session: Session, calendar_ids: list[str]) -> list[str]:
    colors: list[str] = []
    for calendar_id in _dedupe_calendar_ids(calendar_ids):
        color = session.scalar(select(CalendarORM.color).where(CalendarORM.id == calendar_id))
        if color is not None:
            colors.append(color)
    return colors or ['#64748b']


def _striped_background(colors: list[str]) -> str:
    if len(colors) <= 1:
        return colors[0] if colors else '#64748b'
    stripe_width = 10
    stops = []
    for index, color in enumerate(colors):
        start = index * stripe_width
        end = (index + 1) * stripe_width
        stops.append(f'{color} {start}px {end}px')
    return f"repeating-linear-gradient(45deg, {', '.join(stops)})"


# ── Legacy title helpers ──────────────────────────────────────────────────────

def _split_legacy_event_title(value: str | None) -> tuple[str, str]:
    raw = str(value or '').strip()
    if not raw:
        return '', ''
    if ' :: ' not in raw:
        return raw, ''
    left, right = raw.split(' :: ', 1)
    return left.strip(), right.strip()


def _compose_display_title(name: str, event_title: str) -> str:
    left = str(name or '').strip()
    right = str(event_title or '').strip()
    if left and right:
        return f'{left} :: {right}'
    return left or right


# ── ORM field accessors ───────────────────────────────────────────────────────

def _orm_calendar_ids(event: EventORM) -> list[str]:
    if event.calendar_ids:
        try:
            parsed = json.loads(event.calendar_ids)
            if isinstance(parsed, list):
                return _dedupe_calendar_ids([str(item) for item in parsed if item])
        except json.JSONDecodeError:
            pass
    return [event.calendar_id] if event.calendar_id else []


def _orm_event_uid(event: EventORM) -> str:
    return event.event_uid or event.id


def _orm_event_version(event: EventORM) -> int:
    return max(1, int(event.version)) if event.version is not None else 1


def _orm_event_deleted(event: EventORM) -> bool:
    return bool(event.deleted)


def _orm_event_notes(event: EventORM) -> str:
    return event.notes or ''


def _orm_event_committed(event: EventORM) -> bool:
    return bool(event.committed)


def _orm_modified_by_user_id(event: EventORM) -> str | None:
    return event.modified_by_user_id or None


def _orm_modified_at(event: EventORM) -> str | None:
    return event.modified_at or None


def _orm_user_name(event: EventORM) -> str:
    if event.user_name:
        return event.user_name
    user, _ = _split_legacy_event_title(event.title)
    return user


def _orm_event_title(event: EventORM) -> str:
    if event.event_title:
        return event.event_title
    _, et = _split_legacy_event_title(event.title)
    return et


def _orm_contact(event: EventORM) -> str:
    return event.contact or ''


# ── Row serialisation ─────────────────────────────────────────────────────────

def orm_to_event(event: EventORM, colors: list[str] | None = None) -> dict[str, Any]:
    calendar_ids = _orm_calendar_ids(event)
    normalized_colors = colors or ['#64748b']
    user_name = _orm_user_name(event)
    event_title = _orm_event_title(event)
    display_title = _compose_display_title(user_name, event_title) or event.title
    recurrence = None
    if event.recurrence_freq is not None:
        recurrence = {
            'freq':     event.recurrence_freq,
            'interval': event.recurrence_interval if event.recurrence_interval is not None else 1,
            'until':    event.recurrence_until,
        }
    return {
        'id':               _orm_event_uid(event),
        'title':            display_title,
        'name':             user_name,
        'eventTitle':       event_title,
        'contact':          _orm_contact(event),
        'start':            event.start,
        'end':              event.end_time,
        'allDay':           bool(event.all_day),
        'recurrence':       recurrence,
        'version':          _orm_event_version(event),
        'deleted':          _orm_event_deleted(event),
        'notes':            _orm_event_notes(event),
        'committed':        _orm_event_committed(event),
        'modifiedByUserId': _orm_modified_by_user_id(event),
        'modifiedAt':       _orm_modified_at(event),
        'calendarId':       calendar_ids[0] if calendar_ids else None,
        'calendarIds':      calendar_ids,
        'calendarColors':   normalized_colors,
        'backgroundColor':  _striped_background(normalized_colors),
        'borderColor':      normalized_colors[0],
    }


def expand_event_for_window(
    event: EventORM,
    window_start: datetime,
    window_end: datetime,
    colors: list[str] | None = None,
) -> list[dict[str, Any]]:
    base = orm_to_event(event, colors)
    base_start = _parse_iso_datetime(base['start'])
    base_end   = _parse_iso_datetime(base['end']) if base['end'] else None
    duration   = base_end - base_start if base_end else None
    recurrence = base['recurrence']

    if recurrence is None:
        if _overlaps_window(base_start, base_end, window_start, window_end):
            base['extendedProps'] = {
                'seriesId':       base['id'],
                'isRecurring':    False,
                'recurrence':     None,
                'calendarId':     base['calendarId'],
                'calendarIds':    base['calendarIds'],
                'calendarColors': base['calendarColors'],
                'notes':          base.get('notes', ''),
                'committed':      bool(base.get('committed', False)),
            }
            return [base]
        return []

    until_dt      = _parse_iso_datetime(recurrence['until']) if recurrence['until'] else None
    interval      = recurrence['interval'] or 1
    current_start = base_start
    expanded: list[dict[str, Any]] = []

    for index in range(1000):
        if current_start >= window_end:
            break
        if until_dt is not None and current_start > until_dt:
            break
        current_end = current_start + duration if duration else None
        if _overlaps_window(current_start, current_end, window_start, window_end):
            expanded.append({
                'id':              f"{base['id']}::{index}",
                'title':           base['title'],
                'start':           current_start.isoformat(),
                'end':             current_end.isoformat() if current_end else None,
                'allDay':          base['allDay'],
                'notes':           base.get('notes', ''),
                'committed':       bool(base.get('committed', False)),
                'backgroundColor': _striped_background(base['calendarColors']),
                'borderColor':     base['calendarColors'][0],
                'extendedProps': {
                    'seriesId':       base['id'],
                    'isRecurring':    True,
                    'recurrence':     recurrence,
                    'calendarId':     base['calendarId'],
                    'calendarIds':    base['calendarIds'],
                    'calendarColors': base['calendarColors'],
                    'notes':          base.get('notes', ''),
                    'committed':      bool(base.get('committed', False)),
                },
            })
        current_start = _next_occurrence(current_start, recurrence['freq'], interval)

    return expanded


# ── Overlap helpers ───────────────────────────────────────────────────────────

def _instance_bounds(event_instance: dict[str, Any]) -> tuple[datetime, datetime]:
    start_dt = _parse_iso_datetime(event_instance['start'])
    end_value = event_instance.get('end')
    end_dt = _parse_iso_datetime(end_value) if end_value else start_dt
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(microseconds=1)
    return start_dt, end_dt


def _instances_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_start, a_end = _instance_bounds(a)
    b_start, b_end = _instance_bounds(b)
    return a_start < b_end and b_start < a_end
