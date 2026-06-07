"""
Application entry point.

Imports register all route handlers and the NiceGUI page, then starts the server.
"""
import asyncio

from nicegui import app, ui
from fastapi.staticfiles import StaticFiles
from media_assets import STATIC_ROOT, ensure_static_asset_dirs

# ── Register routes ───────────────────────────────────────────────────────────
from routes.calendars import router as calendars_router
from routes.admin import router as admin_router
from routes.events import router as events_router
from routes.oauth import router as oauth_router
import realtime  # registers the WebSocket route via realtime.router

app.include_router(calendars_router)
app.include_router(admin_router)
app.include_router(events_router)
app.include_router(oauth_router)
app.include_router(realtime.router)

ensure_static_asset_dirs()
app.mount('/static', StaticFiles(directory=str(STATIC_ROOT)), name='static')

# ── Register NiceGUI page ─────────────────────────────────────────────────────
import ui as app_ui  # noqa: F401  (side-effect: registers @ui.page('/'))

# ── Startup hooks ─────────────────────────────────────────────────────────────
from database import init_db


@app.on_startup
async def _run_database_migrations() -> None:
    from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
    print(
        f'[startup] Running database migrations against PostgreSQL at '
        f'{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}...',
        flush=True,
    )
    init_db()
    print('[startup] Database migrations complete.', flush=True)


@app.on_startup
async def _capture_server_loop() -> None:
    realtime.SERVER_LOOP = asyncio.get_running_loop()


# ── Run ───────────────────────────────────────────────────────────────────────
ui.run(title='NiceGUI FullCalendar App', host='0.0.0.0', port=8080, reload=False, show=False)
