import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import _require_authenticated_user, _validate_read_token_access, _validate_token_access
from database import (
    DB_LOCK,
    _acquire_write_lock,
    _build_latest_events_stmt,
    _db_session,
    _next_event_version_ms,
    _run_write_with_retry,
)
from models import CalendarORM, EventORM
from realtime import _publish_calendar_change
from schemas import Event, EventCreate, EventUpdate
from utils import (
    _calendar_colors_for_ids,
    _compose_display_title,
    _dedupe_calendar_ids,
    _event_calendar_ids,
    _normalize_recurrence,
    _orm_calendar_ids,
    _orm_contact,
    _orm_event_committed,
    _orm_event_deleted,
    _orm_event_notes,
    _orm_event_title,
    _orm_event_uid,
    _orm_user_name,
    _parse_iso_datetime,
    _sanitize_calendar_ids_input,
    _sanitize_id_input,
    _sanitize_notes_input,
    _sanitize_text_input,
    _split_legacy_event_title,
    _striped_background,
    _validate_iso_datetime,
    _validate_range,
    expand_event_for_window,
    orm_to_event,
)

router = APIRouter()

# How far ahead to look for overlap detection in open-ended recurrences.
_OVERLAP_LOOKAHEAD_DAYS = 365


# ── Overlap detection ─────────────────────────────────────────────────────────

def _assert_no_calendar_overlap(
    session: Session,
    *,
    event_id: str,
    title: str,
    start: str,
    end: str | None,
    all_day: bool,
    recurrence: dict[str, Any] | None,
    calendar_ids: list[str],
    exclude_event_id: str | None = None,
) -> None:
    if not calendar_ids:
        raise HTTPException(status_code=400, detail='At least one calendar must be selected.')

    candidate_calendar_ids = _dedupe_calendar_ids(calendar_ids)
    if not candidate_calendar_ids:
        raise HTTPException(status_code=400, detail='At least one calendar must be selected.')

    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end) if end else start_dt
    until_dt = (
        _parse_iso_datetime(recurrence['until'])
        if recurrence and recurrence.get('until')
        else None
    )

    window_start = start_dt - timedelta(seconds=1)
    if recurrence and until_dt is None:
        window_end = max(end_dt, start_dt + timedelta(days=_OVERLAP_LOOKAHEAD_DAYS)) + timedelta(seconds=1)
    else:
        window_end = max(end_dt, until_dt if until_dt is not None else end_dt) + timedelta(seconds=1)

    candidate_event = EventORM(
        id=event_id,
        event_uid=event_id,
        version=1,
        deleted=0,
        title=title,
        start=start,
        end_time=end,
        all_day=int(all_day),
        recurrence_freq=recurrence['freq'] if recurrence else None,
        recurrence_interval=recurrence['interval'] if recurrence else None,
        recurrence_until=recurrence['until'] if recurrence else None,
        calendar_id=candidate_calendar_ids[0],
        calendar_ids=json.dumps(candidate_calendar_ids),
        notes='',
        committed=0,
        modified_by_user_id=None,
        modified_at=None,
        user_name='',
        event_title='',
        contact='',
    )
    candidate_colors = _calendar_colors_for_ids(session, candidate_calendar_ids)
    candidate_instances = expand_event_for_window(candidate_event, window_start, window_end, colors=candidate_colors)
    if not candidate_instances:
        return

    base_stmt, event_alias, _ = _build_latest_events_stmt()
    stmt = base_stmt.where(event_alias.deleted == 0)
    if exclude_event_id is not None:
        stmt = stmt.where(event_alias.event_uid != exclude_event_id)
    other_events = session.scalars(stmt).all()

    other_instances: list[dict[str, Any]] = []
    candidate_set = set(candidate_calendar_ids)
    for other_event in other_events:
        existing_calendar_ids = _orm_calendar_ids(other_event)
        if not candidate_set.intersection(existing_calendar_ids):
            continue
        other_instances.extend(
            expand_event_for_window(
                other_event,
                window_start,
                window_end,
                colors=_calendar_colors_for_ids(session, existing_calendar_ids),
            )
        )

    for candidate in candidate_instances:
        for existing in other_instances:
            candidate_start = _parse_iso_datetime(candidate['start'])
            candidate_end = _parse_iso_datetime(candidate['end']) if candidate['end'] else candidate_start
            existing_start = _parse_iso_datetime(existing['start'])
            existing_end = _parse_iso_datetime(existing['end']) if existing['end'] else existing_start
            if candidate_start < existing_end and existing_start < candidate_end:
                raise HTTPException(
                    status_code=409,
                    detail='Event overlaps another event on the same calendar.',
                )


