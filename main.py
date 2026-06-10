"""
Application entry point.

Imports register all route handlers and the NiceGUI page, then starts the server.
"""
import asyncio
from sqlalchemy.exc import SQLAlchemyError

from fastapi import Request
from fastapi.responses import Response
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
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
from config import (
    APP_ALLOWED_HOSTS,
    ENABLE_GZIP,
    ENABLE_SECURITY_HEADERS,
    GZIP_MINIMUM_SIZE,
    TRUSTED_PROXY_IPS,
)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=APP_ALLOWED_HOSTS)
if ENABLE_GZIP:
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)


@app.middleware('http')
async def _security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    if not ENABLE_SECURITY_HEADERS:
        return response

    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')

    forwarded_proto = (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip().lower()
    effective_scheme = forwarded_proto if forwarded_proto in {'http', 'https'} else request.url.scheme
    if effective_scheme == 'https':
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


APP_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<path d="M24 6h16v6h-2v13l13 21a8 8 0 0 1-7 12H20a8 8 0 0 1-7-12l13-21V12h-2z" '
    'fill="#16a34a" stroke="#14532d" stroke-width="2"/>'
    '<path d="M21 46h22" stroke="#bbf7d0" stroke-width="4" stroke-linecap="round"/>'
    '<circle cx="28" cy="39" r="2" fill="#dcfce7"/>'
    '<circle cx="36" cy="43" r="2" fill="#dcfce7"/>'
    '</svg>'
)


@app.on_startup
async def _run_database_migrations() -> None:
    from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
    retry_seconds = 10
    while True:
        try:
            print(
                f'[startup] Running database migrations against PostgreSQL at '
                f'{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}...',
                flush=True,
            )
            init_db()
            print('[startup] Database migrations complete.', flush=True)
            return
        except SQLAlchemyError as exc:
            print(
                f'[startup] Database unavailable, retrying in {retry_seconds}s: {exc}',
                flush=True,
            )
            await asyncio.sleep(retry_seconds)


@app.on_startup
async def _capture_server_loop() -> None:
    realtime.SERVER_LOOP = asyncio.get_running_loop()


# ── Run ───────────────────────────────────────────────────────────────────────
ui.run(
    title='LabSchedule',
    favicon=APP_FAVICON_SVG,
    host='0.0.0.0',
    port=777,
    reload=False,
    show=False,
    proxy_headers=True,
    forwarded_allow_ips=','.join(sorted(TRUSTED_PROXY_IPS)) or '127.0.0.1',
)
