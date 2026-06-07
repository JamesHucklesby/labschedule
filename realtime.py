import asyncio
from threading import Lock
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import _get_login_or_api_token_allowed_calendars, _get_login_or_api_token_owner_user_id

# ── Global state ──────────────────────────────────────────────────────────────

SERVER_LOOP: asyncio.AbstractEventLoop | None = None
WS_CLIENTS_LOCK = Lock()
# Maps WebSocket -> {'token': str | None, 'allowed_calendars': set[str] | None, 'user_id': str | None}
WS_CLIENT_INFO: dict[WebSocket, dict[str, Any]] = {}

router = APIRouter()


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket('/ws/calendar-updates')
async def ws_calendar_updates(websocket: WebSocket) -> None:
    await websocket.accept()

    token = None
    authorization = (websocket.headers.get('authorization') or '').strip()
    if authorization.lower().startswith('bearer '):
        token = authorization[7:].strip() or None
    if not token:
        token = websocket.cookies.get('session_token') if websocket.cookies else None

    allowed_calendars = _get_login_or_api_token_allowed_calendars(token) if token else set()
    user_id = _get_login_or_api_token_owner_user_id(token) if token else None

    with WS_CLIENTS_LOCK:
        WS_CLIENT_INFO[websocket] = {
            'token': token,
            'allowed_calendars': allowed_calendars,
            'user_id': user_id,
        }

    try:
        while True:
            payload = await websocket.receive_text()
            if payload == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        pass
    finally:
        with WS_CLIENTS_LOCK:
            WS_CLIENT_INFO.pop(websocket, None)


# ── Broadcast helpers ─────────────────────────────────────────────────────────

async def _broadcast_calendar_change(
    event: str,
    entity_id: str | None = None,
    version: int | None = None,
    deleted: bool | None = None,
    source_client_id: str | None = None,
    source_change_id: str | None = None,
    calendar_ids: list[str] | None = None,
) -> None:
    with WS_CLIENTS_LOCK:
        clients_info = list(WS_CLIENT_INFO.items())
    if not clients_info:
        return

    message = {
        'type': 'calendar_changed',
        'event': event,
        'entityId': entity_id,
        'version': version,
        'deleted': deleted,
        'sourceClientId': source_client_id,
        'sourceChangeId': source_change_id,
    }
    stale: list[WebSocket] = []
    for websocket, info in clients_info:
        if info.get('token') is None:
            continue
        allowed_calendars = info.get('allowed_calendars')
        if calendar_ids:
            if not isinstance(allowed_calendars, set):
                continue
            if not any(cal_id in allowed_calendars for cal_id in calendar_ids):
                continue
        try:
            await websocket.send_json(message)
        except Exception:
            stale.append(websocket)

    if stale:
        with WS_CLIENTS_LOCK:
            for websocket in stale:
                WS_CLIENT_INFO.pop(websocket, None)


def _publish_calendar_change(
    event: str,
    entity_id: str | None = None,
    version: int | None = None,
    deleted: bool | None = None,
    source_client_id: str | None = None,
    source_change_id: str | None = None,
    calendar_ids: list[str] | None = None,
) -> None:
    if SERVER_LOOP is None:
        return
    asyncio.run_coroutine_threadsafe(
        _broadcast_calendar_change(
            event,
            entity_id,
            version,
            deleted,
            source_client_id,
            source_change_id,
            calendar_ids,
        ),
        SERVER_LOOP,
    )


async def _broadcast_user_resources_updated(user_id: str) -> None:
    with WS_CLIENTS_LOCK:
        clients_info = list(WS_CLIENT_INFO.items())
    if not clients_info:
        return

    message = {
        'type': 'user_resources_updated',
        'userId': user_id,
    }
    stale: list[WebSocket] = []
    for websocket, info in clients_info:
        if info.get('user_id') != user_id:
            continue
        token = info.get('token')
        if token:
            refreshed_allowed_calendars = _get_login_or_api_token_allowed_calendars(token)
            with WS_CLIENTS_LOCK:
                current_info = WS_CLIENT_INFO.get(websocket)
                if current_info is not None:
                    current_info['allowed_calendars'] = refreshed_allowed_calendars
        try:
            await websocket.send_json(message)
        except Exception:
            stale.append(websocket)

    if stale:
        with WS_CLIENTS_LOCK:
            for websocket in stale:
                WS_CLIENT_INFO.pop(websocket, None)


def _publish_user_resources_updated(user_id: str) -> None:
    if SERVER_LOOP is None:
        return
    asyncio.run_coroutine_threadsafe(
        _broadcast_user_resources_updated(user_id),
        SERVER_LOOP,
    )