# ── Event routes ──────────────────────────────────────────────────────────────

@router.get('/api/events')
def list_events(
    start: str | None = None, end: str | None = None, token: str | None = None
) -> list[dict[str, Any]]:
    from auth import _require_valid_token
    allowed_cals = _require_valid_token(token)
    if start is not None:
        _validate_iso_datetime(start, 'start')
    if end is not None:
        _validate_iso_datetime(end, 'end')

    now = datetime.now().astimezone()
    window_start = _parse_iso_datetime(start) if start else now - timedelta(days=180)
    window_end = _parse_iso_datetime(end) if end else now + timedelta(days=180)

    with DB_LOCK:
        with _db_session() as session:
            base_stmt, event_alias, _ = _build_latest_events_stmt()
            stmt = base_stmt.where(event_alias.deleted == 0).order_by(event_alias.start.asc())
            event_rows = session.scalars(stmt).all()

            events: list[dict[str, Any]] = []
            for event in event_rows:
                calendar_ids = _orm_calendar_ids(event)
                if not any(cid in allowed_cals for cid in calendar_ids):
                    continue
                events.extend(
                    expand_event_for_window(
                        event,
                        window_start,
                        window_end,
                        colors=_calendar_colors_for_ids(session, calendar_ids),
                    )
                )
    return events


@router.get('/api/events/{event_id}', response_model=Event)
def get_event(event_id: str, token: str | None = None) -> dict[str, Any]:
    event_id = _sanitize_id_input(event_id, 'event_id')
    with DB_LOCK:
        with _db_session() as session:
            base_stmt, event_alias, _ = _build_latest_events_stmt()
            event = session.scalar(
                base_stmt.where(event_alias.event_uid == event_id)
            )
            if event is None or _orm_event_deleted(event):
                raise HTTPException(status_code=404, detail='Event not found.')
            calendar_ids = _orm_calendar_ids(event)
            _validate_read_token_access(token, calendar_ids)
            return orm_to_event(event, _calendar_colors_for_ids(session, calendar_ids))


