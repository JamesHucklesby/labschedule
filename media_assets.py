from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from urllib.parse import quote as url_quote

from PIL import Image, UnidentifiedImageError

STATIC_ROOT = Path(__file__).resolve().parent / 'static'
CALENDAR_IMAGE_ROOT = STATIC_ROOT / 'calendar-images'
CALENDAR_THUMB_ROOT = STATIC_ROOT / 'calendar-thumbnails'


def ensure_static_asset_dirs() -> None:
    CALENDAR_IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    CALENDAR_THUMB_ROOT.mkdir(parents=True, exist_ok=True)


def calendar_image_url(filename: str) -> str:
    return f'/static/calendar-images/{url_quote(filename)}'


def calendar_thumbnail_url(filename: str) -> str:
    return f'/static/calendar-thumbnails/{url_quote(filename)}'


def thumbnail_url_for_image_url(image_url: str) -> str:
    value = str(image_url or '').strip()
    if value.startswith('/static/calendar-images/'):
        return value.replace('/static/calendar-images/', '/static/calendar-thumbnails/', 1)
    return value


def create_calendar_thumbnail(source_path: Path, thumbnail_path: Path, max_size: tuple[int, int] = (360, 240)) -> None:
    ensure_static_asset_dirs()
    try:
        with Image.open(source_path) as image:
            image.thumbnail(max_size)
            image_format = (image.format or 'PNG').upper()
            if image_format == 'JPG':
                image_format = 'JPEG'
            if image_format == 'JPEG' and image.mode not in {'RGB', 'L'}:
                image = image.convert('RGB')
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(thumbnail_path, format=image_format)
    except UnidentifiedImageError:
        thumbnail_path.write_bytes(source_path.read_bytes())


def _guess_image_mime_type(filename: str | None, content_type: str | None) -> str:
    value = str(content_type or '').strip().lower()
    if value.startswith('image/'):
        return value

    suffix = Path(str(filename or '')).suffix.lower()
    if suffix in {'.jpg', '.jpeg'}:
        return 'image/jpeg'
    if suffix == '.png':
        return 'image/png'
    if suffix == '.gif':
        return 'image/gif'
    if suffix == '.webp':
        return 'image/webp'
    if suffix == '.bmp':
        return 'image/bmp'
    if suffix == '.svg':
        return 'image/svg+xml'
    return 'application/octet-stream'


def bytes_to_data_url(data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(data).decode('ascii')
    return f'data:{mime_type};base64,{encoded}'


def create_calendar_thumbnail_data_url(
    source_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    max_size: tuple[int, int] = (360, 240),
) -> tuple[str, str]:
    mime_type = _guess_image_mime_type(filename, content_type)
    if mime_type == 'image/svg+xml':
        data_url = bytes_to_data_url(source_bytes, mime_type)
        return data_url, data_url

    try:
        with Image.open(BytesIO(source_bytes)) as image:
            image.thumbnail(max_size)
            image_format = (image.format or 'PNG').upper()
            if image_format == 'JPG':
                image_format = 'JPEG'
            if image_format == 'JPEG' and image.mode not in {'RGB', 'L'}:
                image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format=image_format)
            thumb_bytes = output.getvalue()
            thumb_mime = 'image/jpeg' if image_format == 'JPEG' else f'image/{image_format.lower()}'
            return bytes_to_data_url(source_bytes, mime_type), bytes_to_data_url(thumb_bytes, thumb_mime)
    except UnidentifiedImageError:
        data_url = bytes_to_data_url(source_bytes, mime_type)
        return data_url, data_url


def calendar_placeholder_data_url(name: str, group_name: str | None, accent: str | None) -> str:
    safe_name = str(name or 'Calendar')
    safe_group = str(group_name or 'General')
    safe_accent = str(accent or '#2563eb')
    svg = f'''
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">
        <title id="title">{safe_name}</title>
        <desc id="desc">{safe_group} calendar illustration</desc>
        <defs>
          <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#062f2d"/>
            <stop offset="100%" stop-color="{safe_accent}"/>
          </linearGradient>
          <radialGradient id="glow" cx="30%" cy="20%" r="80%">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.24"/>
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <rect width="1200" height="720" rx="48" fill="url(#bg)"/>
        <rect x="64" y="64" width="1072" height="592" rx="36" fill="#ffffff" fill-opacity="0.08" stroke="#ffffff" stroke-opacity="0.2"/>
        <circle cx="180" cy="136" r="140" fill="url(#glow)"/>
        <rect x="116" y="148" width="272" height="272" rx="36" fill="#ffffff" fill-opacity="0.16"/>
        <rect x="160" y="192" width="184" height="22" rx="11" fill="#ffffff" fill-opacity="0.92"/>
        <rect x="160" y="238" width="144" height="22" rx="11" fill="#ffffff" fill-opacity="0.78"/>
        <rect x="160" y="284" width="212" height="22" rx="11" fill="#ffffff" fill-opacity="0.78"/>
        <rect x="160" y="330" width="120" height="22" rx="11" fill="#ffffff" fill-opacity="0.78"/>
        <text x="460" y="244" fill="#ffffff" font-family="Plus Jakarta Sans, Arial, sans-serif" font-size="72" font-weight="800">{safe_name}</text>
        <text x="460" y="316" fill="#d1fae5" font-family="IBM Plex Sans, Arial, sans-serif" font-size="34" font-weight="600">{safe_group}</text>
        <text x="460" y="388" fill="#ecfeff" font-family="IBM Plex Sans, Arial, sans-serif" font-size="26" font-weight="400">Calendar overview</text>
      </svg>
    '''.strip()
    return 'data:image/svg+xml;utf8,' + url_quote(svg)