@router.get('/api/events/{event_id}/instances')
def get_event_instances(
    event_id: str,
    start: str,
    end: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    event_id = _sanitize_id_input(event_id, 'event_id')
    _validate_iso_datetime(start, 'start')
    _validate_iso_datetime(end, 'end')
    window_start = _parse_iso_datetime(start)
    window_end = _parse_iso_datetime(end)

    with DB_LOCK:
        with _db_session() as session:
            base_stmt, event_alias, _ = _build_latest_events_stmt()
            event = session.scalar(
                base_stmt.where(event_alias.event_uid == event_id)
            )
            if event is None or _orm_event_deleted(event):
                return []
            calendar_ids = _orm_calendar_ids(event)
            _validate_read_token_access(token, calendar_ids)
            return expand_event_for_window(
                event,
                window_start,
                window_end,
                colors=_calendar_colors_for_ids(session, calendar_ids),
            )


@router.post('/api/events', response_model=Event)
def create_event(event: EventCreate, request: Request, token: str | None = None) -> dict[str, Any]:
    actor = _require_authenticated_user(token)
    legacy_name, legacy_event_title = _split_legacy_event_title(event.title)
    name = _sanitize_text_input(event.name or legacy_name, 'name', min_length=0, max_length=120)
    event_title = _sanitize_text_input(event.eventTitle or legacy_event_title, 'eventTitle', min_length=0, max_length=200)
    contact = _sanitize_text_input(event.contact or '', 'contact', min_length=0, max_length=160)
    title = _compose_display_title(name, event_title)
    if not title:
        raise HTTPException(status_code=400, detail='Name or Event Name is required.')
    notes = _sanitize_notes_input(event.notes, 'notes')
    committed = bool(event.committed)
    _validate_iso_datetime(event.start, 'start')
    if event.end:
        _validate_iso_datetime(event.end, 'end')
    _validate_range(event.start, event.end)
    recurrence = _normalize_recurrence(event.recurrence)
    calendar_ids = _event_calendar_ids(event.calendarIds, event.calendarId)
    _validate_token_access(token, calendar_ids)
    modified_at = datetime.now().astimezone().isoformat()
    event_uid = str(uuid4())

    def _write_create() -> tuple[list[str], int]:
        with _acquire_write_lock():
            with _db_session() as session:
                event_version = _next_event_version_ms(session, event_uid)
                _assert_no_calendar_overlap(
                    session,
                    event_id=event_uid,
                    title=title,
                    start=event.start,
                    end=event.end,
                    all_day=event.allDay,
                    recurrence=recurrence,
                    calendar_ids=calendar_ids,
                )
                session.add(EventORM(
                    id=str(uuid4()),
                    event_uid=event_uid,
                    version=event_version,
                    deleted=0,
                    title=title,
                    start=event.start,
                    end_time=event.end,
                    all_day=int(event.allDay),
                    recurrence_freq=recurrence['freq'] if recurrence else None,
                    recurrence_interval=recurrence['interval'] if recurrence else None,
                    recurrence_until=recurrence['until'] if recurrence else None,
                    calendar_id=calendar_ids[0],
                    calendar_ids=json.dumps(calendar_ids),
                    notes=notes,
                    committed=int(committed),
                    modified_by_user_id=actor['id'],
                    modified_at=modified_at,
                    user_name=name,
                    event_title=event_title,
                    contact=contact,
                ))
                colors = _calendar_colors_for_ids(session, calendar_ids)
                return colors, event_version

    colors, event_version = _run_write_with_retry(_write_create)
    _publish_calendar_change(
        'event_created',
        event_uid,
        version=event_version,
        deleted=False,
        source_client_id=request.headers.get('x-client-id'),
        source_change_id=request.headers.get('x-change-id'),
        calendar_ids=calendar_ids,
    )

    return {
        'id': event_uid,
        'title': title,
        'name': name,
        'eventTitle': event_title,
        'contact': contact,
        'start': event.start,
        'end': event.end,
        'allDay': event.allDay,
        'recurrence': recurrence,
        'notes': notes,
        'committed': committed,
        'version': event_version,
        'deleted': False,
        'modifiedByUserId': actor['id'],
        'modifiedAt': modified_at,
        'calendarId': calendar_ids[0] if calendar_ids else None,
        'calendarIds': calendar_ids,
        'calendarColors': colors,
        'backgroundColor': _striped_background(colors),
        'borderColor': colors[0],
    }


@router.put('/api/events/{event_id}', response_model=Event)
def update_event(
    event_id: str,
    payload: EventUpdate,
    request: Request,
    token: str | None = None,
) -> dict[str, Any]:
    event_id = _sanitize_id_input(event_id, 'event_id')
    actor = _require_authenticated_user(token)
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail='No fields were provided to update.')

    if 'title' in update_data and update_data['title'] is not None:
        update_data['title'] = _sanitize_text_input(update_data['title'], 'title', min_length=1, max_length=200)
    if 'name' in update_data and update_data['name'] is not None:
        update_data['name'] = _sanitize_text_input(update_data['name'], 'name', min_length=0, max_length=120)
    if 'eventTitle' in update_data and update_data['eventTitle'] is not None:
        update_data['eventTitle'] = _sanitize_text_input(update_data['eventTitle'], 'eventTitle', min_length=0, max_length=200)
    if 'contact' in update_data and update_data['contact'] is not None:
        update_data['contact'] = _sanitize_text_input(update_data['contact'], 'contact', min_length=0, max_length=160)
    if 'notes' in update_data:
        update_data['notes'] = _sanitize_notes_input(update_data.get('notes'), 'notes')
    if 'start' in update_data and update_data['start']:
        _validate_iso_datetime(update_data['start'], 'start')
    if 'end' in update_data and update_data['end']:
        _validate_iso_datetime(update_data['end'], 'end')
    if 'recurrence' in update_data:
        update_data['recurrence'] = _normalize_recurrence(update_data['recurrence'])

    def _write_update() -> tuple[dict[str, Any], list[str], int]:
        modified_at = datetime.now().astimezone().isoformat()
        with _acquire_write_lock():
            with _db_session() as session:
                base_stmt, event_alias, _ = _build_latest_events_stmt()
                event = session.scalar(
                    base_stmt.where(event_alias.event_uid == event_id)
                )
                if event is None or _orm_event_deleted(event):
                    raise HTTPException(status_code=404, detail='Event not found.')

                existing_recurrence = None
                if event.recurrence_freq is not None:
                    existing_recurrence = {
                        'freq': event.recurrence_freq,
                        'interval': event.recurrence_interval or 1,
                        'until': event.recurrence_until,
                    }

                existing_calendar_ids = _orm_calendar_ids(event)
                if 'calendarIds' in update_data or 'calendarId' in update_data:
                    merged_calendar_ids = _event_calendar_ids(
                        update_data.get('calendarIds'),
                        update_data.get('calendarId'),
                    )
                else:
                    merged_calendar_ids = existing_calendar_ids
                _validate_token_access(token, merged_calendar_ids)

                merged = {
                    'id':          _orm_event_uid(event),
                    'name':        update_data.get('name', _orm_user_name(event)),
                    'eventTitle':  update_data.get('eventTitle', _orm_event_title(event)),
                    'contact':     update_data.get('contact', _orm_contact(event)),
                    'start':       update_data.get('start', event.start),
                    'end':         update_data.get('end', event.end_time),
                    'allDay':      bool(update_data.get('allDay', bool(event.all_day))),
                    'recurrence':  update_data.get('recurrence', existing_recurrence),
                    'calendarIds': merged_calendar_ids,
                    'notes':       update_data.get('notes', _orm_event_notes(event)),
                    'committed':   bool(update_data.get('committed', _orm_event_committed(event))),
                }
                if 'title' in update_data and 'name' not in update_data and 'eventTitle' not in update_data:
                    inferred_name, inferred_event_title = _split_legacy_event_title(update_data['title'])
                    merged['name'] = inferred_name
                    merged['eventTitle'] = inferred_event_title
                merged['title'] = _compose_display_title(merged['name'], merged['eventTitle'])
                if not merged['title']:
                    raise HTTPException(status_code=400, detail='Name or Event Name is required.')
                _validate_range(merged['start'], merged['end'])
                _assert_no_calendar_overlap(
                    session,
                    event_id=event_id,
                    title=merged['title'],
                    start=merged['start'],
                    end=merged['end'],
                    all_day=merged['allDay'],
                    recurrence=merged['recurrence'],
                    calendar_ids=merged['calendarIds'],
                    exclude_event_id=event_id,
                )

                next_version = _next_event_version_ms(session, _orm_event_uid(event))

                session.add(EventORM(
                    id=str(uuid4()),
                    event_uid=_orm_event_uid(event),
                    version=next_version,
                    deleted=0,
                    title=merged['title'],
                    start=merged['start'],
                    end_time=merged['end'],
                    all_day=int(merged['allDay']),
                    recurrence_freq=merged['recurrence']['freq'] if merged['recurrence'] else None,
                    recurrence_interval=merged['recurrence']['interval'] if merged['recurrence'] else None,
                    recurrence_until=merged['recurrence']['until'] if merged['recurrence'] else None,
                    calendar_id=merged['calendarIds'][0] if merged['calendarIds'] else None,
                    calendar_ids=json.dumps(merged['calendarIds']),
                    notes=merged['notes'],
                    committed=int(merged['committed']),
                    modified_by_user_id=actor['id'],
                    modified_at=modified_at,
                    user_name=merged['name'],
                    event_title=merged['eventTitle'],
                    contact=merged['contact'],
                ))
                colors = _calendar_colors_for_ids(session, merged['calendarIds'])
                merged['modifiedByUserId'] = actor['id']
                merged['modifiedAt'] = modified_at
                return merged, colors, next_version

    merged, colors, new_version = _run_write_with_retry(_write_update)
    _publish_calendar_change(
        'event_updated',
        event_id,
        version=new_version,
        deleted=False,
        source_client_id=request.headers.get('x-client-id'),
        source_change_id=request.headers.get('x-change-id'),
        calendar_ids=merged.get('calendarIds'),
    )
    merged['id'] = event_id
    merged['version'] = new_version
    merged['deleted'] = False
    merged['calendarId'] = merged['calendarIds'][0] if merged['calendarIds'] else None
    merged['calendarColors'] = colors
    merged['backgroundColor'] = _striped_background(colors)
    merged['borderColor'] = colors[0]
    return merged


@router.delete('/api/events/{event_id}')
def delete_event(event_id: str, request: Request, token: str | None = None) -> dict[str, bool]:
    event_id = _sanitize_id_input(event_id, 'event_id')
    actor = _require_authenticated_user(token)
    calendar_ids: list[str] = []

    def _write_delete() -> int:
        nonlocal calendar_ids
        with _acquire_write_lock():
            with _db_session() as session:
                base_stmt, event_alias, _ = _build_latest_events_stmt()
                event = session.scalar(
                    base_stmt.where(event_alias.event_uid == event_id)
                )
                if event is None or _orm_event_deleted(event):
                    raise HTTPException(status_code=404, detail='Event not found.')
                calendar_ids = _orm_calendar_ids(event)
                _validate_token_access(token, calendar_ids)
                next_version = _next_event_version_ms(session, _orm_event_uid(event))
                modified_at = datetime.now().astimezone().isoformat()
                session.add(EventORM(
                    id=str(uuid4()),
                    event_uid=_orm_event_uid(event),
                    version=next_version,
                    deleted=1,
                    title=event.title,
                    start=event.start,
                    end_time=event.end_time,
                    all_day=int(bool(event.all_day)),
                    recurrence_freq=event.recurrence_freq,
                    recurrence_interval=event.recurrence_interval,
                    recurrence_until=event.recurrence_until,
                    calendar_id=event.calendar_id,
                    calendar_ids=event.calendar_ids,
                    notes=_orm_event_notes(event),
                    committed=int(_orm_event_committed(event)),
                    modified_by_user_id=actor['id'],
                    modified_at=modified_at,
                    user_name=_orm_user_name(event),
                    event_title=_orm_event_title(event),
                    contact=_orm_contact(event),
                ))
                return next_version

    deleted_version = _run_write_with_retry(_write_delete)
    _publish_calendar_change(
        'event_deleted',
        event_id,
        version=deleted_version,
        deleted=True,
        source_client_id=request.headers.get('x-client-id'),
        source_change_id=request.headers.get('x-change-id'),
        calendar_ids=calendar_ids,
    )
    return {'ok': True}
