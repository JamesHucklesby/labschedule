import json
from html import escape as html_escape
from urllib.parse import quote as url_quote

from fastapi import HTTPException, Request
from nicegui import ui
from sqlalchemy import select

from auth import _session_user_for_login_or_api_token
from database import _db_session
from models import CalendarORM
from utils import _sanitize_id_input


_APP_PAGE_TITLE = 'LabSchedule'
_FAVICON_SVG = (
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  '<path d="M24 6h16v6h-2v13l13 21a8 8 0 0 1-7 12H20a8 8 0 0 1-7-12l13-21V12h-2z" '
  'fill="#16a34a" stroke="#14532d" stroke-width="2"/>'
  '<path d="M21 46h22" stroke="#bbf7d0" stroke-width="4" stroke-linecap="round"/>'
  '<circle cx="28" cy="39" r="2" fill="#dcfce7"/>'
  '<circle cx="36" cy="43" r="2" fill="#dcfce7"/>'
  '</svg>'
)
_FAVICON_DATA_URI = 'data:image/svg+xml;utf8,' + url_quote(_FAVICON_SVG)


def _apply_page_branding() -> None:
  ui.add_head_html(f'<title>{html_escape(_APP_PAGE_TITLE)}</title>')
  ui.add_head_html(
    f'<link rel="icon" type="image/svg+xml" href="{html_escape(_FAVICON_DATA_URI)}">'
  )


def _calendar_info_blurb(calendar: CalendarORM) -> str:
    blurb = str(getattr(calendar, 'blurb', '') or '').strip()
    if blurb:
        return blurb
    group_name = calendar.group_name or 'General'
    return f'{calendar.name} belongs to the {group_name} group and is available from the main schedule.'


def _calendar_info_image_src(calendar: CalendarORM) -> str:
    image_url = str(getattr(calendar, 'image_url', '') or '').strip()
    if image_url:
        return image_url

    accent = calendar.color or '#2563eb'
    title = html_escape(calendar.name)
    group_name = html_escape(calendar.group_name or 'General')
    svg = f'''
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">
        <title id="title">{title}</title>
        <desc id="desc">{group_name} calendar illustration</desc>
        <defs>
          <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#062f2d"/>
            <stop offset="100%" stop-color="{accent}"/>
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
        <text x="460" y="244" fill="#ffffff" font-family="Plus Jakarta Sans, Arial, sans-serif" font-size="72" font-weight="800">{title}</text>
        <text x="460" y="316" fill="#d1fae5" font-family="IBM Plex Sans, Arial, sans-serif" font-size="34" font-weight="600">{group_name}</text>
        <text x="460" y="388" fill="#ecfeff" font-family="IBM Plex Sans, Arial, sans-serif" font-size="26" font-weight="400">Calendar overview</text>
      </svg>
    '''.strip()
    return 'data:image/svg+xml;utf8,' + url_quote(svg)


@ui.page('/calendar-info/{calendar_id}')
def calendar_info_page(calendar_id: str) -> None:
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')
    with _db_session() as session:
        calendar = session.get(CalendarORM, calendar_id)

    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">'
    )
    _apply_page_branding()
    ui.add_head_html('''
        <style>
          html, body {
            margin: 0;
            padding: 0;
            min-height: 100%;
            background:
              radial-gradient(circle at top left, rgba(16, 185, 129, 0.18), transparent 38%),
              radial-gradient(circle at top right, rgba(14, 116, 144, 0.18), transparent 32%),
              linear-gradient(145deg, #042f2e 0%, #082f2b 45%, #062f2d 100%);
            color: #e2e8f0;
            font-family: 'IBM Plex Sans', sans-serif;
          }
          h1, h2, h3 {
            font-family: 'Plus Jakarta Sans', sans-serif;
          }
          .calendar-info-page {
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 28px;
          }
          .calendar-info-card {
            width: min(1080px, 100%);
            background: rgba(7, 26, 30, 0.82);
            border: 1px solid rgba(167, 243, 208, 0.18);
            box-shadow: 0 28px 70px rgba(2, 8, 16, 0.38);
            border-radius: 28px;
            overflow: hidden;
            backdrop-filter: blur(14px);
          }
          .calendar-info-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            padding: 20px 22px 0;
          }
          .calendar-info-back {
            color: #a7f3d0;
            text-decoration: none;
            font-weight: 700;
          }
          .calendar-info-back:hover { text-decoration: underline; }
          .calendar-info-body {
            display: grid;
            grid-template-columns: minmax(280px, 0.95fr) minmax(0, 1.15fr);
            gap: 24px;
            padding: 22px;
            align-items: center;
          }
          .calendar-info-image {
            width: 100%;
            aspect-ratio: 4 / 3;
            object-fit: cover;
            border-radius: 22px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(255, 255, 255, 0.05);
          }
          .calendar-info-copy {
            display: grid;
            gap: 12px;
          }
          .calendar-info-kicker {
            display: inline-flex;
            width: fit-content;
            align-items: center;
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(16, 185, 129, 0.14);
            color: #bbf7d0;
            border: 1px solid rgba(167, 243, 208, 0.24);
            font-size: 0.78rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }
          .calendar-info-copy h1 {
            margin: 0;
            color: #f8fafc;
            font-size: clamp(2rem, 4vw, 3.8rem);
            line-height: 1.02;
          }
          .calendar-info-copy p {
            margin: 0;
            color: #dbeafe;
            font-size: 1rem;
            line-height: 1.7;
            max-width: 60ch;
          }
          .calendar-info-fallback {
            padding: 22px;
            color: #dbeafe;
          }
          .calendar-info-fallback h1 {
            margin: 8px 0 12px;
            color: #f8fafc;
          }
          @media (max-width: 860px) {
            .calendar-info-body {
              grid-template-columns: 1fr;
            }
            .calendar-info-top {
              padding: 18px 18px 0;
            }
          }
        </style>
    ''')

    if calendar is None:
        ui.add_body_html('''
          <main class="calendar-info-page">
            <section class="calendar-info-card calendar-info-fallback">
              <a class="calendar-info-back" href="/">Back to schedule</a>
              <h1>Calendar not found</h1>
              <p>The requested calendar could not be located.</p>
            </section>
          </main>
        ''')
        return

    image_src = _calendar_info_image_src(calendar)
    calendar_name = html_escape(calendar.name)
    calendar_group = html_escape(calendar.group_name or 'General')
    calendar_blurb = html_escape(_calendar_info_blurb(calendar))
    calendar_image_src = html_escape(image_src, quote=True)

    ui.add_body_html(f'''
      <main class="calendar-info-page">
        <section class="calendar-info-card">
          <div class="calendar-info-top">
            <a class="calendar-info-back" href="/">Back to schedule</a>
          </div>
          <div class="calendar-info-body">
            <img class="calendar-info-image" src="{calendar_image_src}" alt="{calendar_name} calendar image" />
            <div class="calendar-info-copy">
              <div class="calendar-info-kicker">{calendar_group}</div>
              <h1>{calendar_name}</h1>
              <p>{calendar_blurb}</p>
            </div>
          </div>
        </section>
      </main>
    ''')


@ui.page('/calendar-edit/{calendar_id}')
def calendar_editor_page(calendar_id: str, request: Request) -> None:
    session_token = request.cookies.get('session_token')
    current_user = _session_user_for_login_or_api_token(session_token)
    calendar_id = _sanitize_id_input(calendar_id, 'calendar_id')

    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">'
    )
    _apply_page_branding()
    ui.add_head_html('''
        <style>
          html, body {
            margin: 0;
            padding: 0;
            min-height: 100%;
            background:
              radial-gradient(circle at top left, rgba(16, 185, 129, 0.18), transparent 38%),
              radial-gradient(circle at top right, rgba(14, 116, 144, 0.18), transparent 32%),
              linear-gradient(145deg, #042f2e 0%, #082f2b 45%, #062f2d 100%);
            color: #e2e8f0;
            font-family: 'IBM Plex Sans', sans-serif;
          }
          h1, h2, h3 {
            font-family: 'Plus Jakarta Sans', sans-serif;
          }
          .calendar-edit-page {
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 28px;
          }
          .calendar-edit-card {
            width: min(1160px, 100%);
            background: rgba(7, 26, 30, 0.82);
            border: 1px solid rgba(167, 243, 208, 0.18);
            box-shadow: 0 28px 70px rgba(2, 8, 16, 0.38);
            border-radius: 28px;
            overflow: hidden;
            backdrop-filter: blur(14px);
          }
          .calendar-edit-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            padding: 20px 22px 0;
          }
          .calendar-edit-back {
            color: #a7f3d0;
            text-decoration: none;
            font-weight: 700;
          }
          .calendar-edit-back:hover { text-decoration: underline; }
          .calendar-edit-body {
            display: grid;
            grid-template-columns: minmax(300px, 0.92fr) minmax(0, 1.08fr);
            gap: 24px;
            padding: 22px;
            align-items: start;
          }
          .calendar-edit-image {
            width: 100%;
            aspect-ratio: 4 / 3;
            object-fit: cover;
            border-radius: 22px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(255, 255, 255, 0.05);
          }
          .calendar-edit-copy {
            display: grid;
            gap: 12px;
          }
          .calendar-edit-kicker {
            display: inline-flex;
            width: fit-content;
            align-items: center;
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(16, 185, 129, 0.14);
            color: #bbf7d0;
            border: 1px solid rgba(167, 243, 208, 0.24);
            font-size: 0.78rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }
          .calendar-edit-copy h1 {
            margin: 0;
            color: #f8fafc;
            font-size: clamp(2rem, 4vw, 3.4rem);
            line-height: 1.02;
          }
          .calendar-edit-copy p {
            margin: 0;
            color: #dbeafe;
            font-size: 0.98rem;
            line-height: 1.65;
          }
          .calendar-edit-grid {
            display: grid;
            gap: 14px;
            margin-top: 8px;
          }
          .calendar-edit-field {
            display: grid;
            gap: 6px;
          }
          .calendar-edit-field label {
            color: #dbeafe;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            text-transform: uppercase;
          }
          .calendar-edit-field input,
          .calendar-edit-field textarea {
            border: 1px solid #cbd5e1;
            border-radius: 12px;
            padding: 11px 12px;
            font-size: 0.95rem;
            background: #fff;
            color: #0f172a;
          }
          .calendar-edit-field textarea {
            min-height: 120px;
            resize: vertical;
            line-height: 1.5;
          }
          .calendar-edit-file {
            color: #dbeafe;
            font-size: 0.9rem;
          }
          .calendar-edit-upload-note {
            color: #cbd5e1;
            font-size: 0.84rem;
            line-height: 1.5;
          }
          .calendar-edit-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
          }
          .calendar-edit-actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 8px;
          }
          .calendar-edit-color-preview {
            margin-top: 8px;
            width: 100%;
            min-height: 36px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #0f172a;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
          }
          .calendar-edit-button {
            border: none;
            border-radius: 12px;
            padding: 12px 16px;
            font-weight: 800;
            cursor: pointer;
          }
          .calendar-edit-button.primary {
            background: linear-gradient(135deg, #22c55e 0%, #14b8a6 100%);
            color: #03261e;
          }
          .calendar-edit-button.secondary {
            background: rgba(255, 255, 255, 0.08);
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.25);
          }
          .calendar-edit-status {
            min-height: 1.2rem;
            color: #bbf7d0;
            font-size: 0.9rem;
          }
          .calendar-edit-disabled {
            padding: 24px 22px 28px;
            color: #dbeafe;
          }
          .calendar-edit-disabled h1 {
            margin: 8px 0 12px;
            color: #f8fafc;
          }
          @media (max-width: 860px) {
            .calendar-edit-body {
              grid-template-columns: 1fr;
            }
            .calendar-edit-row {
              grid-template-columns: 1fr;
            }
          }
        </style>
    ''')

    if not current_user or current_user.get('role') != 'admin':
        ui.add_body_html('''
          <main class="calendar-edit-page">
            <section class="calendar-edit-card calendar-edit-disabled">
              <a class="calendar-edit-back" href="/">Back to schedule</a>
              <h1>Access denied</h1>
              <p>This calendar editor is available to authenticated admin users only.</p>
            </section>
          </main>
        ''')
        return

    with _db_session() as session:
        calendar = session.get(CalendarORM, calendar_id)

    if calendar is None:
        ui.add_body_html('''
          <main class="calendar-edit-page">
            <section class="calendar-edit-card calendar-edit-disabled">
              <a class="calendar-edit-back" href="/">Back to schedule</a>
              <h1>Calendar not found</h1>
              <p>The requested calendar could not be located.</p>
            </section>
          </main>
        ''')
        return

    calendar_name = html_escape(calendar.name)
    calendar_group = html_escape(calendar.group_name or 'General')
    calendar_color = html_escape(calendar.color or '#2563eb', quote=True)
    calendar_blurb = html_escape(calendar.blurb or '')
    calendar_image_src = html_escape(_calendar_info_image_src(calendar), quote=True)
    calendar_info_href = f'/calendar-info/{html_escape(calendar.id, quote=True)}'

    ui.add_body_html(f'''
      <main class="calendar-edit-page">
        <section class="calendar-edit-card">
          <div class="calendar-edit-top">
            <a class="calendar-edit-back" href="/">Back to schedule</a>
            <a class="calendar-edit-back" href="{calendar_info_href}">View information page</a>
          </div>
          <div class="calendar-edit-body">
            <img id="calendar-edit-image" class="calendar-edit-image" src="{calendar_image_src}" alt="{calendar_name} preview" />
            <div class="calendar-edit-copy">
              <div class="calendar-edit-kicker">Calendar editor</div>
              <h1>Edit {calendar_name}</h1>
              <p>Update the information stored on the calendar record. Changes are reflected in the info page and sidebar after save.</p>
              <div class="calendar-edit-grid">
                <div class="calendar-edit-field">
                  <label for="calendar-edit-name">Calendar Name</label>
                  <input id="calendar-edit-name" type="text" value="{calendar_name}" />
                </div>
                <div class="calendar-edit-row">
                  <div class="calendar-edit-field">
                    <label for="calendar-edit-group">Group</label>
                    <input id="calendar-edit-group" type="text" value="{calendar_group}" />
                  </div>
                  <div class="calendar-edit-field">
                    <label for="calendar-edit-color">Color</label>
                    <input id="calendar-edit-color" type="color" value="{calendar_color}" />
                    <div class="calendar-edit-actions" style="margin-top: 6px;">
                      <button id="calendar-edit-suggest-color" type="button" class="calendar-edit-button secondary">Suggest Distinct Color</button>
                    </div>
                    <div id="calendar-edit-color-preview" class="calendar-edit-color-preview">{calendar_color.upper()}</div>
                  </div>
                </div>
                <div class="calendar-edit-field">
                  <label for="calendar-edit-blurb">Blurb</label>
                  <textarea id="calendar-edit-blurb" placeholder="Short description of this calendar">{calendar_blurb}</textarea>
                </div>
                <div class="calendar-edit-field">
                  <label for="calendar-edit-image-file">Image Upload</label>
                  <input id="calendar-edit-image-file" class="calendar-edit-file" type="file" accept="image/*" />
                  <input id="calendar-edit-image-url" type="hidden" value="{html_escape(calendar.image_url or '', quote=True)}" />
                  <div class="calendar-edit-upload-note" id="calendar-edit-image-note"></div>
                  <div class="calendar-edit-actions">
                    <button id="calendar-edit-upload" type="button" class="calendar-edit-button secondary">Upload Image</button>
                  </div>
                </div>
                <div class="calendar-edit-status" id="calendar-edit-status"></div>
                <div class="calendar-edit-actions">
                  <button id="calendar-edit-save" type="button" class="calendar-edit-button primary">Save Changes</button>
                  <button id="calendar-edit-reset" type="button" class="calendar-edit-button secondary">Reset</button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
      <script>
        (function() {{
          const calendarId = {json.dumps(calendar.id)};
          const sessionToken = {json.dumps(session_token or '')};
          const checkSessionUrl = '/api/auth/check-session';
          const initial = {json.dumps({
            'name': calendar.name,
            'groupName': calendar.group_name or 'General',
            'color': calendar.color or '#2563eb',
            'blurb': calendar.blurb or '',
            'imageUrl': calendar.image_url or '',
          })};
          const nameInput = document.getElementById('calendar-edit-name');
          const groupInput = document.getElementById('calendar-edit-group');
          const colorInput = document.getElementById('calendar-edit-color');
          const blurbInput = document.getElementById('calendar-edit-blurb');
          const imageFileInput = document.getElementById('calendar-edit-image-file');
          const imageInput = document.getElementById('calendar-edit-image-url');
          const imageUploadButton = document.getElementById('calendar-edit-upload');
          const imageNote = document.getElementById('calendar-edit-image-note');
          const saveButton = document.getElementById('calendar-edit-save');
          const resetButton = document.getElementById('calendar-edit-reset');
          const suggestColorButton = document.getElementById('calendar-edit-suggest-color');
          const colorPreviewBox = document.getElementById('calendar-edit-color-preview');
          const status = document.getElementById('calendar-edit-status');
          const preview = document.getElementById('calendar-edit-image');
          let storedImageUrl = initial.imageUrl;

          const updateImageNote = () => {{
            if (storedImageUrl) {{
              imageNote.textContent = 'Stored image is saved in the database.';
            }} else {{
              imageNote.textContent = 'No uploaded image yet. Upload a file to store it in the database.';
            }}
          }};

          const resolveAdminToken = async () => {{
            if (sessionToken) {{
              return sessionToken;
            }}
            try {{
              const response = await fetch(checkSessionUrl, {{
                method: 'GET',
                credentials: 'include',
                headers: {{ 'Content-Type': 'application/json' }},
              }});
              if (!response.ok) {{
                return '';
              }}
              const sessionData = await response.json().catch(() => null);
              return sessionData && sessionData.authenticated
                ? String(sessionData.apiToken || '')
                : '';
            }} catch {{
              return '';
            }}
          }};

          const updatePreview = () => {{
            if (imageInput.value.trim()) {{
              preview.src = imageInput.value.trim();
              return;
            }}
            preview.src = {json.dumps(_calendar_info_image_src(calendar))};
          }};

          const syncColorPreview = (value) => {{
            if (!colorPreviewBox) return;
            const next = String(value || '').trim() || '#2563eb';
            colorPreviewBox.style.background = next;
            colorPreviewBox.textContent = next.toUpperCase();
          }};

          updateImageNote();
          imageInput.value = storedImageUrl;
          syncColorPreview(colorInput.value || initial.color);

          imageInput.addEventListener('input', updatePreview);
          colorInput.addEventListener('input', () => syncColorPreview(colorInput.value));
          imageFileInput.addEventListener('change', () => {{
            const selectedFile = imageFileInput.files && imageFileInput.files[0];
            imageNote.textContent = selectedFile
              ? 'Selected file: ' + selectedFile.name
              : (storedImageUrl
                ? 'Stored image is saved in the database.'
                : 'No uploaded image yet. Upload a file to store it in the database.');
          }});
          imageUploadButton.addEventListener('click', async () => {{
            const selectedFile = imageFileInput.files && imageFileInput.files[0];
            if (!selectedFile) {{
              status.textContent = 'Choose an image file first.';
              return;
            }}
            status.textContent = 'Uploading image...';
            imageUploadButton.disabled = true;
            try {{
              await resolveAdminToken();
              const uploadPath = `/api/admin/calendars/${{encodeURIComponent(calendarId)}}/image`;
              const formData = new FormData();
              formData.append('file', selectedFile);
              const response = await fetch(uploadPath, {{
                method: 'POST',
                credentials: 'include',
                body: formData,
              }});
              const data = await response.json().catch(() => ({{ detail: 'Upload failed' }}));
              if (!response.ok) {{
                throw new Error(data.detail || 'Upload failed');
              }}
              storedImageUrl = data.imageUrl || '';
              imageInput.value = storedImageUrl;
              preview.src = storedImageUrl || preview.src;
              imageFileInput.value = '';
              updateImageNote();
              status.textContent = 'Image uploaded.';
            }} catch (error) {{
              status.textContent = error instanceof Error ? error.message : String(error);
            }} finally {{
              imageUploadButton.disabled = false;
            }}
          }});
          resetButton.addEventListener('click', () => {{
            nameInput.value = initial.name;
            groupInput.value = initial.groupName;
            colorInput.value = initial.color;
            blurbInput.value = initial.blurb;
            imageInput.value = initial.imageUrl;
            storedImageUrl = initial.imageUrl;
            imageFileInput.value = '';
            status.textContent = 'Changes reset.';
            updateImageNote();
            updatePreview();
            syncColorPreview(colorInput.value || initial.color);
          }});

          if (suggestColorButton) {{
            suggestColorButton.addEventListener('click', async () => {{
              const groupName = groupInput.value.trim();
              if (!groupName) {{
                status.textContent = 'Enter a group name first.';
                return;
              }}
              suggestColorButton.disabled = true;
              status.textContent = 'Suggesting color...';
              try {{
                const response = await fetch('/api/admin/calendars/suggest-color', {{
                  method: 'POST',
                  credentials: 'include',
                  headers: {{ 'Content-Type': 'application/json' }},
                  body: JSON.stringify({{ groupName, excludeCalendarId: calendarId, avoidColor: colorInput.value }}),
                }});
                const data = await response.json().catch(() => ({{ detail: 'Suggestion failed' }}));
                if (!response.ok) {{
                  throw new Error(data.detail || 'Suggestion failed');
                }}
                const nextColor = String(data.color || '').trim();
                if (!nextColor) {{
                  throw new Error('Suggestion failed');
                }}
                colorInput.value = nextColor;
                syncColorPreview(nextColor);
                status.textContent = `Suggested color: ${{nextColor}}`;
              }} catch (error) {{
                status.textContent = error instanceof Error ? error.message : String(error);
              }} finally {{
                suggestColorButton.disabled = false;
              }}
            }});
          }}

          saveButton.addEventListener('click', async () => {{
            const payload = {{
              name: nameInput.value.trim(),
              groupName: groupInput.value.trim(),
              color: colorInput.value.trim(),
              blurb: blurbInput.value.trim(),
              imageUrl: imageInput.value.trim(),
            }};
            if (!payload.name) {{
              status.textContent = 'Calendar name is required.';
              return;
            }}
            if (!payload.groupName) {{
              status.textContent = 'Group is required.';
              return;
            }}
            status.textContent = 'Saving...';
            saveButton.disabled = true;
            try {{
              await resolveAdminToken();
              const adminPath = `/api/admin/calendars/${{encodeURIComponent(calendarId)}}`;
              const response = await fetch(adminPath, {{
                method: 'PUT',
                credentials: 'include',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload),
              }});
              const data = await response.json().catch(() => ({{ detail: 'Save failed' }}));
              if (!response.ok) {{
                throw new Error(data.detail || 'Save failed');
              }}
              status.textContent = 'Saved.';
              updatePreview();
              window.location.reload();
            }} catch (error) {{
              status.textContent = error instanceof Error ? error.message : String(error);
            }} finally {{
              saveButton.disabled = false;
            }}
          }});
        }})();
      </script>
    ''')

@ui.page('/signup')
def signup_page() -> None:
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">'
    )
    _apply_page_branding()
    ui.add_body_html('''
      <style>
        html, body {
          margin: 0;
          min-height: 100%;
          background:
            radial-gradient(circle at top left, rgba(16, 185, 129, 0.2), transparent 40%),
            radial-gradient(circle at top right, rgba(14, 116, 144, 0.18), transparent 34%),
            linear-gradient(145deg, #042f2e 0%, #082f2b 48%, #062f2d 100%);
          color: #e2e8f0;
          font-family: 'IBM Plex Sans', sans-serif;
        }
        .signup-page {
          min-height: 100vh;
          display: grid;
          place-items: center;
          padding: 24px;
        }
        .signup-card {
          width: min(820px, 100%);
          border-radius: 24px;
          border: 1px solid rgba(167, 243, 208, 0.22);
          background: rgba(5, 23, 29, 0.86);
          box-shadow: 0 30px 70px rgba(2, 8, 16, 0.42);
          padding: 24px;
          display: grid;
          gap: 18px;
          backdrop-filter: blur(14px);
        }
        .signup-title {
          margin: 0;
          font-family: 'Plus Jakarta Sans', sans-serif;
          font-size: clamp(1.8rem, 4vw, 2.6rem);
          color: #f8fafc;
        }
        .signup-sub {
          margin: 0;
          color: #cbd5e1;
        }
        .signup-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 14px;
        }
        .signup-box {
          border: 1px solid rgba(148, 163, 184, 0.32);
          border-radius: 16px;
          padding: 16px;
          display: grid;
          gap: 12px;
          background: rgba(15, 23, 42, 0.4);
        }
        .signup-box h2 {
          margin: 0;
          font-family: 'Plus Jakarta Sans', sans-serif;
          font-size: 1.12rem;
          color: #f8fafc;
        }
        .signup-box p {
          margin: 0;
          color: #cbd5e1;
          font-size: 0.94rem;
          line-height: 1.45;
        }
        .signup-input {
          width: 100%;
          border: 1px solid #334155;
          border-radius: 10px;
          background: rgba(15, 23, 42, 0.72);
          color: #f8fafc;
          padding: 11px 12px;
          font-size: 0.95rem;
          box-sizing: border-box;
        }
        .signup-btn {
          border: none;
          border-radius: 10px;
          padding: 10px 14px;
          font-size: 0.95rem;
          font-weight: 700;
          cursor: pointer;
          color: #fff;
        }
        .signup-btn.oauth { background: #4285F4; }
        .signup-btn.local { background: #0e7490; }
        .signup-btn.passkey { background: #16a34a; }
        .signup-note {
          color: #a7f3d0;
          font-size: 0.92rem;
          min-height: 1.2rem;
        }
        .signup-result {
          border: 1px solid rgba(16, 185, 129, 0.32);
          border-radius: 14px;
          padding: 12px;
          background: rgba(16, 185, 129, 0.08);
          display: none;
          gap: 8px;
        }
        .signup-result a {
          color: #bbf7d0;
          word-break: break-all;
        }
        .signup-skip-link {
          color: #93c5fd;
          font-weight: 600;
          text-decoration: none;
          white-space: nowrap;
        }
        .signup-skip-link:hover {
          text-decoration: underline;
        }
        .signup-links {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }
        .signup-links a {
          color: #93c5fd;
        }
        @media (max-width: 760px) {
          .signup-row { grid-template-columns: 1fr; }
        }
      </style>
      <main class="signup-page">
        <section class="signup-card">
          <h1 class="signup-title">Create your Lab Scheduler account</h1>
          <p class="signup-sub">Choose OAuth signup or create a local account with a login link and passkey setup.</p>

          <div class="signup-row">
            <section class="signup-box">
              <h2>OAuth Signup</h2>
              <p>Use your university Google account. This matches the main login flow.</p>
              <button id="signup-oauth-btn" type="button" class="signup-btn oauth">Sign up with Google</button>
            </section>

            <section class="signup-box">
              <h2>Local Signup</h2>
              <p>Enter your name and email to get a login link. Then optionally create a passkey immediately.</p>
              <input id="signup-name" class="signup-input" type="text" maxlength="120" placeholder="Full name" />
              <input id="signup-email" class="signup-input" type="email" maxlength="254" placeholder="Email" />
              <input id="signup-passkey-name" class="signup-input" type="text" maxlength="80" placeholder="Passkey name (optional)" />
              <button id="signup-local-btn" type="button" class="signup-btn local">Create Account</button>
            </section>
          </div>

          <div id="signup-note" class="signup-note"></div>

          <section id="signup-result" class="signup-result">
            <div><strong>Login link issued:</strong></div>
            <a id="signup-login-link" href="#"></a>
            <div style="display:flex; gap:10px; flex-wrap: wrap;">
              <button id="signup-passkey-btn" type="button" class="signup-btn passkey">Create Passkey Now</button>
              <a id="signup-continue-link" class="signup-skip-link" href="/">Skip passkey and go to schedule</a>
            </div>
          </section>

          <div class="signup-links">
            <a href="/">Back to homepage</a>
          </div>
        </section>
      </main>
      <script>
        (() => {
          const oauthBtn = document.getElementById('signup-oauth-btn');
          const localBtn = document.getElementById('signup-local-btn');
          const passkeyBtn = document.getElementById('signup-passkey-btn');
          const note = document.getElementById('signup-note');
          const resultBox = document.getElementById('signup-result');
          const loginLink = document.getElementById('signup-login-link');
          const continueLink = document.getElementById('signup-continue-link');
          const nameInput = document.getElementById('signup-name');
          const emailInput = document.getElementById('signup-email');
          const passkeyNameInput = document.getElementById('signup-passkey-name');

          let apiToken = '';
          let loginToken = '';

          const toBuffer = (value) => {
            const input = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
            const padLen = (4 - (input.length % 4)) % 4;
            const padded = input + '='.repeat(padLen);
            const binary = atob(padded);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
            return bytes.buffer;
          };

          const toBase64Url = (buffer) => {
            const bytes = new Uint8Array(buffer);
            let binary = '';
            for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
            return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/g, '');
          };

          const fetchJson = async (path, method = 'GET', body = null) => {
            const opts = {
              method,
              credentials: 'include',
              headers: { 'Content-Type': 'application/json' },
            };
            if (body !== null) opts.body = JSON.stringify(body);
            const response = await fetch(path, opts);
            const data = await response.json().catch(() => ({ detail: 'Request failed' }));
            if (!response.ok) {
              throw new Error(String(data.detail || 'Request failed'));
            }
            return data;
          };

          oauthBtn?.addEventListener('click', () => {
            window.location.href = '/auth/google-login';
          });

          localBtn?.addEventListener('click', async () => {
            note.textContent = '';
            localBtn.disabled = true;
            localBtn.textContent = 'Creating...';
            try {
              const name = String(nameInput?.value || '').trim();
              const email = String(emailInput?.value || '').trim();
              const result = await fetchJson('/auth/local-signup', 'POST', { name, email });
              apiToken = String(result.apiToken || '').trim();
              loginToken = String(result.loginToken || '').trim();
              const url = String(result.loginUrl || '').trim();
              loginLink.href = url || '#';
              loginLink.textContent = url || 'Login link unavailable';
              continueLink.href = loginToken ? '/?token=' + encodeURIComponent(loginToken) : '/';
              resultBox.style.display = 'grid';
              note.textContent = 'Account created. You can now create a passkey.';
            } catch (error) {
              note.textContent = error instanceof Error ? error.message : String(error);
            } finally {
              localBtn.disabled = false;
              localBtn.textContent = 'Create Account';
            }
          });

          passkeyBtn?.addEventListener('click', async () => {
            if (!apiToken) {
              note.textContent = 'Create an account first.';
              return;
            }
            if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.create) {
              note.textContent = 'This browser does not support passkey creation.';
              return;
            }

            passkeyBtn.disabled = true;
            passkeyBtn.textContent = 'Creating passkey...';
            try {
              const optionsResult = await fetchJson('/api/passkeys/register/options?token=' + encodeURIComponent(apiToken), 'POST', {});
              const publicKey = optionsResult?.publicKey;
              if (!publicKey || !publicKey.challenge || !publicKey.user || !publicKey.user.id) {
                throw new Error('Invalid passkey options returned.');
              }

              const creationOptions = {
                ...publicKey,
                challenge: toBuffer(publicKey.challenge),
                user: {
                  ...publicKey.user,
                  id: toBuffer(publicKey.user.id),
                },
                excludeCredentials: Array.isArray(publicKey.excludeCredentials)
                  ? publicKey.excludeCredentials.map(descriptor => ({ ...descriptor, id: toBuffer(descriptor.id) }))
                  : [],
              };

              const credential = await navigator.credentials.create({ publicKey: creationOptions });
              if (!credential) {
                throw new Error('Passkey creation cancelled.');
              }

              const credentialPayload = {
                id: credential.id,
                type: credential.type,
                rawId: toBase64Url(credential.rawId),
                response: {
                  clientDataJSON: toBase64Url(credential.response.clientDataJSON),
                  attestationObject: toBase64Url(credential.response.attestationObject),
                  transports: typeof credential.response.getTransports === 'function' ? credential.response.getTransports() : [],
                },
              };

              const passkeyName = String(passkeyNameInput?.value || '').trim();
              await fetchJson('/api/passkeys/register/verify?token=' + encodeURIComponent(apiToken), 'POST', {
                credential: credentialPayload,
                passkeyName: passkeyName,
              });
              note.textContent = 'Passkey created successfully. Redirecting to schedule...';
              window.location.href = continueLink && continueLink.href ? continueLink.href : '/';
            } catch (error) {
              note.textContent = error instanceof Error ? error.message : String(error);
            } finally {
              passkeyBtn.disabled = false;
              passkeyBtn.textContent = 'Create Passkey Now';
            }
          });
        })();
      </script>
    ''')


@ui.page('/')
def index() -> None:
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">'
    )
    _apply_page_branding()
    ui.add_head_html(
        '<link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.css"'
        ' rel="stylesheet" />'
    )
    ui.add_head_html(
        '<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.js">'
        '</script>'
    )
    ui.add_head_html('''
        <style>
          /* Remove NiceGUI default padding so our layout fills the viewport */
          html, body { margin:0; padding:0; height:100%; width:100%; background:#062f2d; }
          body { font-family: 'IBM Plex Sans', sans-serif; }
          h1, h2, h3, .sidebar-logo { font-family: 'Plus Jakarta Sans', sans-serif; }
          .q-page, .nicegui-content {
            padding:0 !important;
            min-height:100vh;
            min-height:100dvh;
            width:100%;
            background:#062f2d;
          }
          .nicegui-content {
            max-width: none !important;
          }
          .nicegui-content > .nicegui-element {
            width: 100% !important;
            min-height: 100vh;
            min-height: 100dvh;
          }
          .nicegui-content > .nicegui-element > div {
            width: 100% !important;
            min-height: 100vh;
            min-height: 100dvh;
          }
          body > div[id^='c'] {
            width: 100% !important;
            max-width: none !important;
            min-height: 100vh;
            min-height: 100dvh;
          }
          body > div[id^='c'] > div {
            width: 100% !important;
            min-height: 100vh;
            min-height: 100dvh;
          }

          /* ── Biology landing screen ───────────────────── */
          .landing-screen {
            min-height: 100vh;
            min-height: 100dvh;
            width: 100%;
            height: 100vh;
            height: 100dvh;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 0;
            position: fixed;
            inset: 0;
            background:
              radial-gradient(circle at 15% 15%, rgba(16, 185, 129, 0.25), transparent 45%),
              radial-gradient(circle at 80% 30%, rgba(20, 184, 166, 0.2), transparent 40%),
              radial-gradient(circle at 25% 80%, rgba(132, 204, 22, 0.16), transparent 45%),
              linear-gradient(145deg, #042f2e 0%, #0b3b33 45%, #062f2d 100%);
            color: #e7fff7;
            z-index: 50;
            overflow: hidden;
            isolation: isolate;
          }
          .landing-screen.is-signin-modal::before {
            content: '';
            position: fixed;
            inset: 0;
            background: rgba(2, 6, 23, 0.72);
            backdrop-filter: blur(2px);
            z-index: 8;
          }
          #landing-screen {
            left: 50% !important;
            top: 0 !important;
            right: auto !important;
            bottom: 0 !important;
            width: 100vw !important;
            width: 100svw !important;
            height: 100vh !important;
            height: 100svh !important;
            min-height: 100vh !important;
            min-height: 100svh !important;
            margin: 0 !important;
            transform: translateX(-50%) !important;
          }
          .landing-screen::before,
          .landing-screen::after {
            content: '';
            position: absolute;
            width: 460px;
            height: 460px;
            border-radius: 50%;
            border: 1px solid rgba(167, 243, 208, 0.15);
            filter: blur(0.2px);
            pointer-events: none;
          }
          .landing-screen::before { top: -160px; right: -120px; }
          .landing-screen::after { bottom: -180px; left: -140px; }
          .landing-card {
            width: min(560px, calc(100% - 32px));
            background: linear-gradient(145deg, rgba(6, 24, 27, 0.84) 0%, rgba(10, 39, 34, 0.78) 100%);
            border: 1px solid rgba(167, 243, 208, 0.24);
            border-radius: 28px;
            backdrop-filter: blur(12px);
            box-shadow: 0 28px 70px rgba(2, 8, 16, 0.42);
            padding: clamp(22px, 4vw, 34px);
            position: relative;
            z-index: 2;
          }
          .landing-screen.is-signin-modal .landing-card {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: min(760px, calc(100vw - 32px));
            max-height: calc(100vh - 32px);
            overflow: auto;
            z-index: 9;
            box-shadow: 0 40px 90px rgba(2, 8, 16, 0.55);
          }
          .landing-content {
            width: 100%;
            position: relative;
            z-index: 2;
          }
          .landing-title {
            margin: 4px 0 8px;
            font-size: clamp(1.65rem, 4.8vw, 2.7rem);
            line-height: 1.15;
            color: #f0fdf4;
          }
          .landing-subtitle {
            margin: 0;
            color: #c7f9e7;
            font-size: 1rem;
            line-height: 1.45;
            max-width: none;
          }
          .landing-form {
            margin-top: 22px;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 10px;
          }
          .landing-input {
            border: 1px solid rgba(134, 239, 172, 0.38);
            border-radius: 12px;
            padding: 12px 14px;
            font-size: 1rem;
            color: #ecfeff;
            background: rgba(12, 36, 40, 0.72);
          }
          .landing-input::placeholder { color: rgba(191, 219, 254, 0.8); }
          .landing-input:focus {
            outline: none;
            border-color: #34d399;
            box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.22);
          }
          .landing-submit {
            border: none;
            border-radius: 12px;
            background: linear-gradient(135deg, #22c55e 0%, #14b8a6 100%);
            color: #03261e;
            font-weight: 800;
            letter-spacing: 0.01em;
            padding: 12px 16px;
            cursor: pointer;
            transition: transform 0.15s, box-shadow 0.15s;
          }
          .landing-submit:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(52, 211, 153, 0.35);
          }
          .landing-help {
            margin: 10px 0 0;
            font-size: 0.88rem;
            color: #bbf7d0;
            min-height: 1.25rem;
          }
          .landing-auth {
            margin-top: 20px;
            padding-top: 18px;
            border-top: 1px solid rgba(255,255,255,0.1);
            display: grid;
            gap: 12px;
          }
          .landing-auth-groups {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
          }
          .landing-auth-block {
            background: rgba(15, 23, 42, 0.58);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            padding: 12px;
            display: grid;
            gap: 10px;
          }
          .landing-auth-title {
            margin: 0;
            color: #cbd5e1;
            font-size: 0.95rem;
            font-weight: 700;
            text-align: center;
          }
          .landing-auth-row {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
          }
          .landing-auth-row-single {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
          }
          .landing-submit--auth {
            width: 100%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
          }
          .landing-auth .landing-input {
            max-width: none;
          }
          .landing-auth-close {
            display: none;
            border: 1px solid rgba(148, 163, 184, 0.24);
            background: rgba(15, 23, 42, 0.7);
            color: #e2e8f0;
            border-radius: 999px;
            padding: 8px 12px;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            justify-self: end;
          }
          .landing-auth-close:hover {
            background: rgba(30, 41, 59, 0.92);
          }
          .landing-screen.is-signin-modal .landing-auth-close {
            display: inline-flex;
          }
          .landing-auth-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(2, 6, 23, 0.68);
            backdrop-filter: blur(2px);
            z-index: 7;
          }
          .ws-status {
            margin: 10px 12px 14px;
            pointer-events: none;
            display: grid;
            gap: 4px;
            background: rgba(15, 23, 42, 0.62);
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.24);
            border-radius: 10px;
            padding: 8px 10px;
            font-size: 0.74rem;
            line-height: 1.25;
            font-family: Consolas, 'Courier New', monospace;
            min-width: 0;
            box-shadow: 0 8px 18px rgba(2, 6, 23, 0.24);
          }
          .ws-block-overlay {
            position: fixed;
            inset: 0;
            z-index: 10000;
            display: none;
            visibility: hidden;
            opacity: 0;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background: rgba(2, 6, 23, 0.56);
            backdrop-filter: blur(3px);
            pointer-events: auto;
            transition: opacity 0.16s ease;
          }
          dialog.ws-block-overlay {
            border: none;
            padding: 0;
            background: transparent;
            max-width: none;
            max-height: none;
          }
          dialog.ws-block-overlay::backdrop {
            background: rgba(2, 6, 23, 0.56);
            backdrop-filter: blur(3px);
          }
          dialog.ws-block-overlay[open] {
            display: flex;
            visibility: visible;
            opacity: 1;
          }
          .ws-block-overlay.visible {
            display: flex;
            visibility: visible;
            opacity: 1;
          }
          .ws-block-card {
            width: min(760px, calc(100% - 24px));
            border-radius: 18px;
            border: 2px solid rgba(248, 113, 113, 0.6);
            background: linear-gradient(160deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.98));
            box-shadow: 0 24px 64px rgba(2, 6, 23, 0.55);
            color: #fee2e2;
            text-align: center;
            padding: clamp(20px, 3.2vw, 36px);
          }
          .ws-block-title {
            margin: 0;
            font-size: clamp(1.65rem, 4.6vw, 2.95rem);
            line-height: 1.1;
            font-weight: 900;
            letter-spacing: 0.02em;
            color: #fecaca;
          }
          .ws-block-message {
            margin: 10px 0 0;
            font-size: clamp(1rem, 2.3vw, 1.34rem);
            color: #fecdd3;
            line-height: 1.42;
          }
          .ws-block-state {
            margin-top: 12px;
            font-size: 0.94rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #fda4af;
          }
          .ws-block-refresh {
            margin-top: 28px;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 14px 36px;
            font-size: clamp(1rem, 2.4vw, 1.25rem);
            font-weight: 700;
            letter-spacing: 0.04em;
            color: #fff;
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            border: 2px solid rgba(252, 165, 165, 0.45);
            border-radius: 12px;
            cursor: pointer;
            box-shadow: 0 4px 18px rgba(220, 38, 38, 0.45);
            transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
            pointer-events: auto;
          }
          .ws-block-refresh:hover {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            box-shadow: 0 6px 24px rgba(220, 38, 38, 0.6);
            transform: translateY(-1px);
          }
          .ws-block-refresh:active {
            transform: translateY(1px);
            box-shadow: 0 2px 10px rgba(220, 38, 38, 0.4);
          }
          .override-actions {
            margin-top: 24px;
            display: flex;
            justify-content: center;
            gap: 10px;
            flex-wrap: wrap;
          }
          .override-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 12px 22px;
            border-radius: 10px;
            border: 1px solid transparent;
            font-weight: 700;
            cursor: pointer;
            transition: transform 0.1s, box-shadow 0.15s;
          }
          .override-btn:active {
            transform: translateY(1px);
          }
          .override-btn-confirm {
            color: #fff;
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            border-color: rgba(252, 165, 165, 0.45);
            box-shadow: 0 4px 18px rgba(220, 38, 38, 0.45);
          }
          .override-btn-confirm:hover {
            box-shadow: 0 6px 24px rgba(220, 38, 38, 0.6);
            transform: translateY(-1px);
          }
          .override-btn-cancel {
            color: #fee2e2;
            background: rgba(15, 23, 42, 0.8);
            border-color: rgba(248, 113, 113, 0.35);
          }
          body.ws-input-blocked {
            overflow: hidden;
          }
          body.ws-input-blocked #app-shell,
          body.ws-input-blocked #landing-screen,
          body.ws-input-blocked dialog {
            pointer-events: none;
            user-select: none;
          }
          /* Hide NiceGUI's built-in "Trying to reconnect…" notification — our overlay replaces it */
          body.ws-input-blocked .q-notifications__list,
          body.ws-input-blocked [class*="nicegui-reconnect"],
          body.ws-input-blocked .nicegui-reconnect-dialog {
            display: none !important;
          }
          /* ── Save toast ───────────────────────────────────────────── */
          #save-toast {
            position: fixed;
            top: 18px;
            right: 18px;
            z-index: 9000;
            display: flex;
            align-items: flex-start;
            gap: 12px;
            min-width: 260px;
            max-width: min(400px, calc(100vw - 36px));
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            border: 1.5px solid rgba(52, 211, 153, 0.45);
            border-radius: 14px;
            box-shadow: 0 8px 32px rgba(2,6,23,0.38);
            padding: 14px 18px;
            color: #e2e8f0;
            font-size: 0.93rem;
            line-height: 1.4;
            pointer-events: auto;
            opacity: 0;
            transform: translateY(-8px);
            transition: opacity 0.18s ease, transform 0.18s ease;
          }
          #save-toast.visible {
            opacity: 1;
            transform: translateY(0);
          }
          .save-toast-icon {
            flex-shrink: 0;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: rgba(52, 211, 153, 0.18);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            margin-top: 1px;
          }
          .save-toast-body {
            flex: 1;
          }
          .save-toast-close {
            flex-shrink: 0;
            width: 22px;
            height: 22px;
            background: none;
            border: none;
            color: #64748b;
            cursor: pointer;
            font-size: 18px;
            padding: 0;
            line-height: 1;
            margin-top: -2px;
            transition: color 0.12s ease;
          }
          .save-toast-close:hover {
            color: #e2e8f0;
          }
          .save-toast-title {
            font-weight: 700;
            color: #34d399;
            margin-bottom: 2px;
          }
          .save-toast-sub {
            color: #94a3b8;
            font-size: 0.82rem;
          }
          .save-toast--error {
            border-color: rgba(239, 68, 68, 0.45);
          }
          .save-toast--error .save-toast-icon {
            background: rgba(239, 68, 68, 0.18);
          }
          .save-toast--error .save-toast-title {
            color: #f87171;
          }
          .ws-status-title {
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.67rem;
          }
          .ws-status-row {
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .ws-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #f59e0b;
            box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.25);
            flex: 0 0 auto;
          }
          .ws-indicator.connected {
            background: #22c55e;
            box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.25);
          }
          .ws-indicator.disconnected {
            background: #ef4444;
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.22);
          }
          .ws-indicator.error {
            background: #f97316;
            box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.24);
          }
          .slime-field {
            position: absolute;
            inset: 0;
            overflow: hidden;
            pointer-events: none;
            z-index: 0;
          }
          .slime-canvas {
            width: 100%;
            height: 100%;
            display: block;
            opacity: 0.82;
            filter: saturate(1.2) contrast(1.08) blur(0.15px);
          }
          .slime-vein-glow {
            position: absolute;
            inset: 0;
            background:
              radial-gradient(circle at 22% 30%, rgba(52, 211, 153, 0.18), transparent 40%),
              radial-gradient(circle at 70% 70%, rgba(45, 212, 191, 0.14), transparent 45%);
            mix-blend-mode: screen;
            opacity: 0.85;
          }
          .card-sheen {
            position: absolute;
            inset: 0;
            background: linear-gradient(180deg, rgba(220, 252, 231, 0.06), transparent 28%);
            pointer-events: none;
            z-index: 1;
            border-radius: 28px;
          }

          /* ── App shell ─────────────────────────────── */
          .app-layout {
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: #f0f4fa;
          }

          /* ── Left sidebar ──────────────────────────── */
          .sidebar {
            width: 220px;
            flex-shrink: 0;
            background: #ffffff;
            color: #0f172a;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            border-right: 1px solid #e2e8f0;
          }
          .sidebar-nav-spacer { flex: 1; min-height: 18px; }
          .sidebar-nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 12px 12px 16px;
            padding: 10px 12px;
            border-radius: 10px;
            color: #334155;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
            border: 1px solid #e2e8f0;
          }
          .sidebar-nav-item:hover,
          .sidebar-nav-item.active {
            background: #ecfeff;
            color: #0f766e;
            border-color: #99f6e4;
          }
          .sidebar-nav-icon {
            font-size: 0.92rem;
            width: 18px;
            text-align: center;
          }
          .sidebar-logo {
            padding: 20px 16px 16px;
            font-size: 1rem;
            font-weight: 800;
            letter-spacing: 0.01em;
            color: #0f172a;
            border-bottom: 1px solid #e2e8f0;
            cursor: pointer;
          }
          .sidebar-section-title {
            padding: 14px 16px 6px;
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: #64748b;
          }
          .sidebar-group-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding-right: 12px;
          }
          .sidebar-section-title--group {
            padding-right: 0;
          }
          .sidebar-group-toggle {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.7rem;
            color: #64748b;
            cursor: pointer;
            user-select: none;
          }
          .sidebar-cal-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 16px;
            cursor: pointer;
            transition: background 0.15s;
          }
          .sidebar-cal-item:hover { background: #f8fafc; }
          .sidebar-cal-meta {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            flex: 1;
          }
          .sidebar-cal-info {
            width: 22px;
            height: 22px;
            border-radius: 999px;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            color: #334155;
            font-size: 0.72rem;
            font-weight: 800;
            line-height: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
          }
          .sidebar-cal-info:hover {
            background: #ecfeff;
            border-color: #99f6e4;
            color: #0f766e;
          }

          /* Custom checkbox whose tick/border adopts the calendar colour via CSS var */
          .cal-checkbox {
            appearance: none;
            -webkit-appearance: none;
            width: 15px;
            height: 15px;
            border-radius: 4px;
            border: 2px solid var(--cal-color, #64748b);
            cursor: pointer;
            flex-shrink: 0;
            position: relative;
            transition: background 0.15s;
          }
          .cal-checkbox:checked { background: var(--cal-color, #64748b); }
          .cal-checkbox:checked::after {
            content: '';
            position: absolute;
            left: 2px; top: -1px;
            width: 5px; height: 9px;
            border: 2px solid #fff;
            border-top: none; border-left: none;
            transform: rotate(45deg);
          }
          .cal-name {
            font-size: 0.86rem;
            font-weight: 750;
          }

          /* ── Main content ──────────────────────────── */
          .main-content {
            flex: 1;
            overflow-y: auto;
            padding: 22px 24px;
            min-width: 0;
          }
          .calendar-card {
            background: #fff;
            border-radius: 14px;
            padding: 16px;
            box-shadow: 0 4px 24px rgba(15,23,42,0.07);
          }
          .admin-panel {
            display: grid;
            gap: 18px;
          }
          .admin-panel[hidden] { display: none; }
          .access-panel {
            display: grid;
            gap: 18px;
          }
          .access-panel[hidden] { display: none; }
          .upcoming-panel {
            display: grid;
            gap: 18px;
          }
          .upcoming-panel[hidden] { display: none; }
          .admin-card {
            background: #fff;
            border-radius: 14px;
            padding: 18px;
            box-shadow: 0 4px 24px rgba(15,23,42,0.07);
          }
          .admin-card h2 {
            margin: 0 0 8px;
            color: #0f172a;
            font-size: 1.15rem;
          }
          .admin-card p {
            margin: 0;
            color: #475569;
            font-size: 0.94rem;
          }
          .admin-link-grid {
            display: grid;
            gap: 16px;
            margin-top: 16px;
          }
          .admin-link-card {
            border: 1px solid #dbe4f0;
            border-radius: 12px;
            padding: 14px;
            background: #f8fafc;
            display: grid;
            gap: 12px;
          }
          .admin-link-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
          }
          .admin-link-token {
            font-family: "IBM Plex Sans", sans-serif;
            font-size: 0.84rem;
            color: #0f766e;
            word-break: break-all;
          .access-catalog-grid {
            display: grid;
            gap: 16px;
            margin-top: 16px;
          }
          }
          .admin-link-meta {
            font-size: 0.84rem;
            color: #64748b;
          }
          .admin-inline-link {
            font-size: 0.84rem;
            color: #0e7490;
            text-decoration: underline;
            cursor: pointer;
            width: fit-content;
          }
          .admin-inline-link[aria-disabled="true"] {
            color: #94a3b8;
            pointer-events: none;
            text-decoration: none;
            cursor: default;
          }
          .share-link-list {
            display: grid;
            gap: 12px;
          }
          .share-link-row {
            border: 1px solid #dbe4f0;
            border-radius: 12px;
            padding: 12px;
            background: #f8fafc;
            display: grid;
            gap: 6px;
          }
          .share-link-name {
            font-weight: 700;
            color: #0f172a;
          }
          .share-link-empty {
            color: #64748b;
            font-size: 0.95rem;
          }
          .admin-resource-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }
          .access-group-card {
            border: 1px solid #dbe4f0;
            border-radius: 12px;
            padding: 16px;
            background: linear-gradient(180deg, #fff, #f8fbff);
            display: grid;
            gap: 10px;
          }
          .access-group-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
          }
          .access-group-title {
            font-size: 1rem;
            font-weight: 800;
            color: #0f172a;
          }
          .access-group-subtitle {
            margin-top: 3px;
            font-size: 0.84rem;
            color: #64748b;
          }
          .access-group-calendar-list {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            padding-left: 10px;
          }
          .access-pill-button {
            border: 1px solid transparent;
            border-radius: 999px;
            padding: 8px 14px;
            font-weight: 800;
            font-size: 0.82rem;
            cursor: pointer;
            background: #0e7490;
            color: #fff;
            transition: transform 0.15s, box-shadow 0.15s, background 0.15s, border-color 0.15s;
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            justify-content: center;
          }
          .access-pill-button:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 8px 16px rgba(14, 116, 144, 0.24);
            background: #155e75;
          }
          .access-pill-button--granted,
          .access-pill-button:disabled {
            background: #cbd5e1;
            color: #64748b;
            box-shadow: none;
            cursor: not-allowed;
            transform: none;
          }
          .access-group-request {
            margin-left: auto;
          }
          .access-group-request[data-state="available"] {
            background: #0e7490;
            color: #fff;
          }
          .access-group-request[data-state="pending"],
          .access-group-request[data-state="requested"],
          .access-group-request[data-state="group-pending"] {
            background: #fff7ed;
            color: #f59e0b;
            border-color: #fed7aa;
          }
          .access-group-request[data-state="hidden"] {
            background: #fff7ed;
            color: #f59e0b;
            border-color: #fed7aa;
          }
          .access-group-request[data-state="granted"],
          .access-group-request[data-state="approved"] {
            background: #16a34a;
            color: #fff;
          }
          .access-pill-button[data-state="pending"],
          .access-pill-button[data-state="requested"],
          .access-pill-button[data-state="group-pending"] {
            background: #fff7ed;
            color: #f59e0b;
            border-color: #fed7aa;
            box-shadow: none;
          }
          .access-pill-button[data-state="hidden"] {
            background: #fff7ed;
            color: #f59e0b;
            border-color: #fed7aa;
            box-shadow: none;
          }
          .access-pill-button[data-state="pending"]:hover:not(:disabled),
          .access-pill-button[data-state="group-pending"]:hover:not(:disabled),
          .access-pill-button[data-state="hidden"]:hover:not(:disabled) {
            background: #ffedd5;
            color: #ea580c;
            box-shadow: 0 8px 16px rgba(245, 158, 11, 0.14);
          }
          .access-group-assets {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding-left: 10px;
          }
          .access-asset-pill {
            background: #e2e8f0;
            color: #0f172a;
            border-color: #cbd5e1;
            font-weight: 700;
          }
          .access-asset-pill:hover:not(:disabled) {
            background: #cbd5e1;
            color: #0f172a;
          }
          .access-asset-pill[data-state="granted"],
          .access-asset-pill[data-state="approved"] {
            background: #22c55e;
            color: #ffffff;
            border-color: #16a34a;
          }
          .access-asset-pill[data-state="granted"]:hover:not(:disabled) {
            background: #16a34a;
            color: #ffffff;
          }
          .access-asset-pill[data-state="hidden"] {
            background: #fff7ed;
            color: #f59e0b;
            border-color: #fed7aa;
            box-shadow: none;
          }
          .access-asset-pill[data-state="hidden"]:hover:not(:disabled) {
            background: #ffedd5;
            color: #ea580c;
            box-shadow: 0 8px 16px rgba(245, 158, 11, 0.14);
          }
          .admin-status-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
          }
          .admin-status-pill--pending {
            background: #fff7ed;
            color: #f59e0b;
          }
          .admin-status-pill--requested {
            background: #fff7ed;
            color: #f59e0b;
          }
          .admin-status-pill--hidden {
            background: #fff7ed;
            color: #f59e0b;
          }
          .admin-status-pill--approved {
            background: #ecfdf5;
            color: #16a34a;
          }
          .admin-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            border-radius: 999px;
            background: #e2e8f0;
            color: #0f172a;
            font-size: 0.82rem;
          }
          .admin-pill-group {
            background: #dbeafe;
            color: #1e3a8a;
          }
          .admin-pill-remove {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 16px;
            height: 16px;
            border: none;
            background: transparent;
            color: #334155;
            font-size: 0.82rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
            padding: 0;
          }
          .admin-pill-remove:hover { color: #991b1b; }
          .admin-editor-row {
            display: grid;
            grid-template-columns: minmax(220px, 1fr) auto;
            gap: 10px;
            align-items: center;
          }
          .admin-datalist-input {
            width: 100%;
            border: 1px solid #cbd5e1;
            border-radius: 9px;
            padding: 10px 12px;
            font-size: 0.94rem;
            background: #fff;
          }
          .settings-profile-field {
            display: grid;
            gap: 6px;
            margin-top: 8px;
          }
          .settings-profile-field label {
            color: #334155;
            font-size: 0.9rem;
            font-weight: 600;
          }
          .admin-helper {
            color: #64748b;
            font-size: 0.82rem;
          }
          .admin-save-button {
            border: none;
            border-radius: 10px;
            padding: 11px 18px;
            font-size: 0.96rem;
            font-weight: 700;
            cursor: pointer;
            background: #166534;
            color: #ffffff;
            transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
          }
          .admin-save-button:hover:not(:disabled) {
            background: #14532d;
            transform: translateY(-1px);
            box-shadow: 0 8px 16px rgba(22, 101, 52, 0.25);
          }
          .admin-save-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
          }
          .admin-resource-catalog {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }
          .admin-resource-option {
            border: 1px solid #bfdbfe;
            background: #eff6ff;
            color: #1e3a8a;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
          }
          .admin-resource-option:hover {
            background: #dbeafe;
            border-color: #93c5fd;
          }
          .admin-resource-option.assigned {
            background: #ecfdf5;
            border-color: #86efac;
            color: #166534;
            cursor: default;
          }
          .admin-order-list {
            display: grid;
            gap: 8px;
          }
          .admin-order-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 8px;
            align-items: center;
            border: 1px solid #dbe4f0;
            border-radius: 10px;
            background: #fff;
            padding: 8px 10px;
          }
          .admin-order-label {
            font-size: 0.86rem;
            font-weight: 650;
            display: inline-flex;
            align-items: center;
            gap: 8px;
          }
          .admin-order-swatch {
            width: 10px;
            height: 10px;
            border-radius: 999px;
            flex-shrink: 0;
            box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.18);
          }
          .admin-order-controls {
            display: inline-flex;
            gap: 6px;
          }
          .admin-vacuum-list {
            display: grid;
            gap: 8px;
          }
          .admin-vacuum-row {
            display: grid;
            grid-template-columns: minmax(0, 2fr) repeat(3, auto) auto;
            gap: 8px;
            align-items: center;
            border: 1px solid #dbe4f0;
            border-radius: 10px;
            background: #fff;
            padding: 8px 10px;
          }
          .admin-vacuum-label {
            display: grid;
            gap: 2px;
            min-width: 0;
          }
          .admin-vacuum-table-name {
            font-size: 0.88rem;
            font-weight: 700;
            color: #0f172a;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .admin-vacuum-table-meta {
            font-size: 0.78rem;
            color: #64748b;
          }
          .admin-vacuum-stat {
            font-size: 0.82rem;
            font-weight: 600;
            color: #334155;
            white-space: nowrap;
          }
          .upcoming-bookings-list {
            display: grid;
            gap: 10px;
            margin-top: 10px;
          }
          .upcoming-booking-row {
            border: 1px solid #dbe4f0;
            border-radius: 12px;
            background: #f8fafc;
            padding: 12px;
            display: grid;
            gap: 6px;
          }
          .upcoming-booking-title {
            margin: 0;
            color: #0f172a;
            font-size: 0.96rem;
            font-weight: 700;
          }
          .upcoming-booking-meta {
            margin: 0;
            color: #334155;
            font-size: 0.86rem;
          }
          .upcoming-booking-empty {
            border: 1px dashed #cbd5e1;
            border-radius: 12px;
            background: #f8fafc;
            color: #475569;
            font-size: 0.92rem;
            padding: 12px;
          }
          .calendar-editor-modal {
            width: min(1180px, calc(100vw - 32px));
            max-height: calc(100vh - 32px);
            border: none;
            border-radius: 16px;
            padding: 0;
            overflow: hidden;
            box-shadow: 0 32px 80px rgba(2, 8, 23, 0.42);
            background: #020617;
          }
          .calendar-editor-modal::backdrop {
            background: rgba(2, 6, 23, 0.68);
            backdrop-filter: blur(2px);
          }
          .calendar-editor-modal-shell {
            display: grid;
            grid-template-rows: auto 1fr;
            min-height: min(760px, calc(100vh - 32px));
            background: #020617;
          }
          .calendar-editor-modal-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 12px 14px;
            background: linear-gradient(135deg, #0f172a 0%, #082f49 100%);
            border-bottom: 1px solid rgba(148, 163, 184, 0.3);
          }
          .calendar-editor-modal-title {
            margin: 0;
            color: #e2e8f0;
            font-size: 0.94rem;
            font-weight: 700;
          }
          .calendar-editor-modal-close {
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: rgba(15, 23, 42, 0.85);
            color: #e2e8f0;
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
          }
          .calendar-editor-modal-close:hover {
            background: rgba(30, 41, 59, 0.95);
          }
          .calendar-editor-modal-frame {
            width: 100%;
            height: 100%;
            border: none;
            background: #020617;
          }
          .admin-performance-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
          }
          .admin-performance-table th,
          .admin-performance-table td {
            border-bottom: 1px solid #e2e8f0;
            padding: 7px 8px;
            vertical-align: top;
            text-align: left;
          }
          .admin-performance-table th {
            color: #334155;
            font-weight: 700;
            background: #f8fafc;
          }
          .admin-performance-query {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            white-space: normal;
            word-break: break-word;
            color: #0f172a;
          }
          .admin-section-title {
            margin-top: 10px;
            margin-bottom: 4px;
            color: #475569;
            font-size: 0.83rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
          }
          .admin-user-role {
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.03em;
          }
          .admin-user-role.admin {
            background: #dcfce7;
            color: #166534;
          }
          .admin-user-role.user {
            background: #e2e8f0;
            color: #334155;
          }
          #calendar { min-height: 680px; }

          /* FullCalendar button theming */
          .fc .fc-button-primary { background:#0e7490; border-color:#0e7490; }
          .fc .fc-button-primary:hover { background:#155e75; border-color:#155e75; }
          .fc .fc-bg-event.working-hours-highlight {
            background: rgba(14, 116, 144, 0.14);
            border: none;
          }

          /* ── Event dialog ──────────────────────────── */
          .event-dialog {
            border: none;
            border-radius: 14px;
            width: min(520px, calc(100% - 24px));
            max-width: 520px;
            box-shadow: 0 18px 45px rgba(15,23,42,0.2);
            padding: 0;
          }
          .event-dialog::backdrop {
            background: rgba(15,23,42,0.4);
            backdrop-filter: blur(2px);
          }
          .event-dialog-header {
            padding: 14px 16px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 1.1rem;
            font-weight: 700;
            color: #164e63;
          }
          .overlap-dialog-header {
            color: #991b1b;
          }
          .overlap-dialog-message {
            margin: 0;
            font-size: 0.95rem;
            color: #334155;
            line-height: 1.45;
            white-space: pre-wrap;
          }
          .event-dialog-body { padding: 14px 16px; display: grid; gap: 10px; }
          .event-dialog-field { display: grid; gap: 4px; }
          .event-dialog-field label { font-size: 0.9rem; color: #334155; }
          .event-dialog-field input,
          .event-dialog-field select,
          .event-dialog-field textarea {
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 9px 10px;
            font-size: 0.95rem;
          }
          .event-dialog-field--emphasis {
            padding: 12px;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            background: #f8fafc;
          }
          .event-dialog-field--emphasis > label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.95rem;
            font-weight: 600;
            color: #0f172a;
            margin: 0;
          }
          .event-dialog-field--emphasis input[type="checkbox"] {
            width: 16px;
            height: 16px;
            margin: 0;
            padding: 0;
            accent-color: #0e7490;
          }
          .event-dialog-field textarea {
            min-height: 140px;
            resize: vertical;
            line-height: 1.4;
          }
          .event-calendar-list {
            display: grid;
            gap: 8px;
            max-height: 180px;
            overflow: auto;
            padding: 10px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            background: #f8fafc;
          }
          .event-calendar-item {
            display: flex;
            align-items: center;
            gap: 10px;
          }
          .event-calendar-item--hidden {
            /* the row itself stays visible; only the availability is dimmed */
          }
          .event-calendar-item--hidden .event-calendar-toggle,
          .event-calendar-item--hidden .event-calendar-dot,
          .event-calendar-item--hidden .event-calendar-label {
            opacity: 0.48;
          }
          .event-calendar-toggle {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            flex: 1;
          }
          .event-calendar-info {
            margin-left: auto;
            width: 26px;
            height: 26px;
            border: 1px solid #cbd5e1;
            border-radius: 999px;
            background: #fff;
            color: #0f766e;
            font-weight: 800;
            line-height: 1;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
          }
          .event-calendar-info:hover {
            background: #ecfeff;
            border-color: #5eead4;
          }
          .event-calendar-info--booked {
            color: #b91c1c;
            border-color: #fca5a5;
            background: #fef2f2;
          }
          .event-calendar-info--booked:hover {
            background: #fee2e2;
            border-color: #ef4444;
          }
          .calendar-hover-tooltip {
            position: fixed;
            z-index: 2200;
            display: none;
            width: min(320px, calc(100vw - 20px));
            background: rgba(255, 255, 255, 0.98);
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.28);
            overflow: hidden;
            pointer-events: none;
          }
          .calendar-hover-tooltip--booked {
            border-color: #ef4444;
            box-shadow: 0 18px 40px rgba(185, 28, 28, 0.32);
          }
          .calendar-hover-tooltip--booked .calendar-hover-copy {
            background: #fef2f2;
            border-top: 1px solid #fca5a5;
          }
          .calendar-hover-tooltip img {
            display: block;
            width: 100%;
            aspect-ratio: 4 / 3;
            object-fit: cover;
            background: #e2e8f0;
          }
          .calendar-hover-copy {
            padding: 10px 12px 12px;
          }
          .calendar-hover-tooltip--booked .calendar-hover-title {
            color: #b91c1c;
          }
          .calendar-hover-tooltip--booked .calendar-hover-subtitle {
            color: #dc2626;
          }
          .calendar-hover-title {
            font-size: 0.92rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.3;
          }
          .calendar-hover-subtitle {
            margin-top: 4px;
            font-size: 0.8rem;
            color: #475569;
          }
          .event-calendar-dot {
            width: 12px;
            height: 12px;
            border-radius: 3px;
            flex-shrink: 0;
          }
          .event-calendar-label {
            font-size: 0.92rem;
            color: #334155;
          }
          .event-dialog-row { display:grid; gap:10px; grid-template-columns:1fr 1fr; }
          .event-dialog-actions {
            display: flex;
            justify-content: space-between;
            padding: 12px 16px 14px;
            border-top: 1px solid #e2e8f0;
            gap: 8px;
          }
          .btn { border:none; border-radius:8px; padding:9px 12px; font-weight:600; cursor:pointer; }
          .btn-primary { background:#0e7490; color:#fff; }
          .btn-danger  { background:#dc2626; color:#fff; }
          .btn-neutral { background:#e2e8f0; color:#0f172a; }
          .btn-group   { display:flex; gap:8px; }
          .save-account-auth-message {
            margin: 0;
            font-size: 0.94rem;
            color: #334155;
            line-height: 1.45;
          }
          .save-account-auth-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            flex-wrap: wrap;
          }
          .event-notes-tooltip {
            position: fixed;
            z-index: 2000;
            max-width: min(360px, calc(100vw - 24px));
            background: rgba(15, 23, 42, 0.95);
            color: #f8fafc;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.28);
            padding: 10px 12px;
            font-size: 0.86rem;
            line-height: 1.4;
            white-space: pre-wrap;
            pointer-events: none;
            display: none;
          }
          .event-lock-icon {
            margin-right: 6px;
            font-size: 0.9em;
            vertical-align: text-bottom;
          }
          .profile-screen {
            min-height: 100vh;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 24px;
            background:
              radial-gradient(circle at 20% 20%, rgba(16, 185, 129, 0.18), transparent 48%),
              radial-gradient(circle at 80% 10%, rgba(14, 116, 144, 0.18), transparent 42%),
              linear-gradient(160deg, #022c22 0%, #052e2b 56%, #082f2f 100%);
          }
          .profile-card {
            width: min(640px, 100%);
            background: rgba(4, 15, 22, 0.82);
            border: 1px solid rgba(148, 163, 184, 0.24);
            box-shadow: 0 20px 48px rgba(2, 8, 23, 0.34);
            border-radius: 18px;
            padding: 20px;
            display: grid;
            gap: 12px;
            color: #e2e8f0;
          }
          .profile-card h2 {
            margin: 0;
            color: #f8fafc;
            font-size: 1.35rem;
          }
          .profile-card p {
            margin: 0;
            color: #cbd5e1;
            font-size: 0.95rem;
          }
          .profile-form {
            display: grid;
            gap: 10px;
            margin-top: 6px;
          }
          .profile-field {
            display: grid;
            gap: 6px;
          }
          .profile-field label {
            font-size: 0.9rem;
            color: #bae6fd;
            font-weight: 600;
          }
          .profile-field input {
            width: 100%;
            border: 1px solid rgba(148, 163, 184, 0.4);
            border-radius: 10px;
            background: rgba(15, 23, 42, 0.65);
            color: #f8fafc;
            padding: 10px 12px;
            box-sizing: border-box;
          }
          .profile-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 8px;
          }
          .profile-submit {
            border: none;
            border-radius: 10px;
            padding: 10px 14px;
            background: #0f766e;
            color: #fff;
            font-weight: 700;
            cursor: pointer;
          }
          .profile-error {
            min-height: 1.2rem;
            color: #fecaca;
            font-size: 0.9rem;
          }
          .lab-group-modal-copy {
            display: grid;
            gap: 10px;
            color: #334155;
          }
          .lab-group-modal-copy label {
            display: grid;
            gap: 6px;
            font-size: 0.9rem;
            font-weight: 600;
            color: #0f172a;
          }
          .lab-group-modal-copy input,
          .lab-group-modal-copy select {
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 9px 10px;
            font-size: 0.94rem;
          }
          @media (max-width:640px) {
            .landing-screen {
              align-items: flex-start;
              overflow-y: auto;
              padding: 12px 0;
            }
            .landing-card {
              width: calc(100% - 16px);
              border-radius: 18px;
              padding: 16px;
              margin: 0 auto;
            }
            .landing-screen.is-signin-modal .landing-card {
              width: calc(100vw - 16px);
              max-height: calc(100dvh - 16px);
              top: 8px;
              transform: translateX(-50%);
            }
            .landing-title { font-size: clamp(1.35rem, 7vw, 1.85rem); }
            .landing-subtitle { font-size: 0.92rem; line-height: 1.35; }
            .landing-form { grid-template-columns: 1fr; }
            .landing-auth-row { grid-template-columns: 1fr; }
            .landing-submit { padding: 11px 12px; }
            .event-dialog-row { grid-template-columns:1fr; }
            .profile-card { padding: 16px; }
          }

          @media (max-width:420px) {
            .landing-screen {
              padding: 8px 0;
            }
            .landing-card {
              width: calc(100% - 12px);
              border-radius: 14px;
              padding: 12px;
            }
            .landing-screen.is-signin-modal .landing-card {
              width: calc(100vw - 12px);
              max-height: calc(100dvh - 12px);
              top: 6px;
            }
            .landing-title { font-size: clamp(1.2rem, 7.2vw, 1.55rem); }
            .landing-subtitle { font-size: 0.88rem; }
            .landing-auth { margin-top: 14px; padding-top: 12px; }
            .landing-auth-block { padding: 10px; gap: 8px; }
          }
        </style>
    ''')

    # Full-page layout (sidebar + main) plus the dialog
    ui.html('''
        <div id="landing-screen" class="landing-screen">
          <div class="slime-field" aria-hidden="true">
            <canvas id="slime-canvas" class="slime-canvas"></canvas>
            <div class="slime-vein-glow"></div>
          </div>
          <section class="landing-card">
            <div class="card-sheen"></div>
            <div class="landing-content">
              <h1 class="landing-title">Lab Scheduling Dashboard</h1>
              <p class="landing-subtitle">Enter your access token to open the shared lab scheduling view.</p>
              <button id="landing-auth-close" class="landing-auth-close" type="button">Close sign-in</button>

            <div class="landing-form">
                <input id="token-input" class="landing-input" type="text" placeholder="Enter access token (for example: amber-fox-river-candle)" />
                <button id="token-submit" class="landing-submit" type="button">Open Schedule</button>
              </div>
              <p id="token-help" class="landing-help"></p>

              <div class="landing-auth">
                <div class="landing-auth-groups">
                  <section class="landing-auth-block">
                    <p class="landing-auth-title">Or Sign In:</p>
                    <div class="landing-auth-row">
                      <button id="google-login-btn" class="landing-submit landing-submit--auth" type="button">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <circle cx="12" cy="12" r="10"></circle>
                        </svg>
                        Sign in with Google
                      </button>
                      <button id="passkey-login-btn" class="landing-submit landing-submit--auth" type="button">
                        <span aria-hidden="true">&#128273;</span>
                        Login with Passkey
                      </button>
                    </div>
                    <div class="landing-auth-row-single">
                      <input id="email-login-input" class="landing-input" type="email" maxlength="254" placeholder="Email for a diceword sign-in link" />
                      <button id="email-login-btn" class="landing-submit landing-submit--auth" type="button">Send Diceword Sign-In Link</button>
                    </div>
                  </section>

                  <section id="landing-sign-up" class="landing-auth-block">
                    <p class="landing-auth-title">Sign Up:</p>
                    <div class="landing-auth-row">
                      <button id="google-signup-btn" class="landing-submit landing-submit--auth" type="button">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <circle cx="12" cy="12" r="10"></circle>
                        </svg>
                        Sign up with Google
                      </button>
                      <button id="passkey-signup-btn" class="landing-submit landing-submit--auth" type="button">
                        <span aria-hidden="true">&#128273;</span>
                        Sign up with Passkey
                      </button>
                    </div>
                    <div class="landing-auth-row-single">
                      <input id="email-signup-input" class="landing-input" type="email" maxlength="254" placeholder="Email for a sign-up link" />
                      <button id="email-signup-btn" class="landing-submit landing-submit--auth" type="button">Send Sign-Up Link</button>
                    </div>
                  </section>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div id="landing-auth-backdrop" class="landing-auth-backdrop" hidden></div>

        <div id="profile-onboarding-screen" class="profile-screen" aria-live="polite">
          <section class="profile-card">
            <h2>Complete your profile</h2>
            <p>Before continuing, please confirm your name, contact details, and lab group.</p>
            <form id="profile-onboarding-form" class="profile-form">
              <div class="profile-field">
                <label for="profile-onboarding-name">Name</label>
                <input id="profile-onboarding-name" type="text" maxlength="120" required />
              </div>
              <div class="profile-field">
                <label for="profile-onboarding-contact">Contact</label>
                <input id="profile-onboarding-contact" type="text" maxlength="254" placeholder="Email, phone, or extension" required />
              </div>
              <div class="profile-field">
                <label for="profile-onboarding-lab-group">Lab group</label>
                <input id="profile-onboarding-lab-group" list="profile-onboarding-lab-group-options" type="text" maxlength="120" placeholder="Choose or type your lab group" required />
                <datalist id="profile-onboarding-lab-group-options"></datalist>
              </div>
              <div id="profile-onboarding-error" class="profile-error"></div>
              <div class="profile-actions">
                <button id="profile-onboarding-submit" class="profile-submit" type="submit">Continue</button>
              </div>
            </form>
          </section>
        </div>

        <div id="app-shell" class="app-layout" style="display:none;">

          <!-- Left sidebar -->
          <nav class="sidebar">
            <div id="sidebar-logo" class="sidebar-logo">&#128300; Lab Scheduling</div>
            <div id="calendar-nav-item" class="sidebar-nav-item active">
              <span class="sidebar-nav-icon">&#128197;</span>
              <span>Calendars</span>
            </div>
            <div id="calendar-list"></div>
            <div class="sidebar-nav-spacer"></div>
            <div id="access-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#128272;</span>
              <span>User Settings</span>
            </div>
            <div id="upcoming-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#9200;</span>
              <span>Upcoming Bookings</span>
            </div>
            <div id="admin-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#9881;</span>
              <span>Admin</span>
            </div>
            <div id="logout-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#128682;</span>
              <span id="logout-nav-label">Logout</span>
            </div>
            <div id="share-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#128257;</span>
              <span>Share</span>
            </div>
            <div id="token-action-nav-item" class="sidebar-nav-item" style="display:none;">
              <span class="sidebar-nav-icon">&#128179;</span>
              <span id="token-action-label">Login</span>
            </div>
          </nav>

          <!-- Main area -->
          <div class="main-content">
            <div id="calendar-view" class="calendar-card">
              <div id="calendar"></div>
            </div>
            <div id="access-panel" class="access-panel" hidden>
              <section class="admin-card">
                <h2>Profile</h2>
                <p>Update your name, contact details, and lab group.</p>
                <div class="settings-profile-field">
                  <label for="settings-profile-name-input">Name</label>
                  <input id="settings-profile-name-input" class="admin-datalist-input" type="text" maxlength="120" placeholder="Name" />
                </div>
                <div class="settings-profile-field">
                  <label for="settings-profile-contact-input">Contact details</label>
                  <input id="settings-profile-contact-input" class="admin-datalist-input" type="text" maxlength="254" placeholder="Contact" />
                </div>
                <div class="settings-profile-field">
                  <label for="settings-profile-lab-group-input">Lab group</label>
                  <input id="settings-profile-lab-group-input" class="admin-datalist-input" list="settings-profile-lab-group-options" type="text" maxlength="120" placeholder="Lab group" />
                  <datalist id="settings-profile-lab-group-options"></datalist>
                </div>
                <div id="settings-profile-error" class="admin-helper" style="margin-top: 8px; color: #dc2626;"></div>
                <div class="admin-editor-row" style="grid-template-columns: 1fr auto; margin-top: 10px;">
                  <button id="settings-profile-save-button" type="button" class="admin-save-button">Save profile</button>
                </div>
              </section>
              <section class="admin-card">
                <h2>User Settings</h2>
                <p>Manage your access preferences for groups and calendars.</p>
                <div id="access-catalog-grid" class="access-catalog-grid"></div>
              </section>
              <section class="admin-card">
                <h2>Login Link</h2>
                <p>Regenerate your Diceware login string for link-based sign-in.</p>
                <div class="admin-link-meta" style="display: grid; gap: 6px; margin-top: 4px;">
                  <a id="own-login-link-anchor" href="#" target="_blank" rel="noreferrer noopener">No login URL</a>
                  <a id="own-login-link-copy" class="admin-inline-link" href="#" aria-disabled="true">Copy to clipboard</a>
                </div>
                <div class="admin-editor-row" style="grid-template-columns: 1fr auto; margin-top: 10px;">
                  <button id="regenerate-own-login-link-button" type="button" class="admin-save-button">Regenerate</button>
                </div>
              </section>
              <section class="admin-card">
                <h2>Passkeys</h2>
                <p>Create a passkey for faster and more secure sign-in on this device.</p>
                <div class="admin-editor-row" style="grid-template-columns: minmax(220px, 1fr) auto;">
                  <input id="passkey-name-input" class="admin-datalist-input" type="text" maxlength="80" placeholder="Passkey name (e.g. Work MacBook)" />
                  <button id="create-passkey-button" type="button" class="admin-save-button">Create Passkey</button>
                </div>
                <div id="passkey-list" class="admin-resource-pills" style="margin-top: 8px;"></div>
              </section>
            </div>
            <div id="upcoming-panel" class="upcoming-panel" hidden>
              <section class="admin-card">
                <h2>Upcoming Bookings</h2>
                <p>Your upcoming bookings where the booking user name matches your current profile name.</p>
                <div id="upcoming-bookings-grid" class="upcoming-bookings-list"></div>
              </section>
            </div>
            <div id="admin-panel" class="admin-panel" hidden>
              <section class="admin-card">
                <h2>Group Manager</h2>
                <p>Create groups and move resources between them.</p>
                <div id="admin-group-grid" class="admin-link-grid"></div>
              </section>
              <section class="admin-card">
                <h2>User Access Manager</h2>
                <p>Manage each user's allowed calendars. Remove individual calendars or remove a whole assigned group in one click.</p>
                <div id="admin-user-grid" class="admin-link-grid"></div>
              </section>
              <section class="admin-card">
                <h2>Access Requests</h2>
                <p>Review pending requests and hidden access rows.</p>
                <div id="admin-access-requests-grid" class="admin-link-grid"></div>
              </section>
              <section class="admin-card">
                <h2>PostgreSQL Performance Logs</h2>
                <p>Live database activity snapshot for troubleshooting slowdowns and lock contention.</p>
                <div id="admin-postgres-performance-grid" class="admin-link-grid"></div>
              </section>
            </div>
          </div>

        </div>

        <div id="save-toast" role="status" aria-live="polite">
          <div class="save-toast-icon">&#10003;</div>
          <div class="save-toast-body">
            <div class="save-toast-title" id="save-toast-title">Saved</div>
            <div class="save-toast-sub" id="save-toast-sub"></div>
          </div>
          <button class="save-toast-close" id="save-toast-close" type="button" aria-label="Close notification">&#10005;</button>
        </div>

        <div id="ws-block-overlay" class="ws-block-overlay" aria-live="assertive" role="alertdialog" aria-modal="true">
          <div class="ws-block-card">
            <h2 class="ws-block-title">Realtime Sync Lost</h2>
            <p class="ws-block-message">Connection to the update channel was lost. Inputs are temporarily locked until sync is restored.</p>
            <div id="ws-block-state" class="ws-block-state">Reconnecting...</div>
            <button class="ws-block-refresh" onclick="window.__allowManualReload()">&#8635;&nbsp;&nbsp;Refresh Page</button>
          </div>
        </div>

        <dialog id="override-block-overlay" class="ws-block-overlay" role="alertdialog" aria-modal="true" aria-hidden="true">
          <div class="ws-block-card">
            <h2 class="ws-block-title">Locked Event Override</h2>
            <p class="ws-block-message">This booking is locked because someone may be relying on it. Only alter your own locked bookings, unless you have already discussed it with the person booked or the instrument owner in charge.</p>
            <div class="override-actions">
              <button id="override-cancel" class="override-btn override-btn-cancel" type="button">Cancel</button>
              <button id="override-confirm" class="override-btn override-btn-confirm" type="button">Override</button>
            </div>
          </div>
        </dialog>

        <dialog id="calendar-editor-modal" class="calendar-editor-modal" aria-label="Calendar editor" aria-modal="true">
          <div class="calendar-editor-modal-shell">
            <div class="calendar-editor-modal-head">
              <p id="calendar-editor-modal-title" class="calendar-editor-modal-title">Calendar Editor</p>
              <button id="calendar-editor-modal-close" class="calendar-editor-modal-close" type="button">Close</button>
            </div>
            <iframe id="calendar-editor-modal-frame" class="calendar-editor-modal-frame" title="Calendar editor"></iframe>
          </div>
        </dialog>

        <!-- Event dialog (outside layout so it centres in viewport) -->
        <dialog id="event-dialog" class="event-dialog">
          <div class="event-dialog-header" id="event-dialog-title">Event</div>
          <div class="event-dialog-body">
            <div class="event-dialog-field">
              <label for="event-title">User</label>
              <input id="event-title" type="text" placeholder="User name" />
            </div>
            <div class="event-dialog-field">
              <label for="event-name">Event Name</label>
              <input id="event-name" type="text" placeholder="Event name" list="event-name-options" />
              <datalist id="event-name-options"></datalist>
            </div>
            <div class="event-dialog-field">
              <label for="event-contact">Contact</label>
              <input id="event-contact" type="text" placeholder="Contact details" />
            </div>
            <div class="event-dialog-field">
              <label>Calendars</label>
              <div id="event-calendars" class="event-calendar-list"></div>
            </div>
            <div class="event-dialog-row">
              <div class="event-dialog-field">
                <label for="event-start">Start</label>
                <input id="event-start" type="datetime-local" />
              </div>
              <div class="event-dialog-field">
                <label for="event-end">End</label>
                <input id="event-end" type="datetime-local" />
              </div>
            </div>
            <div class="event-dialog-field event-dialog-field--emphasis">
              <label><input id="event-committed" type="checkbox" /> Check this box when an experiment is underway and you are now relying on the instrument.</label>
            </div>
            <div class="event-dialog-field">
              <label><input id="event-all-day" type="checkbox" /> All day</label>
            </div>
            <div class="event-dialog-field">
              <label><input id="event-recur-enabled" type="checkbox" /> Recurring event</label>
            </div>
            <div id="event-recur-fields" class="event-dialog-row" style="display:none;">
              <div class="event-dialog-field">
                <label for="event-recur-freq">Frequency</label>
                <select id="event-recur-freq">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
              <div class="event-dialog-field">
                <label for="event-recur-interval">Interval</label>
                <input id="event-recur-interval" type="number" min="1" step="1" value="1" />
              </div>
            </div>
            <div id="event-recur-until-field" class="event-dialog-field" style="display:none;">
              <label for="event-recur-until">Repeat until (optional)</label>
              <input id="event-recur-until" type="datetime-local" />
            </div>
            <div class="event-dialog-field">
              <label for="event-notes">Notes</label>
              <textarea id="event-notes" placeholder="Add notes for this event..."></textarea>
            </div>
          </div>
          <div class="event-dialog-actions">
            <button id="event-delete" class="btn btn-danger"  type="button" style="visibility:hidden;">Delete</button>
            <div class="btn-group">
              <button id="event-cancel" class="btn btn-neutral" type="button">Cancel</button>
              <button id="event-save"   class="btn btn-primary" type="button">Save</button>
            </div>
          </div>
        </dialog>

        <dialog id="overlap-dialog" class="event-dialog">
          <div id="overlap-dialog-title" class="event-dialog-header overlap-dialog-header">Scheduling Conflict</div>
          <div class="event-dialog-body">
            <p id="overlap-dialog-message" class="overlap-dialog-message">
              This event overlaps another event on the same calendar.
            </p>
          </div>
          <div class="event-dialog-actions" style="justify-content:flex-end;">
            <button id="overlap-dialog-ok" class="btn btn-primary" type="button">OK</button>
          </div>
        </dialog>

        <dialog id="group-create-resource-dialog" class="event-dialog">
          <div id="group-create-resource-dialog-title" class="event-dialog-header overlap-dialog-header">Create Resource</div>
          <div class="event-dialog-body">
            <p id="group-create-resource-dialog-message" class="overlap-dialog-message"></p>
          </div>
          <div class="event-dialog-actions" style="justify-content:flex-end;">
            <button id="group-create-resource-dialog-cancel" class="btn btn-neutral" type="button">Cancel</button>
            <button id="group-create-resource-dialog-confirm" class="btn btn-primary" type="button">Create & Add</button>
          </div>
        </dialog>

        <dialog id="linked-removal-dialog" class="event-dialog">
          <div id="linked-removal-dialog-title" class="event-dialog-header overlap-dialog-header">Confirm Related Removal</div>
          <div class="event-dialog-body">
            <p id="linked-removal-dialog-message" class="overlap-dialog-message"></p>
          </div>
          <div class="event-dialog-actions" style="justify-content:flex-end; gap: 10px;">
            <button id="linked-removal-dialog-keep" class="btn btn-neutral" type="button">Keep</button>
            <button id="linked-removal-dialog-remove" class="btn btn-danger" type="button">Remove</button>
          </div>
        </dialog>

        <dialog id="save-account-auth-dialog" class="event-dialog">
          <div class="event-dialog-header">Save To Account</div>
          <div class="event-dialog-body">
            <p class="save-account-auth-message">Sign in to a user account to save these calendars. Choose Google OAuth or a registered passkey.</p>
          </div>
          <div class="event-dialog-actions save-account-auth-actions">
            <button id="save-account-auth-cancel" class="btn btn-neutral" type="button">Cancel</button>
            <button id="save-account-auth-passkey" class="btn btn-neutral" type="button">Sign in with Passkey</button>
            <button id="save-account-auth-google" class="btn btn-primary" type="button">Sign in with Google</button>
          </div>
        </dialog>

        <dialog id="share-links-dialog" class="event-dialog">
          <div class="event-dialog-header">Share Links</div>
          <div class="event-dialog-body">
            <div id="share-links-list" class="share-link-list"></div>
          </div>
          <div class="event-dialog-actions" style="justify-content:flex-end;">
            <button id="share-links-close" class="btn btn-neutral" type="button">Close</button>
          </div>
        </dialog>

        <dialog id="lab-group-confirm-dialog" class="event-dialog">
          <div class="event-dialog-header">Confirm Lab Group</div>
          <div class="event-dialog-body lab-group-modal-copy">
            <p id="lab-group-confirm-message">Lab group not found, please confirm spelling.</p>
            <label for="lab-group-confirm-input">Edit lab group
              <input id="lab-group-confirm-input" type="text" maxlength="120" />
            </label>
            <label for="lab-group-confirm-select">Or choose existing
              <select id="lab-group-confirm-select"></select>
            </label>
          </div>
          <div class="event-dialog-actions" style="justify-content:flex-end; gap: 10px;">
            <button id="lab-group-confirm-cancel" class="btn btn-neutral" type="button">Go back</button>
            <button id="lab-group-confirm-apply" class="btn btn-primary" type="button">Join group</button>
          </div>
        </dialog>
    ''')

    # Standalone offline guard — injected as initial page HTML, runs immediately
    # on parse (no FullCalendar or calendar-WS dependency). Also prevents
    # automatic page reloads.
    ui.add_body_html('''
<style id="page-fouc-hide">body{opacity:0!important}</style>
<script>
(function installOfflineGuard() {
  // Reveal the page cleanly — called by initializeCalendar once we know
  // what to show (landing screen or app shell). Fades in from opacity:0.
  window.__revealPage = function() {
    var s = document.getElementById('page-fouc-hide');
    if (s) s.remove();
    document.body.style.transition = 'opacity 0.12s ease';
    document.body.style.opacity = '1';
  };

  // Prevent automatic reloads (e.g., from socket.io reconnection logic).
  // Only allow manual reloads via the explicit button.
  var allowReload = false;
  var origReload = window.location.reload;
  window.location.reload = function(forceReload) {
    if (allowReload) return origReload.call(window.location, forceReload);
    // Silently ignore non-user-initiated reloads
  };
  
  // Expose a way for the refresh button to actually reload
  window.__allowManualReload = function() {
    allowReload = true;
    window.location.reload();
  };

  function setOverlay(blocked) {
    var el = document.getElementById('ws-block-overlay');
    if (!el) return;
    if (blocked) {
      el.classList.add('visible');
      el.style.display = 'flex';
      el.style.visibility = 'visible';
      el.style.opacity = '1';
      document.body.classList.add('ws-input-blocked');
    } else {
      el.classList.remove('visible');
      el.style.display = 'none';
      el.style.visibility = 'hidden';
      el.style.opacity = '0';
      document.body.classList.remove('ws-input-blocked');
    }
  }
  // Connection state is managed by the calendar-updates websocket.
  setOverlay(false);
})();
</script>
    ''')

    ui.add_body_html('''
<script>
(function initializeCalendar() {
  if (window.__labSchedulerClientInitialized) {
    return;
  }

  const mountNode = document.getElementById('calendar');
  if (!mountNode || !window.FullCalendar) {
    setTimeout(initializeCalendar, 100);
    return;
  }

  window.__labSchedulerClientInitialized = true;

  const JSON_HDR = { 'Content-Type': 'application/json' };

  // ── DOM refs ────────────────────────────────────────────────────────────
  const dialog          = document.getElementById('event-dialog');
  const dialogTitle     = document.getElementById('event-dialog-title');
  const titleInput      = document.getElementById('event-title');
  const eventNameInput  = document.getElementById('event-name');
  const eventNameOptions = document.getElementById('event-name-options');
  const contactInput    = document.getElementById('event-contact');
  const startInput      = document.getElementById('event-start');
  const endInput        = document.getElementById('event-end');
  const allDayInput     = document.getElementById('event-all-day');
  const recurEnabled    = document.getElementById('event-recur-enabled');
  const recurFields     = document.getElementById('event-recur-fields');
  const recurUntilField = document.getElementById('event-recur-until-field');
  const recurFreq       = document.getElementById('event-recur-freq');
  const recurInterval   = document.getElementById('event-recur-interval');
  const recurUntil      = document.getElementById('event-recur-until');
  const notesInput      = document.getElementById('event-notes');
  const committedInput  = document.getElementById('event-committed');
  const saveButton      = document.getElementById('event-save');
  const cancelButton    = document.getElementById('event-cancel');
  const deleteButton    = document.getElementById('event-delete');
  const calendarList    = document.getElementById('calendar-list');
  const sidebarLogo     = document.getElementById('sidebar-logo');
  const calendarNavItem = document.getElementById('calendar-nav-item');
  const accessNavItem   = document.getElementById('access-nav-item');
  const upcomingNavItem = document.getElementById('upcoming-nav-item');
  const adminNavItem    = document.getElementById('admin-nav-item');
  const logoutNavItem   = document.getElementById('logout-nav-item');
  const shareNavItem    = document.getElementById('share-nav-item');
  const tokenActionNavItem = document.getElementById('token-action-nav-item');
  const calendarView    = document.getElementById('calendar-view');
  const accessPanel     = document.getElementById('access-panel');
  const upcomingPanel   = document.getElementById('upcoming-panel');
  const adminPanel      = document.getElementById('admin-panel');
  const adminGroupGrid   = document.getElementById('admin-group-grid');
  const adminUserGrid   = document.getElementById('admin-user-grid');
  const adminAccessRequestsGrid = document.getElementById('admin-access-requests-grid');
  const adminPostgresPerformanceGrid = document.getElementById('admin-postgres-performance-grid');
  const accessCatalogGrid = document.getElementById('access-catalog-grid');
  const upcomingBookingsGrid = document.getElementById('upcoming-bookings-grid');
  const settingsProfileNameInput = document.getElementById('settings-profile-name-input');
  const settingsProfileContactInput = document.getElementById('settings-profile-contact-input');
  const settingsProfileLabGroupInput = document.getElementById('settings-profile-lab-group-input');
  const settingsProfileLabGroupOptions = document.getElementById('settings-profile-lab-group-options');
  const settingsProfileError = document.getElementById('settings-profile-error');
  const settingsProfileSaveButton = document.getElementById('settings-profile-save-button');
  const ownLoginLinkAnchor = document.getElementById('own-login-link-anchor');
  const ownLoginLinkCopy = document.getElementById('own-login-link-copy');
  const regenerateOwnLoginLinkButton = document.getElementById('regenerate-own-login-link-button');
  const passkeyNameInput = document.getElementById('passkey-name-input');
  const createPasskeyButton = document.getElementById('create-passkey-button');
  const passkeyList = document.getElementById('passkey-list');
  const eventCalendars  = document.getElementById('event-calendars');
  const appShell        = document.getElementById('app-shell');
  const landingScreen   = document.getElementById('landing-screen');
  const landingAuthBackdrop = document.getElementById('landing-auth-backdrop');
  const profileOnboardingScreen = document.getElementById('profile-onboarding-screen');
  const profileOnboardingForm = document.getElementById('profile-onboarding-form');
  const profileOnboardingName = document.getElementById('profile-onboarding-name');
  const profileOnboardingContact = document.getElementById('profile-onboarding-contact');
  const profileOnboardingLabGroup = document.getElementById('profile-onboarding-lab-group');
  const profileOnboardingLabGroupOptions = document.getElementById('profile-onboarding-lab-group-options');
  const profileOnboardingError = document.getElementById('profile-onboarding-error');
  const profileOnboardingSubmit = document.getElementById('profile-onboarding-submit');
  const tokenInput      = document.getElementById('token-input');
  const tokenSubmit     = document.getElementById('token-submit');
  const tokenHelp       = document.getElementById('token-help');
  const wsStatusPanel   = document.getElementById('ws-status');
  const wsIndicator     = document.getElementById('ws-indicator');
  const wsConnState     = document.getElementById('ws-connection-state');
  const wsLastChange    = document.getElementById('ws-last-change');
  const logoutNavLabel  = document.getElementById('logout-nav-label');
  const tokenActionLabel = document.getElementById('token-action-label');
  const saveToast      = document.getElementById('save-toast');
  const saveToastTitle = document.getElementById('save-toast-title');
  const saveToastSub   = document.getElementById('save-toast-sub');
  const saveToastClose = document.getElementById('save-toast-close');
  const landingAuthCloseButton = document.getElementById('landing-auth-close');
  let   saveToastTimer = null;
  const wsBlockOverlay  = document.getElementById('ws-block-overlay');
  const wsBlockState    = document.getElementById('ws-block-state');
  const overrideBlockOverlay = document.getElementById('override-block-overlay');
  const overrideCancelButton = document.getElementById('override-cancel');
  const overrideConfirmButton = document.getElementById('override-confirm');
  const calendarEditorModal = document.getElementById('calendar-editor-modal');
  const calendarEditorModalTitle = document.getElementById('calendar-editor-modal-title');
  const calendarEditorModalClose = document.getElementById('calendar-editor-modal-close');
  const calendarEditorModalFrame = document.getElementById('calendar-editor-modal-frame');
  const overlapDialog   = document.getElementById('overlap-dialog');
  const overlapTitle    = document.getElementById('overlap-dialog-title');
  const overlapMessage  = document.getElementById('overlap-dialog-message');
  const overlapOkButton = document.getElementById('overlap-dialog-ok');
  const groupCreateResourceDialog = document.getElementById('group-create-resource-dialog');
  const groupCreateResourceTitle = document.getElementById('group-create-resource-dialog-title');
  const groupCreateResourceMessage = document.getElementById('group-create-resource-dialog-message');
  const groupCreateResourceCancel = document.getElementById('group-create-resource-dialog-cancel');
  const groupCreateResourceConfirm = document.getElementById('group-create-resource-dialog-confirm');
  const linkedRemovalDialog = document.getElementById('linked-removal-dialog');
  const linkedRemovalTitle = document.getElementById('linked-removal-dialog-title');
  const linkedRemovalMessage = document.getElementById('linked-removal-dialog-message');
  const linkedRemovalKeep = document.getElementById('linked-removal-dialog-keep');
  const linkedRemovalRemove = document.getElementById('linked-removal-dialog-remove');
  const saveAccountAuthDialog = document.getElementById('save-account-auth-dialog');
  const saveAccountAuthCancel = document.getElementById('save-account-auth-cancel');
  const saveAccountAuthPasskey = document.getElementById('save-account-auth-passkey');
  const saveAccountAuthGoogle = document.getElementById('save-account-auth-google');
  const shareLinksDialog = document.getElementById('share-links-dialog');
  const shareLinksList = document.getElementById('share-links-list');
  const shareLinksClose = document.getElementById('share-links-close');
  const labGroupConfirmDialog = document.getElementById('lab-group-confirm-dialog');
  const labGroupConfirmMessage = document.getElementById('lab-group-confirm-message');
  const labGroupConfirmInput = document.getElementById('lab-group-confirm-input');
  const labGroupConfirmSelect = document.getElementById('lab-group-confirm-select');
  const labGroupConfirmCancel = document.getElementById('lab-group-confirm-cancel');
  const labGroupConfirmApply = document.getElementById('lab-group-confirm-apply');
  const eventNotesTooltip = document.createElement('div');
  eventNotesTooltip.className = 'event-notes-tooltip';
  document.body.appendChild(eventNotesTooltip);
  const calendarHoverTooltip = document.createElement('div');
  calendarHoverTooltip.className = 'calendar-hover-tooltip';
  document.body.appendChild(calendarHoverTooltip);

  // ── State ────────────────────────────────────────────────────────────────
  const dialogState   = { mode: 'create', eventId: null };
  let   allCalendars  = [];
  let   currentUser   = null;
  let   adminUsersData = null;
  let   adminPerformanceData = null;
  let   accessCatalogData = null;
  let   upcomingBookingsData = null;
  let   userPasskeys = [];
  let   shareLinksData = [];
  let   currentView   = 'calendar';
  let   hiddenCals    = new Set();   // ids of deselected calendars
  let   currentToken  = null;        // token from URL for API requests
  let   sharedLinkToken = null;      // original non-JWT link token, if any
  let   authenticatedSessionToken = null; // session cookie token for the logged-in user
  let   tokenAllowedCalendars = null; // calendars accessible via token
  let   tokenAccessRequested = false; // true when the current page was opened via a token URL
  let   hasValidToken = false;
  let   knownLabGroups = [];
  let   pendingProfileContinue = null;
  let   pendingLabGroupResolve = null;
  let   dialogLoadedEvents = [];
  let   dialogSuggestionEvents = [];
  let   dialogAvailabilityRequestId = 0;
  let   dialogAvailabilityRefreshTimer = null;
  let   dialogSuggestionRequestId = 0;
  let   dialogSuggestionRefreshTimer = null;
  let   dialogInitialState = null;
  let   activeCalendarHoverButton = null;
  let   slimeSimulationStarted = false;
  let   updatesSocket = null;
  let   updatesReconnectTimer = null;
  let   updatesReconnectDelay = 500;
  let   updatesHeartbeatTimer = null;
  let   updatesHeartbeatTimeoutTimer = null;
  let   updatesLastPongAt = 0;
  let   updatesRefreshInFlight = false;
  let   updatesRefreshQueued = false;
  let   updatesConnectionState = 'connecting';
  let   lastCalendarChangeAt = null;
  let   wsInputBlocked = false;
  const recentLocalChangeIds = new Map();
  const CLIENT_INSTANCE_ID = (window.crypto && window.crypto.randomUUID)
    ? window.crypto.randomUUID()
    : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  function setPersistedAuthToken(token) {
    return;
  }

  function getPersistedAuthToken() {
    return null;
  }

  function clearPersistedAuthToken() {
    return;
  }

  function setPreservedLinkToken(token) {
    return;
  }

  function getPreservedLinkToken() {
    return null;
  }

  function clearPreservedLinkToken() {
    return;
  }

  function formatDuration(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    if (totalSeconds < 60) return `${totalSeconds}s ago`;
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes < 60) return `${minutes}m ${seconds}s ago`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m ago`;
  }

  function newChangeId() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return `chg-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function isJwtToken(token) {
    if (!token || typeof token !== 'string') return false;
    return token.split('.').length === 3;
  }

  function showSaveToast(title, sub, isError, host = document.body) {
    if (!saveToast) return;
    if (host && saveToast.parentElement !== host) {
      host.appendChild(saveToast);
    } else if (!host && saveToast.parentElement !== document.body) {
      document.body.appendChild(saveToast);
    }
    saveToastTitle.textContent = title || 'Saved';
    saveToastSub.textContent   = sub   || '';
    const toastIcon = saveToast.querySelector('.save-toast-icon');
    if (isError) {
      saveToast.classList.add('save-toast--error');
      if (toastIcon) toastIcon.textContent = '\u2715';
    } else {
      saveToast.classList.remove('save-toast--error');
      if (toastIcon) toastIcon.textContent = '\u2713';
    }
    saveToast.classList.add('visible');
    if (saveToastTimer) clearTimeout(saveToastTimer);
    saveToastTimer = setTimeout(() => {
      saveToast.classList.remove('visible');
      saveToastTimer = null;
    }, 10000);
  }

  function showErrorToast(title, sub, host = document.body) {
    showSaveToast(title || 'Error', sub || '', true, host);
  }

  function openCalendarEditorModal(calendarId, calendarLabel) {
    const normalizedId = String(calendarId || '').trim();
    if (!normalizedId) {
      return;
    }
    if (!calendarEditorModal || !calendarEditorModalFrame || !calendarEditorModalTitle) {
      window.location.href = `/calendar-edit/${encodeURIComponent(normalizedId)}`;
      return;
    }
    const titleLabel = String(calendarLabel || '').trim() || normalizedId;
    calendarEditorModalTitle.textContent = `Calendar Editor: ${titleLabel}`;
    calendarEditorModalFrame.src = `/calendar-edit/${encodeURIComponent(normalizedId)}`;
    if (!calendarEditorModal.open) {
      calendarEditorModal.showModal();
    }
  }

  function closeCalendarEditorModal() {
    if (!calendarEditorModal) return;
    if (calendarEditorModal.open) {
      calendarEditorModal.close();
    }
    if (calendarEditorModalFrame) {
      calendarEditorModalFrame.src = 'about:blank';
    }
    if (isAdminUser()) {
      loadAdminData().catch((error) => {
        console.warn('Unable to refresh admin data after closing calendar editor:', error);
      });
    }
  }

  if (calendarEditorModalClose) {
    calendarEditorModalClose.addEventListener('click', closeCalendarEditorModal);
  }
  if (calendarEditorModal) {
    calendarEditorModal.addEventListener('click', (event) => {
      if (event.target === calendarEditorModal) {
        closeCalendarEditorModal();
      }
    });
    calendarEditorModal.addEventListener('cancel', () => {
      closeCalendarEditorModal();
    });
  }

  if (saveToastClose) {
    saveToastClose.addEventListener('click', () => {
      if (saveToastTimer) clearTimeout(saveToastTimer);
      saveToast.classList.remove('visible');
      saveToastTimer = null;
    });
  }

  function registerLocalChangeId(changeId) {
    const expiresAt = Date.now() + 15000;
    recentLocalChangeIds.set(changeId, expiresAt);
  }

  function hasRecentLocalChangeId(changeId) {
    const now = Date.now();
    for (const [id, expiry] of recentLocalChangeIds.entries()) {
      if (expiry <= now) recentLocalChangeIds.delete(id);
    }
    const expiry = recentLocalChangeIds.get(changeId);
    return Boolean(expiry && expiry > now);
  }

  function setInputBlocked(blocked) {
    wsInputBlocked = blocked;

    if (blocked && document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }

    if (blocked && dialog && dialog.open) {
      dialog.close();
    }

    document.body.classList.toggle('ws-input-blocked', blocked);
    if (wsBlockOverlay) {
      wsBlockOverlay.classList.toggle('visible', blocked);
      wsBlockOverlay.style.display = blocked ? 'flex' : 'none';
      wsBlockOverlay.style.visibility = blocked ? 'visible' : 'hidden';
      wsBlockOverlay.style.opacity = blocked ? '1' : '0';
      wsBlockOverlay.setAttribute('aria-hidden', blocked ? 'false' : 'true');
    }
  }

  function requestCommittedOverride() {
    return new Promise(resolve => {
      if (!overrideBlockOverlay || !overrideCancelButton || !overrideConfirmButton) {
        resolve(window.confirm('This booking is locked because someone may be relying on it. Only alter your own locked bookings, unless you have already discussed it with the person booked or the instrument owner in charge.'));
        return;
      }

      const cleanup = () => {
        overrideBlockOverlay.classList.remove('visible');
        if (overrideBlockOverlay.open) {
          overrideBlockOverlay.close();
        }
        overrideBlockOverlay.setAttribute('aria-hidden', 'true');
        overrideCancelButton.removeEventListener('click', onCancel);
        overrideConfirmButton.removeEventListener('click', onConfirm);
      };

      const onCancel = () => {
        cleanup();
        resolve(false);
      };
      const onConfirm = () => {
        cleanup();
        resolve(true);
      };

      overrideCancelButton.addEventListener('click', onCancel);
      overrideConfirmButton.addEventListener('click', onConfirm);
      overrideBlockOverlay.classList.add('visible');
      if (!overrideBlockOverlay.open) {
        overrideBlockOverlay.showModal();
      }
      overrideBlockOverlay.setAttribute('aria-hidden', 'false');
      overrideCancelButton.focus();
    });
  }

  async function confirmCommittedEditIfNeeded(isDirty) {
    if (dialogState.mode !== 'edit' || !dialogInitialState?.committed || !isDirty) {
      return true;
    }

    return requestCommittedOverride();
  }

  function captureDialogState() {
    return {
      title: titleInput.value.trim(),
      eventName: eventNameInput.value.trim(),
      contact: contactInput.value.trim(),
      start: startInput.value,
      end: endInput.value,
      allDay: Boolean(allDayInput.checked),
      calendarIds: getSelectedCalendarIds().slice().sort(),
      recurrenceEnabled: Boolean(recurEnabled.checked),
      recurrenceFreq: recurEnabled.checked ? String(recurFreq.value || 'daily') : '',
      recurrenceInterval: recurEnabled.checked ? String(recurInterval.value || '1') : '',
      recurrenceUntil: recurEnabled.checked ? String(recurUntil.value || '') : '',
      notes: notesInput.value.trim(),
      committed: Boolean(committedInput.checked),
    };
  }

  function dialogStateChangedSinceOpen() {
    if (!dialogInitialState) {
      return false;
    }

    const currentState = captureDialogState();
    return JSON.stringify(currentState) !== JSON.stringify(dialogInitialState);
  }

  function blockInputIfNeeded(event) {
    if (!wsInputBlocked) return;
    if (wsBlockOverlay && wsBlockOverlay.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
  }

  document.addEventListener('keydown', blockInputIfNeeded, true);
  document.addEventListener('keypress', blockInputIfNeeded, true);
  document.addEventListener('mousedown', blockInputIfNeeded, true);
  document.addEventListener('touchstart', blockInputIfNeeded, true);

  function renderWsStatus() {
    if (wsConnState) {
      wsConnState.textContent = `WebSocket: ${updatesConnectionState}`;
    }
    if (wsIndicator) {
      wsIndicator.classList.remove('connected', 'disconnected', 'error');
      if (updatesConnectionState === 'connected') wsIndicator.classList.add('connected');
      else if (updatesConnectionState === 'error') wsIndicator.classList.add('error');
      else if (updatesConnectionState === 'disconnected') wsIndicator.classList.add('disconnected');
    }

    if (wsLastChange) {
      if (!lastCalendarChangeAt) {
        wsLastChange.textContent = 'Last change received: never';
      } else {
        wsLastChange.textContent = `Last change received: ${formatDuration(Date.now() - lastCalendarChangeAt)}`;
      }
    }

    // Show overlay based on the single calendar-updates websocket.
    const calConnected = updatesConnectionState === 'connected';
    const fullyConnected = calConnected;
    const appSessionActive = hasValidToken && appShell && appShell.style.display !== 'none';
    setInputBlocked(appSessionActive && !fullyConnected);
    if (wsBlockState) {
      if (!appSessionActive) {
        wsBlockState.textContent = 'Sync status: idle';
      } else if (fullyConnected) {
        wsBlockState.textContent = 'Connected';
      } else {
        wsBlockState.textContent = `Sync status: ${updatesConnectionState} — reconnecting…`;
      }
    }
  }

  function clearHeartbeatTimers() {
    if (updatesHeartbeatTimer) {
      window.clearInterval(updatesHeartbeatTimer);
      updatesHeartbeatTimer = null;
    }
    if (updatesHeartbeatTimeoutTimer) {
      window.clearTimeout(updatesHeartbeatTimeoutTimer);
      updatesHeartbeatTimeoutTimer = null;
    }
  }

  function startHeartbeat(socket) {
    clearHeartbeatTimers();
    updatesLastPongAt = Date.now();

    updatesHeartbeatTimer = window.setInterval(() => {
      if (updatesSocket !== socket || socket.readyState !== WebSocket.OPEN) {
        clearHeartbeatTimers();
        return;
      }

      try {
        socket.send('ping');
      } catch {
        try {
          socket.close();
        } catch {
          // ignore
        }
        return;
      }

      if (updatesHeartbeatTimeoutTimer) {
        window.clearTimeout(updatesHeartbeatTimeoutTimer);
      }
      updatesHeartbeatTimeoutTimer = window.setTimeout(() => {
        if (updatesSocket !== socket || socket.readyState !== WebSocket.OPEN) return;
        const staleForMs = Date.now() - updatesLastPongAt;
        if (staleForMs >= 9000) {
          updatesConnectionState = 'disconnected';
          renderWsStatus();
          try {
            socket.close();
          } catch {
            // ignore
          }
        }
      }, 9000);
    }, 4000);
  }

  window.setInterval(renderWsStatus, 1000);
  renderWsStatus();

  // ── Disable NiceGUI socket.io transport for this page ─────────────────────
  // The app uses /ws/calendar-updates as its single realtime channel.
  (function disableNiceGuiSocket() {
    const sock = window.socket;
    if (!sock) {
      window.setTimeout(disableNiceGuiSocket, 150);
      return;
    }
    try {
      if (typeof sock.removeAllListeners === 'function') {
        sock.removeAllListeners('disconnect');
        sock.removeAllListeners('connect');
        sock.removeAllListeners('reconnect');
        sock.removeAllListeners('reconnect_failed');
        sock.removeAllListeners('reconnect_error');
        sock.removeAllListeners('error');
      }
      if (typeof sock.disconnect === 'function') {
        sock.disconnect();
      }
    } catch {
      // ignore
    }
  })();
  (function extractTokenFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const keys = ['link', 'links', 'token', 'tokens'];
    for (const key of keys) {
      for (const value of params.getAll(key)) {
        for (const token of value.split(',')) {
          const normalized = token.trim();
          if (normalized) {
            currentToken = normalized;
            tokenAccessRequested = !isJwtToken(normalized);
            if (tokenAccessRequested) {
              sharedLinkToken = normalized;
            }
            return;
          }
        }
      }
    }
  })();

  // ── Utilities ────────────────────────────────────────────────────────────
  function isoToLocalInput(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  function localToIso(v) { return v ? new Date(v).toISOString() : null; }

  function splitEventTitle(value) {
    const raw = String(value || '');
    const parts = raw.split(' :: ');
    if (parts.length < 2) {
      return { user: raw, eventName: '' };
    }
    return {
      user: parts[0].trim(),
      eventName: parts.slice(1).join(' :: ').trim(),
    };
  }

  function combineEventTitle(user, eventName) {
    const normalizedUser = String(user || '').trim();
    const normalizedEventName = String(eventName || '').trim();
    if (!normalizedEventName) return normalizedUser;
    if (!normalizedUser) return normalizedEventName;
    return `${normalizedUser} :: ${normalizedEventName}`;
  }

  function startSlimeSimulation() {
    if (slimeSimulationStarted || !landingScreen) return;
    const canvas = document.getElementById('slime-canvas');
    if (!(canvas instanceof HTMLCanvasElement)) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    slimeSimulationStarted = true;

    let viewportWidth = 1;
    let viewportHeight = 1;
    let simW = 1;
    let simH = 1;
    let field = new Float32Array(1);
    let scratch = new Float32Array(1);
    let agents = [];
    let imageData = null;
    let imageBytes = null;
    let bufferCanvas = null;
    let bufferCtx = null;

    const SIM_SCALE = 0.36;
    const SENSOR_DIST = 9;
    const SENSOR_ANGLE = 0.58;
    const TURN_RATE = 0.16;
    const JITTER = 0.16;
    const BASE_SPEED = 1.1;
    const DEPOSIT = 2.4;
    const DECAY = 0.035;

    function wrapX(x) {
      return x < 0 ? x + simW : (x >= simW ? x - simW : x);
    }

    function wrapY(y) {
      return y < 0 ? y + simH : (y >= simH ? y - simH : y);
    }

    function sampleField(x, y) {
      const ix = Math.floor(wrapX(x));
      const iy = Math.floor(wrapY(y));
      return field[iy * simW + ix];
    }

    function initSimulation() {
      viewportWidth = Math.max(1, Math.floor(window.innerWidth));
      viewportHeight = Math.max(1, Math.floor(window.innerHeight));
      canvas.width = viewportWidth;
      canvas.height = viewportHeight;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      ctx.imageSmoothingEnabled = true;

      simW = Math.max(180, Math.floor(viewportWidth * SIM_SCALE));
      simH = Math.max(110, Math.floor(viewportHeight * SIM_SCALE));

      field = new Float32Array(simW * simH);
      scratch = new Float32Array(simW * simH);
      imageData = ctx.createImageData(simW, simH);
      imageBytes = imageData.data;
      bufferCanvas = document.createElement('canvas');
      bufferCanvas.width = simW;
      bufferCanvas.height = simH;
      bufferCtx = bufferCanvas.getContext('2d', { alpha: true });
      if (bufferCtx) bufferCtx.imageSmoothingEnabled = true;

      const agentCount = Math.floor(simW * simH * 0.028);
      agents = [];
      for (let i = 0; i < agentCount; i += 1) {
        agents.push({
          x: Math.random() * simW,
          y: Math.random() * simH,
          angle: Math.random() * Math.PI * 2,
          speed: BASE_SPEED + Math.random() * 0.9,
        });
      }
    }

    function stepAgents() {
      for (const agent of agents) {
        const f = sampleField(
          agent.x + Math.cos(agent.angle) * SENSOR_DIST,
          agent.y + Math.sin(agent.angle) * SENSOR_DIST,
        );
        const l = sampleField(
          agent.x + Math.cos(agent.angle - SENSOR_ANGLE) * SENSOR_DIST,
          agent.y + Math.sin(agent.angle - SENSOR_ANGLE) * SENSOR_DIST,
        );
        const r = sampleField(
          agent.x + Math.cos(agent.angle + SENSOR_ANGLE) * SENSOR_DIST,
          agent.y + Math.sin(agent.angle + SENSOR_ANGLE) * SENSOR_DIST,
        );

        if (f < l && f < r) {
          agent.angle += (Math.random() < 0.5 ? -1 : 1) * TURN_RATE;
        } else if (l > r) {
          agent.angle -= TURN_RATE;
        } else if (r > l) {
          agent.angle += TURN_RATE;
        }
        agent.angle += (Math.random() - 0.5) * JITTER;

        agent.x = wrapX(agent.x + Math.cos(agent.angle) * agent.speed);
        agent.y = wrapY(agent.y + Math.sin(agent.angle) * agent.speed);

        const idx = Math.floor(agent.y) * simW + Math.floor(agent.x);
        field[idx] = Math.min(14, field[idx] + DEPOSIT);
      }
    }

    function diffuseAndDecay() {
      for (let y = 1; y < simH - 1; y += 1) {
        const row = y * simW;
        for (let x = 1; x < simW - 1; x += 1) {
          const idx = row + x;
          const val = (
            field[idx] * 0.25 +
            field[idx - 1] * 0.14 +
            field[idx + 1] * 0.14 +
            field[idx - simW] * 0.14 +
            field[idx + simW] * 0.14 +
            field[idx - simW - 1] * 0.047 +
            field[idx - simW + 1] * 0.047 +
            field[idx + simW - 1] * 0.047 +
            field[idx + simW + 1] * 0.047
          );
          scratch[idx] = Math.max(0, val - DECAY);
        }
      }

      const tmp = field;
      field = scratch;
      scratch = tmp;
    }

    function renderField() {
      for (let i = 0; i < field.length; i += 1) {
        const lum = Math.min(255, field[i] * 32);
        const px = i * 4;
        imageBytes[px] = 5 + lum * 0.08;
        imageBytes[px + 1] = 28 + lum * 0.7;
        imageBytes[px + 2] = 24 + lum * 0.55;
        imageBytes[px + 3] = Math.min(255, lum * 1.22);
      }
      if (!bufferCtx || !bufferCanvas) return;
      bufferCtx.putImageData(imageData, 0, 0);
      ctx.fillStyle = 'rgba(4, 47, 46, 0.18)';
      ctx.clearRect(0, 0, viewportWidth, viewportHeight);
      ctx.fillRect(0, 0, viewportWidth, viewportHeight);
      ctx.drawImage(bufferCanvas, 0, 0, simW, simH, 0, 0, viewportWidth, viewportHeight);
    }

    function animate() {
      if (landingScreen.style.display !== 'none') {
        stepAgents();
        diffuseAndDecay();
        renderField();
      }
      requestAnimationFrame(animate);
    }

    initSimulation();
    window.addEventListener('resize', initSimulation);
    requestAnimationFrame(animate);
  }

  const API_WARN_MS = 1500;
  const API_TIMEOUT_MS = 12000;

  async function request(path, method = 'GET', body = null, includeToken = true) {
    let token = null;
    if (includeToken) {
      token = currentToken;
    }
    const buildFullPath = (candidateToken) => {
      const separator = path.includes('?') ? '&' : '?';
      return candidateToken ? `${path}${separator}token=${encodeURIComponent(candidateToken)}` : path;
    };
    const fullPath = buildFullPath(token);
    
    const changeId = newChangeId();
    const opts = {
      method,
      credentials: 'include',
      headers: {
        ...JSON_HDR,
        'X-Client-Id': CLIENT_INSTANCE_ID,
        'X-Change-Id': changeId,
      },
    };
    if (body !== null) opts.body = JSON.stringify(body);
    if (method !== 'GET') {
      registerLocalChangeId(changeId);
    }

    const startedAt = performance.now();
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    opts.signal = controller.signal;

    let res;
    try {
      res = await fetch(fullPath, opts);
    } catch (error) {
      const elapsed = Math.round(performance.now() - startedAt);
      if (error && error.name === 'AbortError') {
        console.error(`[API timeout] ${method} ${fullPath} exceeded ${API_TIMEOUT_MS}ms`);
        throw new Error('Request timed out. Please retry.');
      }
      console.error(`[API network error] ${method} ${fullPath} after ${elapsed}ms`, error);
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }

    const elapsed = Math.round(performance.now() - startedAt);
    if (elapsed >= API_WARN_MS) {
      console.warn(`[API slow] ${method} ${fullPath} took ${elapsed}ms`);
    }

    if (!res.ok) {
      const p = await res.json().catch(() => ({ detail: 'Request failed' }));
      const detail = String(p.detail || 'Request failed');
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }

  function normalizeGroupName(value) {
    return String(value || '').trim().toLowerCase();
  }

  function setKnownLabGroups(values) {
    const nextValues = Array.isArray(values)
      ? values
        .map(value => String(value || '').trim())
        .filter(Boolean)
      : [];
    knownLabGroups = Array.from(new Set(nextValues)).sort((left, right) => left.localeCompare(right));
    if (profileOnboardingLabGroupOptions) {
      profileOnboardingLabGroupOptions.innerHTML = '';
      for (const groupName of knownLabGroups) {
        const option = document.createElement('option');
        option.value = groupName;
        profileOnboardingLabGroupOptions.appendChild(option);
      }
    }
    if (settingsProfileLabGroupOptions) {
      settingsProfileLabGroupOptions.innerHTML = '';
      for (const groupName of knownLabGroups) {
        const option = document.createElement('option');
        option.value = groupName;
        settingsProfileLabGroupOptions.appendChild(option);
      }
    }
  }

  async function promptForNewLabGroup(initialValue) {
    const normalizedInitial = String(initialValue || '').trim();
    if (!normalizedInitial) {
      return '';
    }
    if (!labGroupConfirmDialog || !labGroupConfirmInput || !labGroupConfirmSelect || !labGroupConfirmApply) {
      return normalizedInitial;
    }

    const updateLabGroupConfirmState = () => {
      const editedValue = String(labGroupConfirmInput?.value || '').trim();
      const selectedValue = String(labGroupConfirmSelect?.value || '').trim();
      const resolvedValue = selectedValue || editedValue;
      const labelValue = resolvedValue || normalizedInitial;
      labGroupConfirmApply.textContent = `Join group ${labelValue}`;
      labGroupConfirmApply.disabled = !resolvedValue;
      if (labGroupConfirmMessage) {
        labGroupConfirmMessage.textContent = 'Lab group not found, please confirm spelling.';
      }
    };

    labGroupConfirmInput.value = normalizedInitial;
    labGroupConfirmSelect.innerHTML = '<option value="">Use typed group name</option>';
    for (const groupName of knownLabGroups) {
      const option = document.createElement('option');
      option.value = groupName;
      option.textContent = groupName;
      labGroupConfirmSelect.appendChild(option);
    }

    labGroupConfirmInput.oninput = updateLabGroupConfirmState;
    labGroupConfirmSelect.onchange = updateLabGroupConfirmState;
    updateLabGroupConfirmState();

    return new Promise((resolve) => {
      pendingLabGroupResolve = resolve;
      labGroupConfirmDialog.showModal();
    });
  }

  async function maybeRequireProfileOnboarding(onContinue) {
    let profile;
    try {
      profile = await request('/api/users/me/profile', 'GET', null, true);
    } catch (error) {
      console.warn('Failed to fetch user profile status:', error);
      return false;
    }

    setKnownLabGroups(profile?.labGroups || []);
    if (!profile?.needsProfile) {
      return false;
    }

    pendingProfileContinue = onContinue;
    if (profileOnboardingError) {
      profileOnboardingError.textContent = '';
    }
    if (profileOnboardingName) {
      profileOnboardingName.value = String(profile?.user?.name || currentUser?.name || '').trim();
    }
    if (profileOnboardingContact) {
      profileOnboardingContact.value = String(profile?.user?.contact || currentUser?.contact || '').trim();
    }
    if (profileOnboardingLabGroup) {
      profileOnboardingLabGroup.value = String(profile?.user?.labGroup || currentUser?.labGroup || '').trim();
    }

    landingScreen.style.display = 'none';
    appShell.style.display = 'none';
    if (profileOnboardingScreen) {
      profileOnboardingScreen.style.display = 'flex';
    }
    return true;
  }

  async function saveProfileWithLabGroupConfirm({ name, contact, labGroup }) {
    const normalizedName = String(name || '').trim();
    const normalizedContact = String(contact || '').trim();
    let normalizedLabGroup = String(labGroup || '').trim();
    if (!normalizedName || !normalizedContact || !normalizedLabGroup) {
      throw new Error('Name, contact, and lab group are required.');
    }

    const knownByNormalized = new Map(knownLabGroups.map(value => [normalizeGroupName(value), value]));
    const knownGroupValue = knownByNormalized.get(normalizeGroupName(normalizedLabGroup));
    if (knownGroupValue) {
      normalizedLabGroup = knownGroupValue;
    } else {
      const resolved = await promptForNewLabGroup(normalizedLabGroup);
      const resolvedValue = String(resolved || '').trim();
      if (!resolvedValue) {
        throw new Error('Please choose or enter a lab group.');
      }
      const existingResolved = knownByNormalized.get(normalizeGroupName(resolvedValue));
      normalizedLabGroup = existingResolved || resolvedValue;
    }

    const result = await request('/api/users/me/profile', 'PUT', {
      name: normalizedName,
      contact: normalizedContact,
      labGroup: normalizedLabGroup,
    }, true);
    setKnownLabGroups(result?.labGroups || []);

    const updatedUser = result?.user || {};
    currentUser = {
      ...(currentUser || {}),
      name: String(updatedUser.name || normalizedName),
      contact: String(updatedUser.contact || normalizedContact),
      labGroup: String(updatedUser.labGroup || normalizedLabGroup),
      profileComplete: true,
    };

    return {
      result,
      name: normalizedName,
      contact: normalizedContact,
      labGroup: normalizedLabGroup,
    };
  }

  async function loadUserProfileSettings() {
    const profile = await request('/api/users/me/profile', 'GET', null, true);
    setKnownLabGroups(profile?.labGroups || []);
    if (settingsProfileNameInput) {
      settingsProfileNameInput.value = String(profile?.user?.name || currentUser?.name || '').trim();
    }
    if (settingsProfileContactInput) {
      settingsProfileContactInput.value = String(profile?.user?.contact || currentUser?.contact || '').trim();
    }
    if (settingsProfileLabGroupInput) {
      settingsProfileLabGroupInput.value = String(profile?.user?.labGroup || currentUser?.labGroup || '').trim();
    }
  }

  async function refreshFromRemoteUpdate() {
    if (!hasValidToken || !currentToken) return;
    if (updatesRefreshInFlight) {
      updatesRefreshQueued = true;
      return;
    }

    updatesRefreshInFlight = true;
    try {
      const [cals, accessCatalog] = await Promise.all([
        request('/api/calendars'),
        request('/api/access/catalog'),
      ]);
      allCalendars = cals;
      accessCatalogData = accessCatalog;
      tokenAllowedCalendars = new Set((cals || []).map(cal => cal.id));
      renderSidebar();
      renderAccessCatalog();
      if (currentView === 'upcoming') {
        void loadUpcomingBookings();
      }
      if (fcCalendar) {
        fcCalendar.refetchEvents();
      }
    } catch (err) {
      console.warn('Remote calendar refresh failed:', err);
    } finally {
      updatesRefreshInFlight = false;
      if (updatesRefreshQueued) {
        updatesRefreshQueued = false;
        refreshFromRemoteUpdate();
      }
    }
  }

  function connectCalendarUpdatesSocket() {
    if (!hasValidToken || !currentToken) {
      return;
    }
    if (updatesSocket && (
      updatesSocket.readyState === WebSocket.OPEN ||
      updatesSocket.readyState === WebSocket.CONNECTING
    )) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/calendar-updates`;
    const socket = new WebSocket(wsUrl);
    updatesSocket = socket;
    updatesConnectionState = 'connecting';
    renderWsStatus();

    socket.onopen = () => {
      updatesReconnectDelay = 500;
      updatesConnectionState = 'connected';
      renderWsStatus();
      startHeartbeat(socket);
      if (updatesReconnectTimer) {
        window.clearTimeout(updatesReconnectTimer);
        updatesReconnectTimer = null;
      }
    };

    socket.onmessage = event => {
      if (event.data === 'pong') {
        updatesLastPongAt = Date.now();
        return;
      }
      try {
        const payload = JSON.parse(event.data || '{}');
        if (payload.type === 'calendar_changed') {
          lastCalendarChangeAt = Date.now();
          renderWsStatus();
          if (payload.sourceChangeId && hasRecentLocalChangeId(payload.sourceChangeId)) {
            return;
          }
          refreshFromRemoteUpdate();
        } else if (payload.type === 'user_resources_updated') {
          // User's resources (calendar_ids) were updated on admin page - refresh the visible range
          console.log('User resources updated, refreshing calendar view');
          refreshFromRemoteUpdate();
        }
      } catch (err) {
        console.warn('Invalid websocket payload:', err);
      }
    };

    socket.onclose = () => {
      clearHeartbeatTimers();
      if (updatesSocket === socket) updatesSocket = null;
      updatesConnectionState = 'disconnected';
      renderWsStatus();
      if (!hasValidToken || !currentToken) return;
      if (updatesReconnectTimer) return;
      const delay = updatesReconnectDelay;
      updatesReconnectDelay = Math.min(5000, updatesReconnectDelay * 2);
      updatesReconnectTimer = window.setTimeout(() => {
        updatesReconnectTimer = null;
        connectCalendarUpdatesSocket();
      }, delay);
    };

    socket.onerror = () => {
      clearHeartbeatTimers();
      updatesConnectionState = 'error';
      renderWsStatus();
      try {
        socket.close();
      } catch {
        // ignore
      }
    };
  }

  async function validateTokenAndLoadCalendars(token) {
    const validation = await request(
      '/api/token/validate/' + encodeURIComponent(token),
      'GET',
      null,
      false,
    );
    if (!validation.valid) {
      throw new Error('Invalid or expired token.');
    }

    const apiToken = validation.apiToken || token;

    // Pass token explicitly for bootstrap/login flows so calendar loading does
    // not depend on in-memory state timing.
    const calendars = await request(
      '/api/calendars?token=' + encodeURIComponent(apiToken),
      'GET',
      null,
      false,
    );
    const session = await request(
      '/api/session/user?token=' + encodeURIComponent(apiToken),
      'GET',
      null,
      false,
    );
    return { validation, calendars, session, apiToken };
  }

  async function claimTokenResourcesForLoggedInUser(token, calendarIds = null) {
    if (!token) return;
    try {
      const payloadCalendarIds = Array.isArray(calendarIds)
        ? calendarIds
        : (() => {
            const pendingCalendarIds = localStorage.getItem('pendingCalendarIdsToClaim');
            if (!pendingCalendarIds) return [];
            try {
              const parsedCalendarIds = JSON.parse(pendingCalendarIds);
              return Array.isArray(parsedCalendarIds) ? parsedCalendarIds : [];
            } catch (error) {
              console.warn('Failed to parse pending calendar claim payload:', error);
              return [];
            }
          })();
      const payload = payloadCalendarIds.length > 0
        ? { calendarIds: payloadCalendarIds }
        : null;
      const result = await request(
        `/api/tokens/claim-url-token/${encodeURIComponent(token)}`,
        'POST',
        payload,
        false,
      );
      if (result && result.claimed) {
        console.log('Token resources claimed for user:', result.calendarIds);
        localStorage.removeItem('pendingCalendarIdsToClaim');
      }
      return result;
    } catch (error) {
      console.warn('Failed to claim token resources for user:', error);
      return null;
    }
  }

  function shortLinkedLabel(names, kind) {
    if (!Array.isArray(names) || names.length === 0) return kind;
    if (names.length === 1) return names[0];
    return `${names[0]} (+${names.length - 1} more ${kind})`;
  }

  function requestLinkedRemovalDecision({ title, message, keepLabel, removeLabel }) {
    return new Promise(resolve => {
      if (!linkedRemovalDialog || !linkedRemovalKeep || !linkedRemovalRemove || !linkedRemovalMessage || !linkedRemovalTitle) {
        resolve(window.confirm(message || 'Apply related removal?'));
        return;
      }

      linkedRemovalTitle.textContent = title || 'Confirm Related Removal';
      linkedRemovalMessage.textContent = message || '';
      linkedRemovalKeep.textContent = keepLabel || 'Keep';
      linkedRemovalRemove.textContent = removeLabel || 'Remove';

      const cleanup = () => {
        linkedRemovalDialog.removeEventListener('close', onClose);
        linkedRemovalKeep.removeEventListener('click', onKeep);
        linkedRemovalRemove.removeEventListener('click', onRemove);
      };

      const onClose = () => {
        const shouldRemove = linkedRemovalDialog.returnValue === 'remove';
        cleanup();
        resolve(shouldRemove);
      };

      const onKeep = () => {
        linkedRemovalDialog.returnValue = 'keep';
        linkedRemovalDialog.close();
      };

      const onRemove = () => {
        linkedRemovalDialog.returnValue = 'remove';
        linkedRemovalDialog.close();
      };

      linkedRemovalDialog.returnValue = 'keep';
      linkedRemovalDialog.addEventListener('close', onClose);
      linkedRemovalKeep.addEventListener('click', onKeep);
      linkedRemovalRemove.addEventListener('click', onRemove);
      if (!linkedRemovalDialog.open) {
        linkedRemovalDialog.showModal();
      }
      linkedRemovalKeep.focus();
    });
  }

  function syncUserIdInUrl(user) {
    const url = new URL(window.location.href);
    if (user && user.id) {
      url.searchParams.set('user_id', user.id);
    } else {
      url.searchParams.delete('user_id');
    }
    history.replaceState({}, '', url.toString());
  }

  function calendarNamesFromIds(calendarIds) {
    const names = (calendarIds || [])
      .map(id => allCalendars.find(c => c.id === id)?.name)
      .filter(Boolean);
    return names.length > 0 ? names.join(', ') : 'this calendar';
  }

  function showOverlapPopupIfNeeded(message, calendarIds = []) {
    const detail = String(message || '').trim();
    if (detail && /(overlap|clash|conflict)/i.test(detail)) {
      const calendarName = calendarNamesFromIds(calendarIds);
      overlapTitle.textContent = `Scheduling Conflict: ${calendarName}`;
      overlapMessage.textContent = detail;
      overlapDialog.showModal();
      overlapOkButton.focus();
      return true;
    }
    return false;
  }

  function compareCalendarPickerItems(left, right) {
    const leftHidden = hiddenCals.has(left.id);
    const rightHidden = hiddenCals.has(right.id);
    if (leftHidden !== rightHidden) {
      return leftHidden ? 1 : -1;
    }

    const leftGroup = String(left.group || 'General');
    const rightGroup = String(right.group || 'General');
    const groupCompare = leftGroup.localeCompare(rightGroup);
    if (groupCompare !== 0) {
      return groupCompare;
    }

    return String(left.name || '').localeCompare(String(right.name || ''));
  }

  function getDialogSelectionRange() {
    const startValue = String(startInput.value || '').trim();
    if (!startValue) {
      return null;
    }

    const start = new Date(startValue);
    if (Number.isNaN(start.getTime())) {
      return null;
    }

    const endValue = String(endInput.value || '').trim();
    const end = endValue ? new Date(endValue) : new Date(start);
    if (Number.isNaN(end.getTime())) {
      return null;
    }

    return { start, end };
  }

  function getEventCalendarIds(eventInstance) {
    const directIds = Array.isArray(eventInstance?.calendarIds) ? eventInstance.calendarIds : [];
    if (directIds.length > 0) {
      return directIds;
    }

    const extendedIds = Array.isArray(eventInstance?.extendedProps?.calendarIds)
      ? eventInstance.extendedProps.calendarIds
      : [];
    if (extendedIds.length > 0) {
      return extendedIds;
    }

    return eventInstance?.calendarId ? [eventInstance.calendarId] : [];
  }

  function getEventNameForSuggestion(eventInstance) {
    const directName = String(eventInstance?.eventTitle || '').trim();
    if (directName) {
      return directName;
    }

    const fallbackTitle = String(eventInstance?.title || '').trim();
    if (!fallbackTitle) {
      return '';
    }

    const parts = fallbackTitle.split(' :: ');
    if (parts.length > 1) {
      return parts.slice(1).join(' :: ').trim();
    }

    return fallbackTitle;
  }

  function updateEventNameSuggestions(events = (dialogSuggestionEvents.length > 0 ? dialogSuggestionEvents : dialogLoadedEvents)) {
    if (!eventNameOptions) {
      return;
    }

    const selectedCalendarIds = new Set(getSelectedCalendarIds());
    const suggestions = new Set();
    const sourceEvents = Array.isArray(events) ? events : [];

    for (const eventInstance of sourceEvents) {
      const calendarIds = getEventCalendarIds(eventInstance);
      if (selectedCalendarIds.size > 0 && !calendarIds.some(calendarId => selectedCalendarIds.has(calendarId))) {
        continue;
      }

      const suggestion = getEventNameForSuggestion(eventInstance);
      if (suggestion) {
        suggestions.add(suggestion);
      }
    }

    eventNameOptions.innerHTML = '';
    for (const suggestion of Array.from(suggestions).sort((left, right) => left.localeCompare(right))) {
      const option = document.createElement('option');
      option.value = suggestion;
      eventNameOptions.appendChild(option);
    }
  }

  async function refreshDialogEventNameSuggestions() {
    if (!dialog.open) {
      return;
    }

    const requestId = ++dialogSuggestionRequestId;
    try {
      const query = new URLSearchParams({
        start: '1970-01-01T00:00:00Z',
        end: '2100-01-01T00:00:00Z',
      });
      const events = await request('/api/events?' + query.toString());
      if (requestId !== dialogSuggestionRequestId || !dialog.open) {
        return;
      }
      dialogSuggestionEvents = Array.isArray(events) ? events : [];
      updateEventNameSuggestions(dialogSuggestionEvents);
    } catch (error) {
      if (requestId === dialogSuggestionRequestId) {
        console.warn('Failed to refresh event name suggestions:', error);
      }
    }
  }

  function scheduleDialogEventNameSuggestionsRefresh() {
    if (dialogSuggestionRefreshTimer) {
      window.clearTimeout(dialogSuggestionRefreshTimer);
    }
    dialogSuggestionRefreshTimer = window.setTimeout(() => {
      dialogSuggestionRefreshTimer = null;
      void refreshDialogEventNameSuggestions();
    }, 120);
  }

  function eventInstanceBookedForDialog(eventInstance, calendarId, rangeStart, rangeEnd) {
    const seriesId = eventInstance?.extendedProps?.seriesId || eventInstance?.id || '';
    if (dialogState.mode === 'edit' && dialogState.eventId && seriesId === dialogState.eventId) {
      return false;
    }

    const calendarIds = getEventCalendarIds(eventInstance);
    if (!calendarIds.includes(calendarId)) {
      return false;
    }

    const startValue = eventInstance?.start;
    if (!startValue) {
      return false;
    }
    const eventStart = new Date(startValue);
    if (Number.isNaN(eventStart.getTime())) {
      return false;
    }

    const endValue = eventInstance?.end || startValue;
    const eventEnd = new Date(endValue);
    if (Number.isNaN(eventEnd.getTime())) {
      return false;
    }

    return eventStart < rangeEnd && rangeStart < eventEnd;
  }

  function updateDialogCalendarAvailability(events = dialogLoadedEvents) {
    if (!dialog.open) {
      return;
    }

    const range = getDialogSelectionRange();
    const sourceEvents = Array.isArray(events) ? events : [];
    const buttons = eventCalendars.querySelectorAll('.event-calendar-info[data-calendar-id]');
    for (const button of buttons) {
      const calendarId = button.getAttribute('data-calendar-id') || '';
      const calendarName = button.getAttribute('data-calendar-name') || 'this calendar';
      const booked = Boolean(range)
        && sourceEvents.some(eventInstance => eventInstanceBookedForDialog(eventInstance, calendarId, range.start, range.end));
      button.classList.toggle('event-calendar-info--booked', booked);
      button.title = booked
        ? 'Booked during the selected time. Open calendar information.'
        : 'Open calendar information';
      button.setAttribute(
        'aria-label',
        booked
          ? `Open information for ${calendarName}. Booked during the selected time.`
          : `Open information for ${calendarName}`,
      );
    }
    syncCalendarHoverTooltipState();
    updateEventNameSuggestions();
  }

  async function refreshDialogCalendarAvailability() {
    if (!dialog.open) {
      return;
    }

    const range = getDialogSelectionRange();
    if (!range) {
      dialogLoadedEvents = [];
      updateDialogCalendarAvailability([]);
      return;
    }

    const requestId = ++dialogAvailabilityRequestId;
    try {
      const query = new URLSearchParams({
        start: range.start.toISOString(),
        end: range.end.toISOString(),
      });
      const events = await request('/api/events?' + query.toString());
      if (requestId !== dialogAvailabilityRequestId || !dialog.open) {
        return;
      }
      dialogLoadedEvents = Array.isArray(events) ? events : [];
      updateDialogCalendarAvailability(dialogLoadedEvents);
    } catch (error) {
      if (requestId === dialogAvailabilityRequestId) {
        console.warn('Failed to refresh dialog availability:', error);
      }
    }
  }

  function scheduleDialogCalendarAvailabilityRefresh() {
    if (dialogAvailabilityRefreshTimer) {
      window.clearTimeout(dialogAvailabilityRefreshTimer);
    }
    dialogAvailabilityRefreshTimer = window.setTimeout(() => {
      dialogAvailabilityRefreshTimer = null;
      void refreshDialogCalendarAvailability();
    }, 120);
  }

  function renderCalendarCheckboxes(selectedIds) {
    const selectedSet = new Set(selectedIds || []);
    eventCalendars.innerHTML = '';
    // If token is set, only show token-accessible calendars
    const visibleCalendars = tokenAllowedCalendars 
      ? allCalendars.filter(cal => tokenAllowedCalendars.has(cal.id))
      : allCalendars;
    const orderedCalendars = [...visibleCalendars].sort(compareCalendarPickerItems);
    
    for (const [groupName, calendars] of groupCalendars(orderedCalendars)) {
      const groupHeader = document.createElement('div');
      groupHeader.className = 'sidebar-section-title';
      groupHeader.textContent = groupName;
      eventCalendars.appendChild(groupHeader);

      for (const cal of calendars) {
        const item = document.createElement('div');
        item.className = 'event-calendar-item';
        if (hiddenCals.has(cal.id)) {
          item.classList.add('event-calendar-item--hidden');
        }

        const toggle = document.createElement('label');
        toggle.className = 'event-calendar-toggle';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = cal.id;
        checkbox.checked = selectedSet.has(cal.id);
        checkbox.addEventListener('change', () => {
            scheduleDialogEventNameSuggestionsRefresh();
            updateEventNameSuggestions();
        });

        const dot = document.createElement('span');
        dot.className = 'event-calendar-dot';
        dot.style.background = cal.color;

        const name = document.createElement('span');
        name.className = 'event-calendar-label';
        name.textContent = cal.name;

        toggle.append(checkbox, dot, name);

        const infoButton = document.createElement('button');
        infoButton.type = 'button';
        infoButton.className = 'event-calendar-info';
        infoButton.dataset.calendarId = cal.id;
        infoButton.dataset.calendarName = cal.name;
        infoButton.textContent = 'i';
        bindCalendarHoverTooltip(infoButton, cal);
        infoButton.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          window.location.href = `/calendar-info/${encodeURIComponent(cal.id)}`;
        });

        item.append(toggle, infoButton);
        eventCalendars.appendChild(item);
      }
    }

    updateDialogCalendarAvailability();
  }

  function getSelectedCalendarIds() {
    return Array.from(eventCalendars.querySelectorAll('input[type="checkbox"]'))
      .filter(checkbox => checkbox.checked)
      .map(checkbox => checkbox.value);
  }

  function groupCalendars(calendars) {
    const uniqueCalendars = [];
    const seenCalendarIds = new Set();
    for (const cal of calendars || []) {
      const calendarId = String(cal && cal.id ? cal.id : '').trim();
      if (!calendarId || seenCalendarIds.has(calendarId)) continue;
      seenCalendarIds.add(calendarId);
      uniqueCalendars.push(cal);
    }

    const grouped = new Map();
    for (const cal of uniqueCalendars) {
      const groupName = cal.group || 'General';
      if (!grouped.has(groupName)) grouped.set(groupName, []);
      grouped.get(groupName).push(cal);
    }
    return Array.from(grouped.entries());
  }

  function calendarThumbnailUrl(calendar) {
    const thumbUrl = calendar?.imageThumbUrl || '';
    if (thumbUrl) return thumbUrl;
    const imageUrl = calendar?.imageUrl || '';
    if (imageUrl.startsWith('data:')) return imageUrl;
    return calendar?.imageFallbackUrl || imageUrl || '';
  }

  function positionCalendarHoverTooltip(event) {
    const tooltipWidth = calendarHoverTooltip.offsetWidth || 320;
    const tooltipHeight = calendarHoverTooltip.offsetHeight || 240;
    const nextX = event.clientX + 16;
    const nextY = event.clientY + 16;
    const maxX = window.innerWidth - tooltipWidth - 8;
    const maxY = window.innerHeight - tooltipHeight - 8;
    calendarHoverTooltip.style.left = `${Math.max(8, Math.min(nextX, maxX))}px`;
    calendarHoverTooltip.style.top = `${Math.max(8, Math.min(nextY, maxY))}px`;
  }

  function showCalendarHoverTooltip(calendar, event, host = document.body) {
    const thumbUrl = calendarThumbnailUrl(calendar);
    if (!thumbUrl) return;
    if (calendarHoverTooltip.parentElement !== host) {
      host.appendChild(calendarHoverTooltip);
    }
    calendarHoverTooltip.replaceChildren();
    const image = document.createElement('img');
    image.src = thumbUrl;
    image.alt = `${calendar.name} thumbnail`;
    const copy = document.createElement('div');
    copy.className = 'calendar-hover-copy';
    const title = document.createElement('div');
    title.className = 'calendar-hover-title';
    title.textContent = calendar.name;
    const subtitle = document.createElement('div');
    subtitle.className = 'calendar-hover-subtitle';
    subtitle.textContent = String(calendar.blurb || `${calendar.name} belongs to the ${calendar.group || 'General'} group and is available from the main schedule.`).trim();
    copy.append(title, subtitle);
    calendarHoverTooltip.append(image, copy);
    calendarHoverTooltip.style.display = 'block';
    positionCalendarHoverTooltip(event);
    syncCalendarHoverTooltipState();
  }

  function bindCalendarHoverTooltip(button, calendar) {
    button.addEventListener('mouseenter', (event) => {
      activeCalendarHoverButton = button;
      const host = button.closest('dialog') || document.body;
      showCalendarHoverTooltip(calendar, event, host);
    });
    button.addEventListener('mousemove', (event) => {
      if (calendarHoverTooltip.style.display === 'block') {
        positionCalendarHoverTooltip(event);
      }
    });
    button.addEventListener('mouseleave', () => {
      if (activeCalendarHoverButton === button) {
        activeCalendarHoverButton = null;
      }
      hideCalendarHoverTooltip();
    });
  }

  function hideCalendarHoverTooltip() {
    calendarHoverTooltip.style.display = 'none';
    calendarHoverTooltip.replaceChildren();
    calendarHoverTooltip.classList.remove('calendar-hover-tooltip--booked');
  }

  function syncCalendarHoverTooltipState() {
    const booked = Boolean(
      activeCalendarHoverButton && activeCalendarHoverButton.classList.contains('event-calendar-info--booked')
    );
    calendarHoverTooltip.classList.toggle('calendar-hover-tooltip--booked', booked);
  }

  function getAdminEditorToken() {
    return currentToken || authenticatedSessionToken || '';
  }

  function isAdminUser() {
    return Boolean(currentUser && currentUser.role === 'admin');
  }

  function isServiceAccountUser() {
    return Boolean(currentUser && currentUser.serviceAccount);
  }

  async function logoutUser() {
    try {
      // Delete the user's link token from the database
      const urlParams = new URLSearchParams(window.location.search);
      const userIdForLogout = (currentUser && currentUser.id) || urlParams.get('user_id');
      if (currentToken && userIdForLogout) {
        await request(
          '/api/logout',
          'POST',
          { user_id: userIdForLogout }
        ).catch(error => {
          console.error('Failed to delete token:', error);
          // Still redirect to clear the session
        });
      }
      clearPersistedAuthToken();
      clearPreservedLinkToken();
      // Clear URL and redirect to home to reset the app
      window.location.href = '/';
    } catch (error) {
      console.error('Logout failed:', error);
      clearPersistedAuthToken();
      clearPreservedLinkToken();
      // Still redirect to clear the session
      window.location.href = '/';
    }
  }

  function isTokenOnlyPage() {
    return tokenAccessRequested || Boolean(currentUser && currentUser.isTokenOnlyAccount);
  }

  function getTokenPageCalendarIdsToClaim() {
    const selectedCalendarIds = getSelectedCalendarIds();
    if (selectedCalendarIds.length > 0) {
      return selectedCalendarIds;
    }
    if (tokenAllowedCalendars && tokenAllowedCalendars.size > 0) {
      return Array.from(tokenAllowedCalendars);
    }
    return [];
  }

  async function getSessionUser() {
    const response = await fetch('/api/auth/check-session', {
      method: 'GET',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) return null;
    const sessionData = await response.json();
    authenticatedSessionToken = sessionData && sessionData.authenticated
      ? (sessionData.apiToken || null)
      : null;
    return sessionData && sessionData.authenticated ? sessionData : null;
  }

  async function preservePendingLinkForOauth(linkToken, calendarIds = null) {
    if (!linkToken) return;
    const payload = { token: linkToken };
    if (Array.isArray(calendarIds)) {
      payload.calendarIds = calendarIds;
    }
    await fetch('/auth/preserve-link-token', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  function redirectToUserOnlyUrl(user) {
    if (!user || !user.id) return;
    const url = new URL(window.location.origin + '/');
    url.searchParams.set('user_id', user.id);
    window.location.replace(url.toString());
  }

  function requestSaveToAccountAuthMethod() {
    return new Promise(resolve => {
      if (!saveAccountAuthDialog || !saveAccountAuthCancel || !saveAccountAuthPasskey || !saveAccountAuthGoogle) {
        resolve('google');
        return;
      }

      let resolved = false;
      const finish = (choice) => {
        if (resolved) return;
        resolved = true;
        saveAccountAuthDialog.returnValue = choice || 'cancel';
        if (saveAccountAuthDialog.open) {
          saveAccountAuthDialog.close();
        }
      };

      const onClose = () => {
        saveAccountAuthDialog.removeEventListener('close', onClose);
        const value = String(saveAccountAuthDialog.returnValue || '').trim();
        if (value === 'google' || value === 'passkey') {
          resolve(value);
          return;
        }
        resolve(null);
      };

      saveAccountAuthCancel.onclick = () => finish('cancel');
      saveAccountAuthPasskey.onclick = () => finish('passkey');
      saveAccountAuthGoogle.onclick = () => finish('google');
      saveAccountAuthDialog.returnValue = 'cancel';
      saveAccountAuthDialog.addEventListener('close', onClose);
      if (!saveAccountAuthDialog.open) {
        saveAccountAuthDialog.showModal();
      }
    });
  }

  async function authenticateWithPasskey() {
    if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.get) {
      throw new Error('This browser does not support passkey login.');
    }

    const optionsResult = await request('/api/passkeys/auth/options', 'POST', {}, false);
    const publicKey = optionsResult?.publicKey;
    const stateId = String(optionsResult?.stateId || '').trim();
    if (!publicKey || !publicKey.challenge || !stateId) {
      throw new Error('Invalid passkey login options from server.');
    }

    const assertionOptions = {
      ...publicKey,
      challenge: base64UrlToBuffer(publicKey.challenge),
      allowCredentials: Array.isArray(publicKey.allowCredentials)
        ? publicKey.allowCredentials.map((descriptor) => ({
            ...descriptor,
            id: base64UrlToBuffer(descriptor.id),
          }))
        : [],
    };

    const assertion = await navigator.credentials.get({ publicKey: assertionOptions });
    if (!assertion) {
      throw new Error('Passkey login was cancelled.');
    }

    const credentialPayload = {
      id: assertion.id,
      type: assertion.type,
      rawId: bufferToBase64Url(assertion.rawId),
      response: {
        clientDataJSON: bufferToBase64Url(assertion.response.clientDataJSON),
        authenticatorData: bufferToBase64Url(assertion.response.authenticatorData),
        signature: bufferToBase64Url(assertion.response.signature),
        userHandle: assertion.response.userHandle ? bufferToBase64Url(assertion.response.userHandle) : null,
      },
    };

    return request('/api/passkeys/auth/verify', 'POST', {
      stateId,
      credential: credentialPayload,
    }, false);
  }

  async function handleTokenPageAction() {
    const calendarIdsToClaim = getTokenPageCalendarIdsToClaim();
    const sessionUser = currentUser && currentUser.id ? currentUser : null;
    const hasAuthenticatedSession = Boolean(sessionUser && authenticatedSessionToken);
    const sessionData = hasAuthenticatedSession ? { user: sessionUser, apiToken: authenticatedSessionToken } : await getSessionUser();
    const originalLinkToken = sharedLinkToken || (currentToken && !isJwtToken(currentToken) ? currentToken : null);

    if (sessionData && sessionData.user && sessionData.apiToken) {
      // Session exists - either save directly to a normal account or hand off
      // a token-only account into OAuth so it can be converted.
      try {
        currentUser = sessionData.user;
        syncUserIdInUrl(currentUser);
        if (currentUser && currentUser.serviceAccount) {
          const authMethod = await requestSaveToAccountAuthMethod();
          if (!authMethod) {
            return;
          }

          if (authMethod === 'google') {
            await preservePendingLinkForOauth(originalLinkToken || currentToken, calendarIdsToClaim);
            window.location.href = '/auth/google-login';
            return;
          }

          const authResult = await authenticateWithPasskey();
          if (!authResult?.authenticated || !authResult?.apiToken) {
            throw new Error('Passkey login failed.');
          }

          const newSessionToken = String(authResult.apiToken || '').trim();
          currentToken = newSessionToken;
          authenticatedSessionToken = newSessionToken;
          currentUser = authResult.user || null;
          syncUserIdInUrl(currentUser);

          const claimResult = await claimTokenResourcesForLoggedInUser(originalLinkToken || currentToken, calendarIdsToClaim);
          redirectToUserOnlyUrl({ id: claimResult?.userId || currentUser?.id });
          showSaveToast('Calendar updated', 'Calendar added to your account');
          return;
        }

        if (currentUser && currentUser.isTokenOnlyAccount) {
          await preservePendingLinkForOauth(originalLinkToken || currentToken, calendarIdsToClaim);
          window.location.href = '/auth/google-login';
          return;
        }

        const claimResult = await claimTokenResourcesForLoggedInUser(originalLinkToken || currentToken, calendarIdsToClaim);
        redirectToUserOnlyUrl({ id: claimResult?.userId || currentUser.id });
        showSaveToast('Calendar updated', 'Calendar added to your account');
      } catch (error) {
        showErrorToast('Save failed', error instanceof Error ? error.message : String(error));
      }
    } else {
      await preservePendingLinkForOauth(originalLinkToken, calendarIdsToClaim);
      // No session token - redirect to login
      window.location.href = '/auth/google-login';
    }
  }

  async function loadSessionUser(token = currentToken) {
    if (!token) {
      currentUser = null;
      syncUserIdInUrl(null);
      return null;
    }
    const session = await request('/api/session/user', 'GET', null, false);
    currentUser = session && session.authenticated ? session.user : null;
    syncUserIdInUrl(currentUser);
    return currentUser;
  }

  function setCurrentView(view) {
    currentView = view;
    const showCalendar = view === 'calendar';
    const showAccess = view === 'access';
    const showUpcoming = view === 'upcoming';
    const showAdmin = view === 'admin' && isAdminUser();
    calendarView.hidden = !showCalendar;
    if (accessPanel) {
      accessPanel.hidden = !showAccess;
    }
    if (upcomingPanel) {
      upcomingPanel.hidden = !showUpcoming;
    }
    adminPanel.hidden = !showAdmin;
    if (showAccess && !accessCatalogData) {
      void loadAccessCatalog();
    }
    if (showAccess) {
      if (settingsProfileError) {
        settingsProfileError.textContent = '';
      }
      void loadUserProfileSettings().catch((error) => {
        if (settingsProfileError) {
          settingsProfileError.textContent = error instanceof Error ? error.message : String(error);
        }
      });
      renderOwnLoginLink('');
      void getOwnLoginToken()
        .then((result) => {
          const loginUrl = String(result?.loginUrl || '').trim();
          renderOwnLoginLink(loginUrl);
        })
        .catch(() => {
          const existingLoginUrl = currentToken && !isJwtToken(currentToken)
            ? `${window.location.origin}/?token=${encodeURIComponent(currentToken)}`
            : '';
          renderOwnLoginLink(existingLoginUrl);
        });
      void loadPasskeys();
    }
    if (showUpcoming) {
      void loadUpcomingBookings();
    }
    if (adminNavItem) {
      adminNavItem.classList.toggle('active', showAdmin);
    }
    if (accessNavItem) {
      accessNavItem.classList.toggle('active', showAccess);
    }
    if (upcomingNavItem) {
      upcomingNavItem.classList.toggle('active', showUpcoming);
    }
    if (calendarNavItem) {
      calendarNavItem.classList.toggle('active', showCalendar);
    }
  }

  function accessButtonLabelForState(state) {
    if (state === 'granted' || state === 'approved') return 'Approved';
    if (state === 'pending' || state === 'requested' || state === 'group-pending') return 'Requested';
    return 'Request access';
  }

  function base64UrlToBuffer(value) {
    const input = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    const padLen = (4 - (input.length % 4)) % 4;
    const padded = input + '='.repeat(padLen);
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  function bufferToBase64Url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 1) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/g, '');
  }

  function formatPasskeyDate(iso) {
    if (!iso) return 'unknown date';
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return 'unknown date';
    return parsed.toLocaleString();
  }

  function renderPasskeyList() {
    if (!passkeyList) return;
    passkeyList.innerHTML = '';
    if (!Array.isArray(userPasskeys) || userPasskeys.length === 0) {
      const emptyState = document.createElement('div');
      emptyState.className = 'admin-helper';
      emptyState.textContent = 'No passkeys created yet.';
      passkeyList.appendChild(emptyState);
      return;
    }
    for (const passkey of userPasskeys) {
      const pill = document.createElement('span');
      pill.className = 'admin-pill';
      const shortId = String(passkey.credentialId || '').slice(0, 10) || 'unknown';
      const label = document.createElement('span');
      label.textContent = `${passkey.name || 'Passkey'} (${shortId}..., ${formatPasskeyDate(passkey.createdAt)})`;
      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'admin-pill-remove';
      removeButton.title = `Remove ${passkey.name || 'passkey'}`;
      removeButton.textContent = 'x';
      removeButton.onclick = async () => {
        try {
          await request(`/api/passkeys/${encodeURIComponent(passkey.credentialId)}`, 'DELETE');
          showSaveToast('Passkey removed', `${passkey.name || 'Passkey'} removed.`);
          await loadPasskeys();
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          showErrorToast('Passkey remove failed', message, accessPanel || document.body);
        }
      };
      pill.append(label, removeButton);
      passkeyList.appendChild(pill);
    }
  }

  async function loadPasskeys() {
    if (!hasValidToken && !currentToken) {
      userPasskeys = [];
      renderPasskeyList();
      return;
    }
    try {
      const response = await request('/api/passkeys');
      userPasskeys = Array.isArray(response?.passkeys) ? response.passkeys : [];
    } catch (error) {
      userPasskeys = [];
      console.warn('Failed to load passkeys:', error);
    }
    renderPasskeyList();
  }

  function formatUpcomingDate(value, isAllDay) {
    if (!value) return 'Unknown time';
    const parsed = new Date(String(value));
    if (Number.isNaN(parsed.getTime())) return 'Unknown time';
    if (isAllDay) {
      return parsed.toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
      });
    }
    return parsed.toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  }

  function renderUpcomingBookings() {
    if (!upcomingBookingsGrid) return;
    upcomingBookingsGrid.innerHTML = '';

    const rows = Array.isArray(upcomingBookingsData) ? upcomingBookingsData : [];
    if (rows.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'upcoming-booking-empty';
      empty.textContent = 'No upcoming bookings match your profile name.';
      upcomingBookingsGrid.appendChild(empty);
      return;
    }

    for (const booking of rows) {
      const card = document.createElement('article');
      card.className = 'upcoming-booking-row';

      const title = document.createElement('p');
      title.className = 'upcoming-booking-title';
      title.textContent = String(booking.eventTitle || booking.title || 'Booking');

      const timeMeta = document.createElement('p');
      timeMeta.className = 'upcoming-booking-meta';
      const startLabel = formatUpcomingDate(booking.start, booking.allDay);
      const endLabel = booking.end ? formatUpcomingDate(booking.end, booking.allDay) : '';
      timeMeta.textContent = endLabel ? `${startLabel} -> ${endLabel}` : startLabel;

      const calMeta = document.createElement('p');
      calMeta.className = 'upcoming-booking-meta';
      const calendarNames = Array.isArray(booking.calendarNames)
        ? booking.calendarNames.map((value) => String(value || '').trim()).filter(Boolean)
        : [];
      calMeta.textContent = `Calendars: ${calendarNames.length > 0 ? calendarNames.join(', ') : 'Unknown'}`;

      const detailMeta = document.createElement('p');
      detailMeta.className = 'upcoming-booking-meta';
      const contact = String(booking.contact || '').trim();
      detailMeta.textContent = contact ? `Contact: ${contact}` : 'No contact set';

      card.append(title, timeMeta, calMeta, detailMeta);
      upcomingBookingsGrid.appendChild(card);
    }
  }

  async function loadUpcomingBookings() {
    if (!upcomingBookingsGrid) return;
    if (!hasValidToken || isServiceAccountUser()) {
      upcomingBookingsData = [];
      renderUpcomingBookings();
      return;
    }

    upcomingBookingsGrid.innerHTML = '';
    const loading = document.createElement('div');
    loading.className = 'upcoming-booking-empty';
    loading.textContent = 'Loading upcoming bookings...';
    upcomingBookingsGrid.appendChild(loading);

    try {
      const response = await request('/api/users/me/upcoming-bookings');
      upcomingBookingsData = Array.isArray(response?.bookings) ? response.bookings : [];
      renderUpcomingBookings();
    } catch (error) {
      upcomingBookingsData = [];
      upcomingBookingsGrid.innerHTML = '';
      const failed = document.createElement('div');
      failed.className = 'upcoming-booking-empty';
      failed.textContent = error instanceof Error ? error.message : String(error);
      upcomingBookingsGrid.appendChild(failed);
    }
  }

  function renderOwnLoginLink(value = '') {
    if (!ownLoginLinkAnchor || !ownLoginLinkCopy) return;
    const normalized = String(value || '').trim();
    ownLoginLinkAnchor.href = normalized || '#';
    ownLoginLinkAnchor.textContent = normalized || 'No login URL';
    if (!normalized) {
      ownLoginLinkAnchor.setAttribute('aria-disabled', 'true');
      ownLoginLinkAnchor.style.pointerEvents = 'none';
      ownLoginLinkAnchor.style.opacity = '0.65';
      ownLoginLinkCopy.setAttribute('aria-disabled', 'true');
      return;
    }
    ownLoginLinkAnchor.removeAttribute('aria-disabled');
    ownLoginLinkAnchor.style.pointerEvents = '';
    ownLoginLinkAnchor.style.opacity = '';
    ownLoginLinkCopy.removeAttribute('aria-disabled');
  }

  async function regenerateOwnLoginLink() {
    const result = await regenerateOwnLoginToken();
    const nextUrl = String(result?.loginUrl || '').trim();
    renderOwnLoginLink(nextUrl);
    await loadShareLinks();
    showSaveToast('Login string regenerated', nextUrl || 'Your login string was regenerated.');
  }

  function renderShareLinks() {
    if (!shareLinksList) return;
    shareLinksList.innerHTML = '';
    const links = Array.isArray(shareLinksData) ? shareLinksData : [];
    if (links.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'share-link-empty';
      empty.textContent = isServiceAccountUser()
        ? 'No share link is available for this service account.'
        : 'No eligible service-account links match your approved groups.';
      shareLinksList.appendChild(empty);
      return;
    }
    for (const link of links) {
      const row = document.createElement('div');
      row.className = 'share-link-row';
      const name = document.createElement('div');
      name.className = 'share-link-name';
      name.textContent = String(link.name || 'Share link');
      const anchor = document.createElement('a');
      anchor.href = String(link.loginUrl || '#');
      anchor.textContent = String(link.loginUrl || 'No login URL');
      anchor.target = '_blank';
      anchor.rel = 'noreferrer noopener';

      const groupsWrap = document.createElement('div');
      groupsWrap.className = 'admin-helper';
      groupsWrap.style.display = 'grid';
      groupsWrap.style.gap = '4px';

      const groups = Array.isArray(link.groups) ? link.groups : [];
      if (groups.length > 0) {
        for (const group of groups) {
          const groupName = String(group?.name || '').trim();
          if (!groupName) continue;
          const calendars = Array.isArray(group?.calendars) ? group.calendars : [];
          const calendarNames = calendars
            .map((calendar) => String(calendar?.name || '').trim())
            .filter((value) => value);
          const groupLine = document.createElement('div');
          groupLine.textContent = calendarNames.length > 0
            ? `${groupName}: ${calendarNames.join(', ')}`
            : `${groupName}: (no calendars)`;
          groupsWrap.appendChild(groupLine);
        }
      }

      const copy = document.createElement('a');
      copy.href = '#';
      copy.className = 'admin-inline-link';
      copy.textContent = 'Copy to clipboard';
      copy.onclick = async (event) => {
        event.preventDefault();
        try {
          await navigator.clipboard.writeText(String(link.loginUrl || ''));
          showSaveToast('Copied', 'Share link copied to clipboard.');
        } catch (error) {
          showErrorToast('Copy failed', error instanceof Error ? error.message : String(error));
        }
      };
      row.append(name, anchor, groupsWrap, copy);
      shareLinksList.appendChild(row);
    }
  }

  async function loadShareLinks() {
    if (!currentUser) {
      shareLinksData = [];
      renderShareLinks();
      return;
    }
    try {
      const result = await request('/api/share-links');
      shareLinksData = Array.isArray(result?.links) ? result.links : [];
    } catch (error) {
      shareLinksData = [];
      console.warn('Failed to load share links:', error);
    }
    renderShareLinks();
  }

  async function openShareLinksDialog() {
    await loadShareLinks();
    if (shareLinksDialog && !shareLinksDialog.open) {
      shareLinksDialog.showModal();
    }
  }

  async function createPasskeyFromSettings() {
    if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.create) {
      showErrorToast('Passkey unavailable', 'This browser does not support passkey creation.', accessPanel || document.body);
      return;
    }

    if (createPasskeyButton) createPasskeyButton.disabled = true;
    try {
      const passkeyName = String(passkeyNameInput?.value || '').trim();
      const optionsResult = await request('/api/passkeys/register/options', 'POST', {});
      const publicKey = optionsResult?.publicKey;
      if (!publicKey || !publicKey.challenge || !publicKey.user || !publicKey.user.id) {
        throw new Error('Invalid passkey options from server.');
      }

      const credentialCreationOptions = {
        ...publicKey,
        challenge: base64UrlToBuffer(publicKey.challenge),
        user: {
          ...publicKey.user,
          id: base64UrlToBuffer(publicKey.user.id),
        },
        excludeCredentials: Array.isArray(publicKey.excludeCredentials)
          ? publicKey.excludeCredentials.map((descriptor) => ({
              ...descriptor,
              id: base64UrlToBuffer(descriptor.id),
            }))
          : [],
      };

      const credential = await navigator.credentials.create({ publicKey: credentialCreationOptions });
      if (!credential) {
        throw new Error('Passkey creation was cancelled.');
      }

      const credentialPayload = {
        id: credential.id,
        type: credential.type,
        rawId: bufferToBase64Url(credential.rawId),
        response: {
          clientDataJSON: bufferToBase64Url(credential.response.clientDataJSON),
          attestationObject: bufferToBase64Url(credential.response.attestationObject),
          transports: typeof credential.response.getTransports === 'function' ? credential.response.getTransports() : [],
        },
      };

      await request('/api/passkeys/register/verify', 'POST', {
        credential: credentialPayload,
        passkeyName,
      });
      showSaveToast('Passkey created', 'You can now use this passkey for sign-in.');
      if (passkeyNameInput) passkeyNameInput.value = '';
      await loadPasskeys();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      showErrorToast('Passkey setup failed', message, accessPanel || document.body);
    } finally {
      if (createPasskeyButton) createPasskeyButton.disabled = false;
    }
  }

  async function requestAccess(targetType, targetId, label, triggerButton = null) {
    const previousState = triggerButton ? String(triggerButton.dataset.state || '') : '';
    const previousLabel = triggerButton ? String(triggerButton.textContent || '') : '';

    if (triggerButton) {
      triggerButton.disabled = true;
      triggerButton.dataset.state = 'pending';
      triggerButton.textContent = accessButtonLabelForState('pending');
    }

    // Confirm immediately so the user gets feedback even if the API is slow.
    showSaveToast('Request sent', `Submitting access request for ${label}...`);

    try {
      await request('/api/access-requests', 'POST', { targetType, targetId });
      showSaveToast('Access requested', `Requested access to ${label}.`);
      void loadAccessCatalog();
    } catch (error) {
      if (triggerButton) {
        triggerButton.disabled = false;
        if (previousState) {
          triggerButton.dataset.state = previousState;
        } else {
          delete triggerButton.dataset.state;
        }
        triggerButton.textContent = previousLabel || accessButtonLabelForState(previousState || 'available');
      }
      showErrorToast('Request failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
    }
  }

  async function withdrawAccessRequest(requestId, label) {
    try {
      await request(`/api/access-requests/${requestId}`, 'DELETE');
      showSaveToast('Request withdrawn', `Withdrew access request for ${label}.`);
      await loadAccessCatalog();
    } catch (error) {
      showErrorToast('Withdraw failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
    }
  }

  async function toggleAccessVisibility(requestId, label) {
    try {
      await request(`/api/access-requests/${requestId}/toggle-visibility`, 'POST');
      showSaveToast('Access updated', `Updated access for ${label}.`);
      await loadAccessCatalog();
    } catch (error) {
      showErrorToast('Update failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
    }
  }

  async function toggleAccessVisibilityForTarget(targetType, targetId, label) {
    try {
      await request('/api/access-requests/toggle-visibility', 'POST', { targetType, targetId });
      showSaveToast('Access updated', `Updated access for ${label}.`);
      await loadAccessCatalog();
    } catch (error) {
      showErrorToast('Update failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
    }
  }

  function renderAccessCatalog() {
    if (!accessCatalogGrid) {
      return;
    }

    accessCatalogGrid.innerHTML = '';
    const groups = Array.isArray(accessCatalogData?.groups) ? accessCatalogData.groups : [];
    if (groups.length === 0) {
      const emptyState = document.createElement('div');
      emptyState.className = 'admin-helper';
      emptyState.textContent = 'No calendars are available yet.';
      accessCatalogGrid.appendChild(emptyState);
      return;
    }

    for (const group of groups) {
      const groupCard = document.createElement('section');
      groupCard.className = 'access-group-card';

      const groupHead = document.createElement('div');
      groupHead.className = 'access-group-head';

      const groupText = document.createElement('div');
      const groupTitle = document.createElement('div');
      groupTitle.className = 'access-group-title';
      groupTitle.textContent = group.name;
      const groupSubtitle = document.createElement('div');
      groupSubtitle.className = 'access-group-subtitle';
      const groupCount = Array.isArray(group.calendars) ? group.calendars.length : 0;
      groupSubtitle.textContent = `${groupCount} calendar${groupCount === 1 ? '' : 's'}`;
      groupText.append(groupTitle, groupSubtitle);

      const groupButton = document.createElement('button');
      groupButton.type = 'button';
      groupButton.className = 'access-pill-button access-group-request';
      const groupState = group.requestState || 'available';
      groupButton.dataset.state = groupState;
      groupButton.textContent = groupState === 'available'
        ? 'Request Group Access'
        : groupState === 'granted' || groupState === 'approved'
          ? 'Hide Group'
          : groupState === 'hidden'
            ? 'Show Group'
            : accessButtonLabelForState(groupState);
      if (groupState === 'available') {
        groupButton.onclick = () => requestAccess('group', group.name, `the ${group.name} group`, groupButton);
      } else if (groupState === 'pending' || groupState === 'requested' || groupState === 'group-pending') {
        groupButton.onclick = () => withdrawAccessRequest(group.requestId, `the ${group.name} group`);
      } else {
        groupButton.onclick = () => toggleAccessVisibilityForTarget('group', group.name, `the ${group.name} group`);
      }

      groupHead.append(groupText, groupButton);

      const calendarList = document.createElement('div');
      calendarList.className = 'access-group-assets';
      for (const calendar of (group.calendars || [])) {
        const calendarState = calendar.requestState || 'available';
        const calendarButton = document.createElement('button');
        calendarButton.type = 'button';
        calendarButton.className = 'access-pill-button access-asset-pill';
        calendarButton.dataset.state = calendarState;
        calendarButton.textContent = calendar.name;
        calendarButton.title = calendarState === 'granted' || calendarState === 'approved'
          ? `Hide access to ${calendar.name}`
          : calendarState === 'hidden'
            ? `Show access to ${calendar.name}`
            : calendarState === 'pending' || calendarState === 'requested' || calendarState === 'group-pending'
              ? `Withdraw the request for ${calendar.name}`
              : `Request access to ${calendar.name}`;
        if (calendarState === 'available') {
          calendarButton.onclick = () => requestAccess('calendar', calendar.id, calendar.name, calendarButton);
        } else if (calendarState === 'pending' || calendarState === 'requested' || calendarState === 'group-pending') {
          calendarButton.onclick = () => withdrawAccessRequest(calendar.requestId, calendar.name);
        } else if (calendarState === 'granted' || calendarState === 'approved' || calendarState === 'hidden') {
          calendarButton.onclick = () => toggleAccessVisibilityForTarget('calendar', calendar.id, calendar.name);
        }

        calendarList.appendChild(calendarButton);
      }

      groupCard.append(groupHead, calendarList);
      accessCatalogGrid.appendChild(groupCard);
    }
  }

  async function loadAccessCatalog() {
    if (!hasValidToken && !currentToken) {
      accessCatalogData = null;
      renderAccessCatalog();
      return;
    }

    try {
      accessCatalogData = await request('/api/access/catalog');
    } catch (error) {
      accessCatalogData = { groups: [] };
      console.warn('Failed to load access catalog:', error);
    }
    renderAccessCatalog();
  }

  function resourceName(resourceId) {
    const resources = adminUsersData?.resources || [];
    return resources.find(resource => resource.id === resourceId)?.name || resourceId;
  }

  function assignedGroupsForCalendarIds(calendarIds, resourceGroups) {
    const selected = new Set(calendarIds || []);
    const groups = [];
    for (const [groupName, ids] of Object.entries(resourceGroups || {})) {
      const assignedIds = ids.filter(id => selected.has(id));
      if (assignedIds.length > 0) {
        groups.push({ groupName, assignedIds });
      }
    }
    return groups;
  }
  async function saveAdminUserResources(userId, calendarIds, groupNames = []) {
    await request(`/api/admin/users/${encodeURIComponent(userId)}/resources`, 'PUT', { calendarIds, groupNames });
    showSaveToast('Access updated', 'User calendar and group access updated.');
  }

  async function createAdminUser(name, email, calendarIds, groupNames = []) {
    return request('/api/admin/users', 'POST', {
      name,
      email: email || null,
      calendarIds,
      groupNames,
    });
  }

  async function regenerateOwnLoginToken() {
    return request('/api/users/me/login-token/regenerate', 'POST', {});
  }

  async function getOwnLoginToken() {
    return request('/api/users/me/login-token', 'GET');
  }

  async function regenerateAdminUserLoginToken(userId) {
    return request(`/api/admin/users/${encodeURIComponent(userId)}/login-token/regenerate`, 'POST', {});
  }

  async function updateAdminUserServiceAccount(userId, serviceAccount) {
    return request(`/api/admin/users/${encodeURIComponent(userId)}/service-account`, 'PUT', {
      serviceAccount: Boolean(serviceAccount),
    });
  }

  async function deleteAdminUser(userId) {
    return request(`/api/admin/users/${encodeURIComponent(userId)}`, 'DELETE');
  }

  async function createAdminGroup(name) {
    return request('/api/admin/groups', 'POST', { name });
  }

  async function createAdminResourceForGroup(name, groupName) {
    return request(`/api/admin/groups/${encodeURIComponent(groupName)}/resources`, 'POST', { name });
  }

  async function renameAdminGroup(groupName, newName) {
    return request(`/api/admin/groups/${encodeURIComponent(groupName)}`, 'PUT', { name: newName });
  }

  async function deleteAdminGroup(groupName) {
    return request(`/api/admin/groups/${encodeURIComponent(groupName)}`, 'DELETE');
  }

  async function updateAdminCalendarGroup(calendarId, groupName) {
    return request(`/api/admin/calendars/${encodeURIComponent(calendarId)}/group`, 'PUT', { groupName });
  }

  async function updateAdminCalendarOrder(calendarIds) {
    return request('/api/admin/calendars/order', 'PUT', { calendarIds });
  }

  async function runAdminDatabaseTableVacuum(schemaName, tableName) {
    return request('/api/admin/postgres-vacuum/table', 'POST', { schemaName, tableName });
  }

  async function runAdminDatabaseVacuum() {
    return request('/api/admin/postgres-vacuum', 'POST', {});
  }

  async function removeAdminCalendarFromGroup(calendarId, groupName) {
    return request(`/api/admin/calendars/${encodeURIComponent(calendarId)}/groups/${encodeURIComponent(groupName)}`, 'DELETE');
  }

  let pendingGroupResourceCreateResolve = null;

  function closeGroupResourceCreateDialog(result) {
    if (pendingGroupResourceCreateResolve) {
      const resolve = pendingGroupResourceCreateResolve;
      pendingGroupResourceCreateResolve = null;
      resolve(result);
    }
    if (groupCreateResourceDialog && groupCreateResourceDialog.open) {
      groupCreateResourceDialog.close();
    }
  }

  function confirmGroupResourceCreation(groupName, resourceName) {
    return new Promise((resolve) => {
      pendingGroupResourceCreateResolve = resolve;
      if (groupCreateResourceTitle) {
        groupCreateResourceTitle.textContent = 'Create Resource';
      }
      if (groupCreateResourceMessage) {
        groupCreateResourceMessage.textContent = `Resource "${resourceName}" does not exist. Create it and add it to ${groupName}?`;
      }
      if (groupCreateResourceDialog) {
        groupCreateResourceDialog.showModal();
      } else {
        resolve(false);
      }
    });
  }

  async function loadAdminData() {
    if (!isAdminUser()) return;

    let usersData = null;
    let usersError = null;
    let performanceData = null;
    let performanceError = null;

    try {
      usersData = await request('/api/admin/users');
    } catch (error) {
      usersError = error instanceof Error ? error.message : String(error);
      console.error('Failed to load admin users:', error);
    }

    try {
      performanceData = await request('/api/admin/postgres-performance');
    } catch (error) {
      performanceError = error instanceof Error ? error.message : String(error);
      console.error('Failed to load postgres performance data:', error);
    }

    adminUsersData = usersData || { users: [], resources: [], resourceGroups: {}, groups: [], accessRequests: [], error: usersError };
    adminPerformanceData = performanceData || { summary: {}, activeQueries: [], topStatements: [], tableStats: [], error: performanceError };

    if (usersError || performanceError) {
      showSaveToast('Admin data warning', 'Some admin data could not be loaded. Check console logs.');
    }

    renderAdminPanel();
  }

  function renderAdminPanel() {
    if (!isAdminUser() || !adminUsersData) {
      if (adminGroupGrid) adminGroupGrid.innerHTML = '';
      if (adminUserGrid) adminUserGrid.innerHTML = '';
      if (adminAccessRequestsGrid) adminAccessRequestsGrid.innerHTML = '';
      if (adminPostgresPerformanceGrid) adminPostgresPerformanceGrid.innerHTML = '';
      return;
    }

    if (!adminGroupGrid || !adminUserGrid || !adminAccessRequestsGrid || !adminPostgresPerformanceGrid) {
      console.error('Admin panel containers are missing from the DOM.');
      return;
    }
    adminGroupGrid.innerHTML = '';
    adminUserGrid.innerHTML = '';
    adminAccessRequestsGrid.innerHTML = '';
    adminPostgresPerformanceGrid.innerHTML = '';

    const formatDuration = (milliseconds) => {
      const ms = Number(milliseconds || 0);
      if (!Number.isFinite(ms) || ms <= 0) return '0s';
      if (ms < 1000) return `${Math.round(ms)}ms`;
      const seconds = ms / 1000;
      if (seconds < 60) return `${seconds.toFixed(1)}s`;
      const minutes = Math.floor(seconds / 60);
      const remSeconds = Math.round(seconds % 60);
      return `${minutes}m ${remSeconds}s`;
    };

    const renderResourceCatalog = (container, resourceList, selectedIds, onAssign) => {
      container.innerHTML = '';
      for (const resource of resourceList) {
        const alreadyAssigned = selectedIds.includes(resource.id);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `admin-resource-option${alreadyAssigned ? ' assigned' : ''}`;
        button.textContent = alreadyAssigned
          ? `${resource.group || 'General'} / ${resource.name} (assigned)`
          : `${resource.group || 'General'} / ${resource.name}`;
        if (alreadyAssigned) {
          button.disabled = true;
          button.setAttribute('aria-disabled', 'true');
        } else {
          button.onclick = async () => {
            await onAssign(resource.id);
          };
        }
        container.appendChild(button);
      }
    };

    const userResources = adminUsersData.resources || [];
    const adminGroups = adminUsersData.groups || [];

    const calendarOrderCard = document.createElement('section');
    calendarOrderCard.className = 'admin-link-card';

    const calendarOrderTitle = document.createElement('strong');
    calendarOrderTitle.textContent = 'Calendar Order';

    const calendarOrderNote = document.createElement('div');
    calendarOrderNote.className = 'admin-helper';
    calendarOrderNote.textContent = 'Reorder calendars for the left sidebar navigation using the arrow controls, then save.';

    const calendarOrderList = document.createElement('div');
    calendarOrderList.className = 'admin-order-list';
    const calendarOrderItems = [...userResources].sort((left, right) => {
      const leftOrder = Number(left?.sortOrder ?? 0);
      const rightOrder = Number(right?.sortOrder ?? 0);
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return String(left?.name || '').localeCompare(String(right?.name || ''));
    });

    const renderCalendarOrderList = () => {
      calendarOrderList.innerHTML = '';
      for (let index = 0; index < calendarOrderItems.length; index += 1) {
        const resource = calendarOrderItems[index];
        const row = document.createElement('div');
        row.className = 'admin-order-row';

        const label = document.createElement('div');
        label.className = 'admin-order-label';
        label.style.color = resource.color || '#0f172a';

        const swatch = document.createElement('span');
        swatch.className = 'admin-order-swatch';
        swatch.style.background = resource.color || '#64748b';
        swatch.setAttribute('aria-hidden', 'true');

        const labelText = document.createElement('span');
        labelText.textContent = `${resource.group || 'General'} / ${resource.name}`;
        label.append(swatch, labelText);

        const controls = document.createElement('div');
        controls.className = 'admin-order-controls';

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'btn btn-neutral';
        editButton.textContent = 'Edit';
        editButton.onclick = () => {
          openCalendarEditorModal(resource.id, resource.name);
        };

        const upButton = document.createElement('button');
        upButton.type = 'button';
        upButton.className = 'btn btn-neutral';
        upButton.textContent = 'Up';
        upButton.disabled = index === 0;
        upButton.onclick = () => {
          if (index === 0) return;
          const previous = calendarOrderItems[index - 1];
          calendarOrderItems[index - 1] = resource;
          calendarOrderItems[index] = previous;
          renderCalendarOrderList();
        };

        const downButton = document.createElement('button');
        downButton.type = 'button';
        downButton.className = 'btn btn-neutral';
        downButton.textContent = 'Down';
        downButton.disabled = index === calendarOrderItems.length - 1;
        downButton.onclick = () => {
          if (index >= calendarOrderItems.length - 1) return;
          const next = calendarOrderItems[index + 1];
          calendarOrderItems[index + 1] = resource;
          calendarOrderItems[index] = next;
          renderCalendarOrderList();
        };

        controls.append(editButton, upButton, downButton);
        row.append(label, controls);
        calendarOrderList.appendChild(row);
      }
    };

    renderCalendarOrderList();

    const calendarOrderSaveButton = document.createElement('button');
    calendarOrderSaveButton.type = 'button';
    calendarOrderSaveButton.className = 'admin-save-button';
    calendarOrderSaveButton.textContent = 'Save Calendar Order';
    calendarOrderSaveButton.onclick = async () => {
      const oldLabel = calendarOrderSaveButton.textContent;
      calendarOrderSaveButton.disabled = true;
      calendarOrderSaveButton.textContent = 'Saving...';
      try {
        const orderedIds = calendarOrderItems.map((resource) => resource.id);
        await updateAdminCalendarOrder(orderedIds);

        const refreshedCalendars = await request('/api/calendars');
        allCalendars = Array.isArray(refreshedCalendars) ? refreshedCalendars : [];
        tokenAllowedCalendars = new Set(allCalendars.map((calendar) => calendar.id));
        renderSidebar();

        showSaveToast('Calendar order updated', 'Sidebar calendar order has been saved.');
        await loadAdminData();
      } catch (error) {
        showErrorToast('Calendar order save failed', error instanceof Error ? error.message : String(error));
      } finally {
        calendarOrderSaveButton.disabled = false;
        calendarOrderSaveButton.textContent = oldLabel;
      }
    };

    calendarOrderCard.append(calendarOrderTitle, calendarOrderNote, calendarOrderList, calendarOrderSaveButton);

    const groupCreateCard = document.createElement('section');
    groupCreateCard.className = 'admin-link-card';

    const groupCreateTitle = document.createElement('strong');
    groupCreateTitle.textContent = 'Create Group';

    const groupCreateRow = document.createElement('div');
    groupCreateRow.className = 'admin-editor-row';

    const groupCreateInput = document.createElement('input');
    groupCreateInput.className = 'admin-datalist-input';
    groupCreateInput.type = 'text';
    groupCreateInput.placeholder = 'New group name';

    const groupCreateButton = document.createElement('button');
    groupCreateButton.type = 'button';
    groupCreateButton.className = 'admin-save-button';
    groupCreateButton.textContent = 'Create';
    groupCreateButton.onclick = async () => {
      const groupName = groupCreateInput.value.trim();
      if (!groupName) {
        showSaveToast('Group name required', 'Enter a name before creating the group.');
        return;
      }
      try {
        await createAdminGroup(groupName);
        groupCreateInput.value = '';
        showSaveToast('Group created', `${groupName} was added.`);
        await loadAdminData();
      } catch (error) {
        showSaveToast('Group create failed', error instanceof Error ? error.message : String(error));
      }
    };

    groupCreateRow.appendChild(groupCreateInput);
    groupCreateRow.appendChild(groupCreateButton);
    groupCreateCard.appendChild(groupCreateTitle);
    groupCreateCard.appendChild(groupCreateRow);
    adminGroupGrid.appendChild(calendarOrderCard);
    adminGroupGrid.appendChild(groupCreateCard);

    for (const group of adminGroups) {
      const groupCard = document.createElement('section');
      groupCard.className = 'admin-link-card';

      const groupHeader = document.createElement('strong');
      groupHeader.textContent = group.name;

      const groupEditorRow = document.createElement('div');
      groupEditorRow.className = 'admin-editor-row';

      const groupRenameInput = document.createElement('input');
      groupRenameInput.className = 'admin-datalist-input';
      groupRenameInput.type = 'text';
      groupRenameInput.value = group.name;
      groupRenameInput.disabled = group.name === 'General';

      const groupRenameButton = document.createElement('button');
      groupRenameButton.type = 'button';
      groupRenameButton.className = 'admin-save-button';
      groupRenameButton.textContent = 'Rename';
      groupRenameButton.disabled = group.name === 'General';
      groupRenameButton.onclick = async () => {
        const nextName = groupRenameInput.value.trim();
        if (!nextName) {
          showSaveToast('Group name required', 'Enter a name before renaming the group.');
          return;
        }
        if (nextName === group.name) {
          return;
        }
        try {
          await renameAdminGroup(group.name, nextName);
          showSaveToast('Group renamed', `${group.name} is now ${nextName}.`);
          await loadAdminData();
        } catch (error) {
          showSaveToast('Rename failed', error instanceof Error ? error.message : String(error));
        }
      };

      const groupDeleteButton = document.createElement('button');
      groupDeleteButton.type = 'button';
      groupDeleteButton.className = 'admin-save-button';
      groupDeleteButton.textContent = 'Delete';
      groupDeleteButton.disabled = group.name === 'General';
      groupDeleteButton.onclick = async () => {
        const confirmed = window.confirm(`Delete group ${group.name}? Resources will move to General.`);
        if (!confirmed) return;
        try {
          await deleteAdminGroup(group.name);
          showSaveToast('Group deleted', `${group.name} was removed.`);
          await loadAdminData();
        } catch (error) {
          showSaveToast('Delete failed', error instanceof Error ? error.message : String(error));
        }
      };

      groupEditorRow.appendChild(groupRenameInput);
      groupEditorRow.appendChild(groupRenameButton);
      groupEditorRow.appendChild(groupDeleteButton);

      const groupMeta = document.createElement('div');
      groupMeta.className = 'admin-resource-count';
      const groupCount = Array.isArray(group.calendarIds) ? group.calendarIds.length : 0;
      groupMeta.textContent = `${groupCount} resource${groupCount === 1 ? '' : 's'}`;

      const groupAssignedLabel = document.createElement('div');
      groupAssignedLabel.className = 'admin-resource-group-label';
      groupAssignedLabel.textContent = 'Resources in group';

      const groupPills = document.createElement('div');
      groupPills.className = 'admin-resource-pills';
      const assignedResources = Array.isArray(group.calendars) ? group.calendars : [];
      if (assignedResources.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'admin-empty-state';
        emptyState.textContent = 'No resources assigned yet.';
        groupPills.appendChild(emptyState);
      } else {
        for (const resource of assignedResources) {
          const pill = document.createElement('span');
          pill.className = 'admin-pill';
          pill.textContent = `${resource.name}`;
          const canRemoveFromThisGroup = true;
          if (canRemoveFromThisGroup) {
            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'admin-pill-remove';
            removeButton.title = `Remove ${resource.name} from ${group.name}`;
            removeButton.textContent = 'x';
            removeButton.onclick = async () => {
              try {
                await removeAdminCalendarFromGroup(resource.id, group.name);
                showSaveToast('Resource updated', `${resource.name} removed from ${group.name}.`);
                await loadAdminData();
              } catch (error) {
                showSaveToast('Remove failed', error instanceof Error ? error.message : String(error));
              }
            };

            pill.appendChild(removeButton);
          }
          groupPills.appendChild(pill);
        }
      }

      const groupCalendarIds = Array.isArray(group.calendarIds) ? group.calendarIds : [];
      const availableResources = userResources.filter((resource) => !groupCalendarIds.includes(resource.id));
      const groupAddLabel = document.createElement('div');
      groupAddLabel.className = 'admin-resource-group-label';
      groupAddLabel.textContent = 'Add resources to this group';

      const groupAddRow = document.createElement('div');
      groupAddRow.className = 'admin-editor-row';

      const groupAddInput = document.createElement('input');
      groupAddInput.className = 'admin-datalist-input';
      groupAddInput.type = 'text';
      groupAddInput.placeholder = 'Type a resource name';

      const groupAddListId = `admin-group-add-options-${group.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
      groupAddInput.setAttribute('list', groupAddListId);

      const groupAddList = document.createElement('datalist');
      groupAddList.id = groupAddListId;
      for (const resource of availableResources) {
        const option = document.createElement('option');
        option.value = resource.name;
        option.label = `${resource.group || 'General'} resource`;
        groupAddList.appendChild(option);
      }

      const addResourceToGroup = async () => {
        const selectedName = groupAddInput.value.trim();
        if (!selectedName) {
          showSaveToast('Resource name required', 'Type a resource name before adding it to the group.');
          return;
        }
        try {
          const matchedResource = userResources.find((resource) => resource.name.toLowerCase() === selectedName.toLowerCase());
          if (matchedResource) {
            await updateAdminCalendarGroup(matchedResource.id, group.name);
            groupAddInput.value = '';
            showSaveToast('Resource moved', `${matchedResource.name} moved to ${group.name}.`);
            await loadAdminData();
            return;
          }

          const confirmed = await confirmGroupResourceCreation(group.name, selectedName);
          if (!confirmed) {
            return;
          }

          const created = await createAdminResourceForGroup(selectedName, group.name);
          groupAddInput.value = '';
          showSaveToast(
            created && created.created ? 'Resource created' : 'Resource added',
            `${selectedName} was added to ${group.name}.`,
          );
          await loadAdminData();
        } catch (error) {
          showSaveToast('Move failed', error instanceof Error ? error.message : String(error));
        }
      };

      const groupAddButton = document.createElement('button');
      groupAddButton.type = 'button';
      groupAddButton.className = 'admin-save-button';
      groupAddButton.textContent = 'Add';
      groupAddButton.onclick = addResourceToGroup;

      groupAddInput.addEventListener('keydown', async (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          await addResourceToGroup();
        }
      });

      groupAddRow.appendChild(groupAddInput);
      groupAddRow.appendChild(groupAddButton);

      groupCard.appendChild(groupHeader);
      groupCard.appendChild(groupMeta);
      if (group.name === 'General') {
        const defaultNote = document.createElement('div');
        defaultNote.className = 'admin-resource-group-label';
        defaultNote.textContent = 'Default group';
        groupCard.appendChild(defaultNote);
      } else {
        groupCard.appendChild(groupEditorRow);
      }
      groupCard.appendChild(groupAssignedLabel);
      groupCard.appendChild(groupPills);
      groupCard.appendChild(groupAddLabel);
      groupCard.appendChild(groupAddRow);
      groupCard.appendChild(groupAddList);
      adminGroupGrid.appendChild(groupCard);
    }

    const userCreateCard = document.createElement('section');
    userCreateCard.className = 'admin-link-card';

    const userCreateTitle = document.createElement('strong');
    userCreateTitle.textContent = 'Create User (No Google Required)';

    const userCreateRow = document.createElement('div');
    userCreateRow.className = 'admin-editor-row';

    const userCreateNameInput = document.createElement('input');
    userCreateNameInput.className = 'admin-datalist-input';
    userCreateNameInput.placeholder = 'Display name (required)';

    const userCreateEmailInput = document.createElement('input');
    userCreateEmailInput.className = 'admin-datalist-input';
    userCreateEmailInput.placeholder = 'Email (optional, local placeholder if empty)';

    userCreateRow.append(userCreateNameInput, userCreateEmailInput);

    const userCreateResourceInput = document.createElement('input');
    userCreateResourceInput.className = 'admin-datalist-input';
    const userCreateListId = 'admin-user-create-options';
    userCreateResourceInput.setAttribute('list', userCreateListId);
    userCreateResourceInput.placeholder = 'Optional: add calendar or group access before create';

    const userCreateList = document.createElement('datalist');
    userCreateList.id = userCreateListId;
    for (const group of adminGroups) {
      const option = document.createElement('option');
      option.value = `Group: ${group.name}`;
      userCreateList.appendChild(option);
    }
    for (const resource of userResources) {
      const option = document.createElement('option');
      option.value = `Calendar: ${resource.name}`;
      userCreateList.appendChild(option);
    }

    const stagedUserResourceIds = [];
    const stagedUserGroupNames = [];
    const stagedUserAccessPills = document.createElement('div');
    stagedUserAccessPills.className = 'admin-resource-pills';
    const renderStagedUserAccessPills = () => {
      stagedUserAccessPills.innerHTML = '';
      for (const resourceId of stagedUserResourceIds) {
        const pill = document.createElement('span');
        pill.className = 'admin-pill';
        pill.textContent = resourceName(resourceId);
        stagedUserAccessPills.appendChild(pill);
      }
      for (const groupName of stagedUserGroupNames) {
        const pill = document.createElement('span');
        pill.className = 'admin-pill';

        const label = document.createElement('span');
        label.textContent = groupName;

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'admin-pill-remove';
        removeButton.title = `Remove ${groupName}`;
        removeButton.setAttribute('aria-label', removeButton.title);
        removeButton.textContent = 'x';
        removeButton.onclick = () => {
          const nextGroups = stagedUserGroupNames.filter(name => name !== groupName);
          stagedUserGroupNames.splice(0, stagedUserGroupNames.length, ...nextGroups);
          renderStagedUserAccessPills();
        };

        pill.append(label, removeButton);
        stagedUserAccessPills.appendChild(pill);
      }
    };

    const stageUserAccessButton = document.createElement('button');
    stageUserAccessButton.type = 'button';
    stageUserAccessButton.className = 'btn btn-neutral';
    stageUserAccessButton.textContent = 'Add Access';
    stageUserAccessButton.onclick = () => {
      const value = userCreateResourceInput.value.trim();
      if (!value) return;

      const normalized = value.toLowerCase();
      const groupPrefix = 'group:';
      const calendarPrefix = 'calendar:';
      const groupLookup = normalized.startsWith(groupPrefix)
        ? value.slice(groupPrefix.length).trim()
        : value;
      const calendarLookup = normalized.startsWith(calendarPrefix)
        ? value.slice(calendarPrefix.length).trim()
        : value;

      let matchedGroup = null;
      let matchedCalendar = null;
      if (!normalized.startsWith(calendarPrefix)) {
        matchedGroup = adminGroups.find(group => group.name.toLowerCase() === groupLookup.toLowerCase()) || null;
      }
      if (!normalized.startsWith(groupPrefix)) {
        matchedCalendar = userResources.find(resource => resource.name.toLowerCase() === calendarLookup.toLowerCase()) || null;
      }

      if (!matchedGroup && !matchedCalendar) {
        showSaveToast('Not found', `No group or calendar matches "${value}".`);
        return;
      }

      if (matchedGroup && !stagedUserGroupNames.includes(matchedGroup.name)) {
        stagedUserGroupNames.push(matchedGroup.name);
        stagedUserGroupNames.sort((left, right) => left.localeCompare(right));
      }
      if (matchedCalendar && !stagedUserResourceIds.includes(matchedCalendar.id)) {
        stagedUserResourceIds.push(matchedCalendar.id);
      }
      stagedUserResourceIds.sort((left, right) => resourceName(left).localeCompare(resourceName(right)));
      userCreateResourceInput.value = '';
      renderStagedUserAccessPills();
    };

    const createUserButton = document.createElement('button');
    createUserButton.type = 'button';
    createUserButton.className = 'btn btn-primary';
    createUserButton.textContent = 'Create User';

    createUserButton.onclick = async () => {
      const name = userCreateNameInput.value.trim();
      const email = userCreateEmailInput.value.trim();
      if (!name) {
        showSaveToast('Missing name', 'User name is required.');
        return;
      }

      const created = await createAdminUser(name, email, stagedUserResourceIds, stagedUserGroupNames);
      const loginUrl = created && created.loginUrl ? created.loginUrl : '';
      const tokenValue = created && created.token ? created.token : 'unknown';
      showSaveToast('User created', loginUrl || `Login token: ${tokenValue}`);

      userCreateNameInput.value = '';
      userCreateEmailInput.value = '';
      userCreateResourceInput.value = '';
      stagedUserResourceIds.splice(0, stagedUserResourceIds.length);
      stagedUserGroupNames.splice(0, stagedUserGroupNames.length);
      renderStagedUserAccessPills();
      await loadAdminData();
    };

    const userCreateButtons = document.createElement('div');
    userCreateButtons.className = 'btn-group';
    userCreateButtons.append(stageUserAccessButton, createUserButton);

    const userCreateResourceRow = document.createElement('div');
    userCreateResourceRow.className = 'admin-editor-row';
    userCreateResourceRow.append(userCreateResourceInput, userCreateButtons);

    userCreateCard.append(
      userCreateTitle,
      userCreateRow,
      userCreateList,
      userCreateResourceRow,
      stagedUserAccessPills,
    );
    adminUserGrid.appendChild(userCreateCard);

    const usersToRender = Array.isArray(adminUsersData.users) ? adminUsersData.users : [];
    for (const user of usersToRender) {
      const card = document.createElement('section');
      card.className = 'admin-link-card';

      const selectedIds = Array.isArray(user.calendarIds) ? [...user.calendarIds] : [];
      const selectedGroupNames = Array.isArray(user.groupNames)
        ? [...user.groupNames]
        : (user.groupName ? [user.groupName] : []);
      const calendarsByGroupName = new Map(
        (adminGroups || []).map(group => [group.name, new Set(Array.isArray(group.calendarIds) ? group.calendarIds : [])]),
      );

      const head = document.createElement('div');
      head.className = 'admin-link-head';

      const titleWrap = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = user.name || user.email || 'Unnamed user';
      const emailLine = document.createElement('div');
      emailLine.className = 'admin-link-token';
      emailLine.textContent = user.email || 'No email';
      const meta = document.createElement('div');
      meta.className = 'admin-link-meta';
      meta.textContent = `Last login: ${user.lastLogin || 'never'}`;

      const loginLinkWrap = document.createElement('div');
      loginLinkWrap.className = 'admin-link-meta';
      const loginLink = document.createElement('a');
      loginLink.href = user.loginUrl || '#';
      loginLink.textContent = user.loginUrl || 'No login URL';
      loginLink.target = '_blank';
      loginLink.rel = 'noreferrer noopener';
      const copyLoginLink = document.createElement('a');
      copyLoginLink.href = '#';
      copyLoginLink.className = 'admin-inline-link';
      copyLoginLink.textContent = 'Copy to clipboard';
      const syncLoginLinkActions = () => {
        const hasUrl = Boolean(user.loginUrl);
        if (!hasUrl) {
          loginLink.setAttribute('aria-disabled', 'true');
          loginLink.style.pointerEvents = 'none';
          loginLink.style.opacity = '0.65';
          copyLoginLink.setAttribute('aria-disabled', 'true');
          return;
        }
        loginLink.removeAttribute('aria-disabled');
        loginLink.style.pointerEvents = '';
        loginLink.style.opacity = '';
        copyLoginLink.removeAttribute('aria-disabled');
      };
      copyLoginLink.onclick = async (event) => {
        event.preventDefault();
        if (!user.loginUrl) {
          return;
        }
        try {
          await navigator.clipboard.writeText(user.loginUrl);
          showSaveToast('Copied', 'Login link copied to clipboard.');
        } catch (error) {
          showErrorToast('Copy failed', error instanceof Error ? error.message : String(error));
        }
      };
      if (!user.loginUrl) {
        copyLoginLink.setAttribute('aria-disabled', 'true');
      }
      syncLoginLinkActions();
      loginLinkWrap.append(loginLink, copyLoginLink);

      const regenerateLoginLinkButton = document.createElement('button');
      regenerateLoginLinkButton.type = 'button';
      regenerateLoginLinkButton.className = 'btn btn-neutral';
      regenerateLoginLinkButton.textContent = 'Regenerate login string';
      regenerateLoginLinkButton.onclick = async () => {
        const oldLabel = regenerateLoginLinkButton.textContent;
        regenerateLoginLinkButton.disabled = true;
        regenerateLoginLinkButton.textContent = 'Regenerating...';
        try {
          const result = await regenerateAdminUserLoginToken(user.id);
          const nextToken = String(result?.loginToken || '').trim();
          const nextUrl = String(result?.loginUrl || '').trim();
          user.loginToken = nextToken;
          user.loginUrl = nextUrl;
          loginLink.href = nextUrl || '#';
          loginLink.textContent = nextUrl || 'No login URL';
          syncLoginLinkActions();
          showSaveToast('Login string regenerated', `${user.name || user.email || 'User'} now has a new login link.`);
        } catch (error) {
          showErrorToast('Regenerate failed', error instanceof Error ? error.message : String(error));
        } finally {
          regenerateLoginLinkButton.disabled = false;
          regenerateLoginLinkButton.textContent = oldLabel;
        }
      };

      const deleteUserButton = document.createElement('button');
      deleteUserButton.type = 'button';
      deleteUserButton.className = 'btn btn-danger';
      deleteUserButton.textContent = 'Delete user';
      deleteUserButton.disabled = Boolean(currentUser && currentUser.id === user.id);
      deleteUserButton.title = deleteUserButton.disabled
        ? 'You cannot delete your own account.'
        : 'Delete this user account.';
      deleteUserButton.onclick = async () => {
        const targetLabel = user.name || user.email || 'this user';
        const confirmed = window.confirm(`Delete ${targetLabel}? This cannot be undone.`);
        if (!confirmed) {
          return;
        }
        const oldLabel = deleteUserButton.textContent;
        deleteUserButton.disabled = true;
        deleteUserButton.textContent = 'Deleting...';
        try {
          await deleteAdminUser(user.id);
          showSaveToast('User deleted', `${targetLabel} was removed.`);
          await loadAdminData();
        } catch (error) {
          showErrorToast('Delete failed', error instanceof Error ? error.message : String(error));
          deleteUserButton.disabled = Boolean(currentUser && currentUser.id === user.id);
        } finally {
          deleteUserButton.textContent = oldLabel;
        }
      };

      titleWrap.append(title, emailLine, meta, loginLinkWrap, regenerateLoginLinkButton, deleteUserButton);

      const roleBadge = document.createElement('span');
      roleBadge.className = `admin-user-role ${user.role === 'admin' ? 'admin' : 'user'}`;
      roleBadge.textContent = user.role || 'user';

      const accountModeWrap = document.createElement('label');
      accountModeWrap.className = 'admin-helper';
      accountModeWrap.style.display = 'inline-flex';
      accountModeWrap.style.alignItems = 'center';
      accountModeWrap.style.gap = '8px';

      const accountModeToggle = document.createElement('input');
      accountModeToggle.type = 'checkbox';
      accountModeToggle.checked = Boolean(user.serviceAccount);

      const accountModeLabel = document.createElement('span');
      accountModeLabel.textContent = 'Service account';

      accountModeWrap.append(accountModeToggle, accountModeLabel);
      accountModeToggle.addEventListener('change', async () => {
        const nextValue = Boolean(accountModeToggle.checked);
        accountModeToggle.disabled = true;
        try {
          await updateAdminUserServiceAccount(user.id, nextValue);
          user.serviceAccount = nextValue;
          showSaveToast('Account type updated', nextValue ? 'Service account enabled.' : 'Service account disabled.');
          if (currentUser && currentUser.id === user.id) {
            currentUser.serviceAccount = nextValue;
            renderSidebar();
          }
        } catch (error) {
          accountModeToggle.checked = Boolean(user.serviceAccount);
          showErrorToast('Update failed', error instanceof Error ? error.message : String(error));
        } finally {
          accountModeToggle.disabled = false;
        }
      });

      const calendarSectionTitle = document.createElement('div');
      calendarSectionTitle.className = 'admin-section-title';
      calendarSectionTitle.textContent = 'Calendar access';

      const calendarPills = document.createElement('div');
      calendarPills.className = 'admin-resource-pills';
      const renderCalendarPills = () => {
        calendarPills.innerHTML = '';
        for (const resourceId of selectedIds) {
          const pill = document.createElement('span');
          pill.className = 'admin-pill';

          const label = document.createElement('span');
          label.textContent = resourceName(resourceId);

          const removeButton = document.createElement('button');
          removeButton.type = 'button';
          removeButton.className = 'admin-pill-remove';
          removeButton.title = `Remove ${resourceName(resourceId)} from ${user.name || user.email}`;
          removeButton.setAttribute('aria-label', removeButton.title);
          removeButton.textContent = 'x';
          removeButton.onclick = async () => {
            const linkedGroups = selectedGroupNames.filter(groupName => {
              const groupCalendarIds = calendarsByGroupName.get(groupName);
              return groupCalendarIds ? groupCalendarIds.has(resourceId) : false;
            });
            let nextGroupNames = [...selectedGroupNames];
            if (linkedGroups.length > 0) {
              const removeLinkedGroups = await requestLinkedRemovalDecision({
                title: 'Calendar Also Granted By Group',
                message: `"${resourceName(resourceId)}" is also granted by group membership: ${linkedGroups.join(', ')}.`,
                keepLabel: `Keep ${shortLinkedLabel(linkedGroups, 'groups')}`,
                removeLabel: `Remove ${shortLinkedLabel(linkedGroups, 'groups')}`,
              });
              if (removeLinkedGroups) {
                nextGroupNames = selectedGroupNames.filter(groupName => !linkedGroups.includes(groupName));
              }
            }
            const nextIds = selectedIds.filter(id => id !== resourceId);
            selectedIds.splice(0, selectedIds.length, ...nextIds);
            selectedGroupNames.splice(0, selectedGroupNames.length, ...nextGroupNames);
            await saveAdminUserResources(user.id, selectedIds, selectedGroupNames);
            user.calendarIds = [...selectedIds];
            user.groupNames = [...selectedGroupNames];
            user.groupName = selectedGroupNames[0] || null;
            renderCalendarPills();
            renderGroupPills();
          };

          pill.append(label, removeButton);
          calendarPills.appendChild(pill);
        }
      };

      const groupSectionTitle = document.createElement('div');
      groupSectionTitle.className = 'admin-section-title';
      groupSectionTitle.textContent = 'Group membership';

      const groupPills = document.createElement('div');
      groupPills.className = 'admin-resource-pills';
      const renderGroupPills = () => {
        groupPills.innerHTML = '';
        for (const groupName of selectedGroupNames) {
          const pill = document.createElement('span');
          pill.className = 'admin-pill';

          const label = document.createElement('span');
          label.textContent = groupName;

          const removeButton = document.createElement('button');
          removeButton.type = 'button';
          removeButton.className = 'admin-pill-remove';
          removeButton.title = `Remove ${groupName} from ${user.name || user.email}`;
          removeButton.setAttribute('aria-label', removeButton.title);
          removeButton.textContent = 'x';
          removeButton.onclick = async () => {
            const calendarsFromGroup = Array.from(calendarsByGroupName.get(groupName) || []);
            const linkedDirectCalendars = selectedIds.filter(calendarId => calendarsFromGroup.includes(calendarId));
            let nextIds = [...selectedIds];
            if (linkedDirectCalendars.length > 0) {
              const linkedCalendarNames = linkedDirectCalendars.map(calendarId => resourceName(calendarId));
              const removeLinkedCalendars = await requestLinkedRemovalDecision({
                title: 'Group Includes Direct Calendars',
                message: `"${groupName}" also contains directly assigned calendars: ${linkedCalendarNames.join(', ')}.`,
                keepLabel: `Keep ${shortLinkedLabel(linkedCalendarNames, 'calendars')}`,
                removeLabel: `Remove ${shortLinkedLabel(linkedCalendarNames, 'calendars')}`,
              });
              if (removeLinkedCalendars) {
                nextIds = selectedIds.filter(calendarId => !linkedDirectCalendars.includes(calendarId));
              }
            }
            const nextGroups = selectedGroupNames.filter(name => name !== groupName);
            selectedIds.splice(0, selectedIds.length, ...nextIds);
            selectedGroupNames.splice(0, selectedGroupNames.length, ...nextGroups);
            await saveAdminUserResources(user.id, selectedIds, selectedGroupNames);
            user.calendarIds = [...selectedIds];
            user.groupNames = [...selectedGroupNames];
            user.groupName = selectedGroupNames[0] || null;
            renderCalendarPills();
            renderGroupPills();
          };

          pill.append(label, removeButton);
          groupPills.appendChild(pill);
        }
      };

      const editorRow = document.createElement('div');
      editorRow.className = 'admin-editor-row';

      const input = document.createElement('input');
      const datalistId = `admin-user-access-options-${user.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
      input.className = 'admin-datalist-input';
      input.setAttribute('list', datalistId);
      input.placeholder = 'Type a group or calendar name';

      const datalist = document.createElement('datalist');
      datalist.id = datalistId;
      for (const group of adminGroups) {
        const option = document.createElement('option');
        option.value = `Group: ${group.name}`;
        datalist.appendChild(option);
      }
      for (const resource of userResources) {
        const option = document.createElement('option');
        option.value = `Calendar: ${resource.name}`;
        datalist.appendChild(option);
      }

      const addButton = document.createElement('button');
      addButton.type = 'button';
      addButton.className = 'btn btn-primary';
      addButton.textContent = 'Add';
      addButton.onclick = async () => {
        const value = input.value.trim();
        if (!value) return;

        const normalized = value.toLowerCase();
        const groupPrefix = 'group:';
        const calendarPrefix = 'calendar:';
        const groupLookup = normalized.startsWith(groupPrefix)
          ? value.slice(groupPrefix.length).trim()
          : value;
        const calendarLookup = normalized.startsWith(calendarPrefix)
          ? value.slice(calendarPrefix.length).trim()
          : value;

        let groupMatched = null;
        let calendarMatched = null;
        if (!normalized.startsWith(calendarPrefix)) {
          groupMatched = adminGroups.find(group => group.name.toLowerCase() === groupLookup.toLowerCase()) || null;
        }
        if (!normalized.startsWith(groupPrefix)) {
          calendarMatched = userResources.find(resource => resource.name.toLowerCase() === calendarLookup.toLowerCase()) || null;
        }

        if (!groupMatched && !calendarMatched) {
          showSaveToast('Not found', `No group or calendar matches "${value}".`);
          return;
        }

        if (groupMatched && !selectedGroupNames.includes(groupMatched.name)) {
          selectedGroupNames.push(groupMatched.name);
          selectedGroupNames.sort((left, right) => left.localeCompare(right));
        }
        if (calendarMatched && !selectedIds.includes(calendarMatched.id)) {
          selectedIds.push(calendarMatched.id);
          selectedIds.sort((left, right) => resourceName(left).localeCompare(resourceName(right)));
        }

        await saveAdminUserResources(user.id, selectedIds, selectedGroupNames);
        user.calendarIds = [...selectedIds];
        user.groupNames = [...selectedGroupNames];
        user.groupName = selectedGroupNames[0] || null;
        renderCalendarPills();
        renderGroupPills();
        input.value = '';
      };

      editorRow.append(input, addButton);

      const helper = document.createElement('div');
      helper.className = 'admin-helper';
      helper.textContent = 'Remove approvals with x, or add either a group or calendar from the single Add box.';

      const userMetaControls = document.createElement('div');
      userMetaControls.style.display = 'grid';
      userMetaControls.style.justifyItems = 'end';
      userMetaControls.style.gap = '8px';
      userMetaControls.append(roleBadge, accountModeWrap);

      head.append(titleWrap, userMetaControls);
      renderCalendarPills();
      renderGroupPills();

      card.append(head, calendarSectionTitle, calendarPills, groupSectionTitle, groupPills, datalist, editorRow, helper);
      adminUserGrid.appendChild(card);
    }

    if (usersToRender.length === 0) {
      const emptyUsers = document.createElement('div');
      emptyUsers.className = 'admin-helper';
      emptyUsers.textContent = adminUsersData.error
        ? `Could not load users: ${adminUsersData.error}`
        : 'No users found.';
      adminUserGrid.appendChild(emptyUsers);
    }

    const accessRequests = Array.isArray(adminUsersData.accessRequests) ? adminUsersData.accessRequests : [];
    if (accessRequests.length === 0) {
      const emptyRequests = document.createElement('div');
      emptyRequests.className = 'admin-helper';
      emptyRequests.textContent = 'No access requests.';
      adminAccessRequestsGrid.appendChild(emptyRequests);
    } else {
      for (const accessRequest of accessRequests) {
        const card = document.createElement('section');
        card.className = 'admin-link-card';

        const head = document.createElement('div');
        head.className = 'admin-link-head';

        const titleWrap = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = accessRequest.targetType === 'group'
          ? `Group request: ${accessRequest.targetLabel}`
          : `Calendar request: ${accessRequest.targetLabel}`;
        const meta = document.createElement('div');
        meta.className = 'admin-link-meta';
        meta.textContent = `Requested by ${accessRequest.requesterName || accessRequest.requesterEmail || 'Unknown user'}`;
        const extra = document.createElement('div');
        extra.className = 'admin-link-token';
        extra.textContent = `Requested at: ${accessRequest.requestedAt || 'unknown'}`;
        const reviewLog = document.createElement('div');
        reviewLog.className = 'admin-helper';
        if (accessRequest.status === 'approved') {
          if (accessRequest.approvalSource === 'auto_link_addition') {
            reviewLog.textContent = 'Approval log: auto approved via link addition.';
          } else if (accessRequest.approvalSource === 'manual') {
            const reviewerLabel = accessRequest.reviewedByName || accessRequest.reviewedByEmail || accessRequest.reviewedByUserId || 'Unknown approver';
            reviewLog.textContent = `Approval log: manually approved by ${reviewerLabel}.`;
          } else {
            reviewLog.textContent = 'Approval log: approved.';
          }
        } else {
          reviewLog.textContent = 'Approval log: pending review.';
        }
        const status = document.createElement('div');
        const accessStatus = accessRequest.status === 'approved'
          ? 'approved'
          : accessRequest.status === 'hidden'
            ? 'hidden'
            : 'requested';
        status.className = `admin-status-pill admin-status-pill--${accessStatus}`;
        status.textContent = accessStatus === 'approved' ? 'Approved' : accessStatus === 'hidden' ? 'Hidden' : 'Requested';
        titleWrap.append(title, meta, extra, reviewLog, status);

        const approveButton = document.createElement('button');
        approveButton.type = 'button';
        approveButton.className = 'btn btn-primary';
        const declineButton = document.createElement('button');
        declineButton.type = 'button';
        declineButton.className = 'btn btn-danger';
        declineButton.textContent = 'Decline';
        declineButton.style.display = 'none';
        if (accessRequest.status === 'hidden') {
          approveButton.textContent = 'Hidden';
          approveButton.disabled = true;
        } else if (accessRequest.status === 'approved') {
          approveButton.textContent = 'Approved';
          approveButton.disabled = true;
        } else {
          approveButton.textContent = 'Approve';
          declineButton.style.display = 'inline-flex';
          approveButton.onclick = async () => {
            try {
              await request(`/api/admin/access-requests/${encodeURIComponent(accessRequest.id)}/approve`, 'POST');
              showSaveToast('Access approved', `${accessRequest.requesterName || 'User'} now has access.`);
              await loadAdminData();
            } catch (error) {
              showErrorToast('Approval failed', error instanceof Error ? error.message : String(error));
            }
          };
          declineButton.onclick = async () => {
            try {
              await request(`/api/admin/access-requests/${encodeURIComponent(accessRequest.id)}/decline`, 'POST');
              showSaveToast('Request declined', `${accessRequest.requesterName || 'User'} request was declined.`);
              await loadAdminData();
            } catch (error) {
              showErrorToast('Decline failed', error instanceof Error ? error.message : String(error));
            }
          };
        }

        const actionWrap = document.createElement('div');
        actionWrap.className = 'btn-group';
        actionWrap.append(declineButton, approveButton);
        head.append(titleWrap, actionWrap);
        card.append(head);

        const detail = document.createElement('div');
        detail.className = 'admin-helper';
        detail.textContent = accessRequest.targetType === 'group'
          ? `Approving this request grants access to all calendars in ${accessRequest.targetLabel}.`
          : `Approving this request grants access to ${accessRequest.targetLabel}.`;
        card.appendChild(detail);

        adminAccessRequestsGrid.appendChild(card);
      }
    }

    const perf = adminPerformanceData || {};
    const summary = perf.summary || {};
    const activeQueries = Array.isArray(perf.activeQueries) ? perf.activeQueries : [];
    const topStatements = Array.isArray(perf.topStatements) ? perf.topStatements : [];
    const tableStats = Array.isArray(perf.tableStats) ? perf.tableStats : [];

    const summaryCard = document.createElement('section');
    summaryCard.className = 'admin-link-card';
    const summaryTitle = document.createElement('strong');
    summaryTitle.textContent = 'Database Summary';
    const summaryActions = document.createElement('div');
    summaryActions.className = 'admin-editor-row';
    summaryActions.style.gridTemplateColumns = '1fr auto';
    const summarySpacer = document.createElement('div');
    const refreshPerfButton = document.createElement('button');
    refreshPerfButton.type = 'button';
    refreshPerfButton.className = 'admin-save-button';
    refreshPerfButton.textContent = 'Refresh performance logs';
    refreshPerfButton.addEventListener('click', async () => {
      const oldLabel = refreshPerfButton.textContent;
      refreshPerfButton.disabled = true;
      refreshPerfButton.textContent = 'Refreshing...';
      try {
        await loadAdminData();
      } finally {
        refreshPerfButton.disabled = false;
        refreshPerfButton.textContent = oldLabel;
      }
    });
    const vacuumPerfButton = document.createElement('button');
    vacuumPerfButton.type = 'button';
    vacuumPerfButton.className = 'admin-save-button';
    vacuumPerfButton.textContent = 'Run VACUUM';
    vacuumPerfButton.addEventListener('click', async () => {
      const oldLabel = vacuumPerfButton.textContent;
      vacuumPerfButton.disabled = true;
      refreshPerfButton.disabled = true;
      vacuumPerfButton.textContent = 'Running...';
      try {
        await runAdminDatabaseVacuum();
        showSaveToast('VACUUM completed', 'Database maintenance finished successfully.');
        await loadAdminData();
      } catch (error) {
        showErrorToast('VACUUM failed', error instanceof Error ? error.message : String(error));
      } finally {
        vacuumPerfButton.disabled = false;
        refreshPerfButton.disabled = false;
        vacuumPerfButton.textContent = oldLabel;
      }
    });
    summaryActions.append(summarySpacer, vacuumPerfButton, refreshPerfButton);
    const summaryMeta = document.createElement('div');
    summaryMeta.className = 'admin-helper';
    const capturedAt = String(perf.capturedAt || '').trim();
    summaryMeta.textContent = capturedAt ? `Captured at ${capturedAt}` : 'No timestamp available.';

    const lastAutovacuum = String(summary.lastAutovacuum || '').trim();
    const lastAutoanalyze = String(summary.lastAutoanalyze || '').trim();
    const lastVacuum = String(summary.lastVacuum || '').trim();
    const lastAnalyze = String(summary.lastAnalyze || '').trim();

    const summaryGrid = document.createElement('div');
    summaryGrid.className = 'admin-resource-pills';
    const summaryItems = [
      ['Connections', Number(summary.connections || 0)],
      ['Autovacuum workers', Number(summary.autovacuumWorkers || 0)],
      ['Tables', Number(summary.tableCount || 0)],
      ['Live tuples', Number(summary.liveTuples || 0)],
      ['Dead tuples', Number(summary.deadTuples || 0)],
      ['Autovacuum runs', Number(summary.autovacuumCount || 0)],
      ['Autoanalyze runs', Number(summary.autoanalyzeCount || 0)],
      ['Vacuum runs', Number(summary.vacuumCount || 0)],
      ['Analyze runs', Number(summary.analyzeCount || 0)],
      ['Active sessions', Number(summary.activeSessions || 0)],
      ['Blocked sessions', Number(summary.blockedSessions || 0)],
      ['Idle in transaction', Number(summary.idleInTransaction || 0)],
      ['Max transaction age', formatDuration(summary.maxTransactionAgeMs)],
      ['Cache hit ratio', `${Number(summary.cacheHitRatioPct || 0).toFixed(2)}%`],
      ['Commits', Number(summary.xactCommit || 0)],
      ['Rollbacks', Number(summary.xactRollback || 0)],
      ['Deadlocks', Number(summary.deadlocks || 0)],
      ['Temp files', Number(summary.tempFiles || 0)],
    ];
    for (const [label, value] of summaryItems) {
      const pill = document.createElement('span');
      pill.className = 'admin-pill';
      const labelSpan = document.createElement('span');
      labelSpan.textContent = `${label}: ${value}`;
      pill.append(labelSpan);
      summaryGrid.appendChild(pill);
    }
    summaryCard.append(summaryTitle, summaryActions, summaryMeta, summaryGrid);
    if (lastAutovacuum || lastAutoanalyze || lastVacuum || lastAnalyze) {
      const timings = document.createElement('div');
      timings.className = 'admin-helper';
      const entries = [];
      if (lastAutovacuum) entries.push(`Last autovacuum: ${new Date(lastAutovacuum).toLocaleString()}`);
      if (lastAutoanalyze) entries.push(`Last autoanalyze: ${new Date(lastAutoanalyze).toLocaleString()}`);
      if (lastVacuum) entries.push(`Last vacuum: ${new Date(lastVacuum).toLocaleString()}`);
      if (lastAnalyze) entries.push(`Last analyze: ${new Date(lastAnalyze).toLocaleString()}`);
      timings.textContent = entries.join(' · ');
      summaryCard.appendChild(timings);
    }
    adminPostgresPerformanceGrid.appendChild(summaryCard);

    const vacuumCard = document.createElement('section');
    vacuumCard.className = 'admin-link-card';
    const vacuumTitle = document.createElement('strong');
    vacuumTitle.textContent = 'Table Vacuum Breakdown';
    const vacuumNote = document.createElement('div');
    vacuumNote.className = 'admin-helper';
    vacuumNote.textContent = 'Tables are ordered by dead tuples. Use the button on a row to run VACUUM ANALYZE for that table only.';
    const vacuumList = document.createElement('div');
    vacuumList.className = 'admin-vacuum-list';

    if (tableStats.length === 0) {
      const emptyVacuum = document.createElement('div');
      emptyVacuum.className = 'admin-helper';
      emptyVacuum.textContent = 'No table statistics available.';
      vacuumList.appendChild(emptyVacuum);
    } else {
      for (const tableStat of tableStats) {
        const row = document.createElement('div');
        row.className = 'admin-vacuum-row';

        const label = document.createElement('div');
        label.className = 'admin-vacuum-label';
        const tableName = document.createElement('div');
        tableName.className = 'admin-vacuum-table-name';
        tableName.textContent = `${String(tableStat.schemaName || 'public')}.${String(tableStat.tableName || '')}`;
        const tableMeta = document.createElement('div');
        tableMeta.className = 'admin-vacuum-table-meta';
        const lastAutovacuum = String(tableStat.lastAutovacuum || '').trim();
        const lastAutoanalyze = String(tableStat.lastAutoanalyze || '').trim();
        tableMeta.textContent = lastAutovacuum || lastAutoanalyze
          ? [
              lastAutovacuum ? `autovacuum ${new Date(lastAutovacuum).toLocaleString()}` : '',
              lastAutoanalyze ? `autoanalyze ${new Date(lastAutoanalyze).toLocaleString()}` : '',
            ].filter(Boolean).join(' · ')
          : 'No auto maintenance timestamp recorded.';
        label.append(tableName, tableMeta);

        const liveTuples = document.createElement('div');
        liveTuples.className = 'admin-vacuum-stat';
        liveTuples.textContent = `Live: ${Number(tableStat.liveTuples || 0)}`;

        const deadTuples = document.createElement('div');
        deadTuples.className = 'admin-vacuum-stat';
        deadTuples.textContent = `Dead: ${Number(tableStat.deadTuples || 0)}`;

        const vacuumCounts = document.createElement('div');
        vacuumCounts.className = 'admin-vacuum-stat';
        vacuumCounts.textContent = `Vacuum: ${Number(tableStat.vacuumCount || 0)} / Autovacuum: ${Number(tableStat.autovacuumCount || 0)}`;

        const tableButton = document.createElement('button');
        tableButton.type = 'button';
        tableButton.className = 'admin-save-button';
        tableButton.textContent = 'Vacuum Table';
        tableButton.disabled = !tableStat.tableName;
        tableButton.addEventListener('click', async () => {
          const oldLabel = tableButton.textContent;
          tableButton.disabled = true;
          refreshPerfButton.disabled = true;
          vacuumPerfButton.disabled = true;
          tableButton.textContent = 'Running...';
          try {
            await runAdminDatabaseTableVacuum(tableStat.schemaName, tableStat.tableName);
            showSaveToast('Table vacuum completed', `${String(tableStat.schemaName || 'public')}.${String(tableStat.tableName || '')} was vacuumed successfully.`);
            await loadAdminData();
          } catch (error) {
            showErrorToast('Table vacuum failed', error instanceof Error ? error.message : String(error));
          } finally {
            tableButton.disabled = false;
            refreshPerfButton.disabled = false;
            vacuumPerfButton.disabled = false;
            tableButton.textContent = oldLabel;
          }
        });

        row.append(label, liveTuples, deadTuples, vacuumCounts, tableButton);
        vacuumList.appendChild(row);
      }
    }

    vacuumCard.append(vacuumTitle, vacuumNote, vacuumList);
    adminPostgresPerformanceGrid.appendChild(vacuumCard);

    const activeCard = document.createElement('section');
    activeCard.className = 'admin-link-card';
    const activeTitle = document.createElement('strong');
    activeTitle.textContent = 'Active Query Activity';
    activeCard.appendChild(activeTitle);
    if (activeQueries.length === 0) {
      const emptyActive = document.createElement('div');
      emptyActive.className = 'admin-helper';
      emptyActive.textContent = 'No active query rows captured.';
      activeCard.appendChild(emptyActive);
    } else {
      const table = document.createElement('table');
      table.className = 'admin-performance-table';
      const header = document.createElement('thead');
      header.innerHTML = '<tr><th>State</th><th>Wait</th><th>Duration</th><th>User/App</th><th>Query</th></tr>';
      const body = document.createElement('tbody');
      for (const row of activeQueries) {
        const tr = document.createElement('tr');

        const stateTd = document.createElement('td');
        stateTd.textContent = String(row.state || 'unknown');

        const waitTd = document.createElement('td');
        const waitType = String(row.waitEventType || '').trim();
        const waitEvent = String(row.waitEvent || '').trim();
        waitTd.textContent = waitType || waitEvent ? `${waitType}${waitType && waitEvent ? ':' : ''}${waitEvent}` : 'None';

        const durationTd = document.createElement('td');
        durationTd.textContent = formatDuration(row.queryDurationMs);

        const userTd = document.createElement('td');
        userTd.textContent = `${row.user || 'unknown'} / ${row.application || row.backendType || 'unknown'}`;

        const queryTd = document.createElement('td');
        queryTd.className = 'admin-performance-query';
        queryTd.textContent = String(row.query || '').trim();

        tr.append(stateTd, waitTd, durationTd, userTd, queryTd);
        body.appendChild(tr);
      }
      table.append(header, body);
      activeCard.appendChild(table);
    }
    adminPostgresPerformanceGrid.appendChild(activeCard);

    const topCard = document.createElement('section');
    topCard.className = 'admin-link-card';
    const topTitle = document.createElement('strong');
    topTitle.textContent = 'Top Statements by Total Execution Time';
    topCard.appendChild(topTitle);
    const topError = String(perf.topStatementsError || perf.error || '').trim();
    if (topError) {
      const errorNode = document.createElement('div');
      errorNode.className = 'admin-helper';
      errorNode.textContent = topError;
      topCard.appendChild(errorNode);
    } else if (topStatements.length === 0) {
      const emptyTop = document.createElement('div');
      emptyTop.className = 'admin-helper';
      emptyTop.textContent = 'No statement performance rows available.';
      topCard.appendChild(emptyTop);
    } else {
      const topTable = document.createElement('table');
      topTable.className = 'admin-performance-table';

      // Sortable columns: key = data field, label = header text
      const TOP_COLS = [
        { key: 'calls',       label: 'Calls',  numeric: true,  fmt: (v) => String(Number(v || 0)) },
        { key: 'totalExecMs', label: 'Total',  numeric: true,  fmt: (v) => formatDuration(Number(v || 0)) },
        { key: 'meanExecMs',  label: 'Mean',   numeric: true,  fmt: (v) => formatDuration(Number(v || 0)) },
        { key: 'rows',        label: 'Rows',   numeric: true,  fmt: (v) => String(Number(v || 0)) },
        { key: 'query',       label: 'Query',  numeric: false, fmt: (v) => String(v || '').trim() },
      ];
      const TOP_COL_SPAN = TOP_COLS.length + 1; // +1 for the Explain action column

      let topSortKey = 'totalExecMs';
      let topSortAsc = false;

      const topHeader = document.createElement('thead');
      const topHeaderRow = document.createElement('tr');
      const topBody = document.createElement('tbody');

      const renderTopRows = () => {
        const sorted = [...topStatements].sort((a, b) => {
          const col = TOP_COLS.find((c) => c.key === topSortKey);
          const av = col && col.numeric ? Number(a[topSortKey] || 0) : String(a[topSortKey] || '');
          const bv = col && col.numeric ? Number(b[topSortKey] || 0) : String(b[topSortKey] || '');
          let cmp = 0;
          if (typeof av === 'number' && typeof bv === 'number') {
            cmp = av - bv;
          } else {
            cmp = av < bv ? -1 : av > bv ? 1 : 0;
          }
          return topSortAsc ? cmp : -cmp;
        });

        topBody.innerHTML = '';
        for (const row of sorted) {
          const tr = document.createElement('tr');
          for (const col of TOP_COLS) {
            const td = document.createElement('td');
            if (col.key === 'query') td.className = 'admin-performance-query';
            td.textContent = col.fmt(row[col.key]);
            tr.appendChild(td);
          }

          // Explain action cell
          const explainTd = document.createElement('td');
          const explainBtn = document.createElement('button');
          explainBtn.type = 'button';
          explainBtn.className = 'btn btn-neutral';
          explainBtn.style.fontSize = '0.78rem';
          explainBtn.style.padding = '3px 8px';
          explainBtn.textContent = 'Explain';

          // Expansion row (hidden until explain runs)
          const expandTr = document.createElement('tr');
          expandTr.hidden = true;
          const expandTd = document.createElement('td');
          expandTd.colSpan = TOP_COL_SPAN;
          expandTd.style.padding = '0';
          const pre = document.createElement('pre');
          pre.style.cssText = 'margin:0;padding:10px 14px;background:#0f172a;color:#e2e8f0;font-size:0.78rem;overflow-x:auto;white-space:pre;border-top:1px solid #334155;';
          expandTd.appendChild(pre);
          expandTr.appendChild(expandTd);

          explainBtn.addEventListener('click', async () => {
            // Toggle off if already showing the same result
            if (!expandTr.hidden && pre.dataset.loadedQuery === row.query) {
              expandTr.hidden = true;
              explainBtn.textContent = 'Explain';
              return;
            }
            const oldLabel = explainBtn.textContent;
            explainBtn.disabled = true;
            explainBtn.textContent = 'Running...';
            pre.textContent = '';
            expandTr.hidden = false;
            try {
              const result = await request('/api/admin/postgres-explain', 'POST', { query: String(row.query || '').trim() });
              if (result && result.ok) {
                const strategyLabel = result.strategy === 'GENERIC_PLAN'
                  ? '-- Strategy: GENERIC_PLAN (PostgreSQL 16+)\\n'
                  : result.strategy === 'NULL_SUBSTITUTION'
                    ? '-- Strategy: $N parameters replaced with NULL for planning\\n'
                    : '';
                pre.textContent = strategyLabel + String(result.plan || '(no plan returned)');
                pre.dataset.loadedQuery = row.query;
                explainBtn.textContent = 'Hide';
              } else {
                pre.textContent = `Error: ${String(result?.error || 'Unknown error')}`;
                pre.dataset.loadedQuery = '';
                explainBtn.textContent = 'Explain';
              }
            } catch (error) {
              pre.textContent = `Error: ${error instanceof Error ? error.message : String(error)}`;
              pre.dataset.loadedQuery = '';
              explainBtn.textContent = 'Explain';
            } finally {
              explainBtn.disabled = false;
            }
          });

          explainTd.appendChild(explainBtn);
          tr.appendChild(explainTd);
          topBody.appendChild(tr);
          topBody.appendChild(expandTr);
        }
      };

      const renderTopHeader = () => {
        topHeaderRow.innerHTML = '';
        for (const col of TOP_COLS) {
          const th = document.createElement('th');
          th.style.cursor = col.key !== 'query' ? 'pointer' : '';
          th.style.userSelect = 'none';
          const isCurrent = topSortKey === col.key;
          const arrow = isCurrent ? (topSortAsc ? ' ▲' : ' ▼') : '';
          th.textContent = col.label + arrow;
          if (col.key !== 'query') {
            th.addEventListener('click', () => {
              if (topSortKey === col.key) {
                topSortAsc = !topSortAsc;
              } else {
                topSortKey = col.key;
                topSortAsc = false;
              }
              renderTopHeader();
              renderTopRows();
            });
          }
          topHeaderRow.appendChild(th);
        }
        // Non-sortable header for the Explain column
        const thExplain = document.createElement('th');
        thExplain.textContent = '';
        topHeaderRow.appendChild(thExplain);
      };

      renderTopHeader();
      renderTopRows();
      topHeader.appendChild(topHeaderRow);
      topTable.append(topHeader, topBody);
      topCard.appendChild(topTable);
    }
    adminPostgresPerformanceGrid.appendChild(topCard);
  }

  function linkTokensFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const keys = ['link', 'links', 'token', 'tokens'];
    for (const key of keys) {
      for (const value of params.getAll(key)) {
        for (const token of value.split(',')) {
          const normalized = token.trim();
          if (normalized) return normalized; // Return first valid token
        }
      }
    }
    return null; // No token found
  }

  function applyLinkVisibility(links) {
    const token = linkTokensFromUrl();
    currentToken = token; // Store for API requests

    const linkMap = new Map((links || []).map(link => [link.token, link]));
    const link = token ? linkMap.get(token) : null;

    if (link) {
      tokenAllowedCalendars = new Set(link.calendarIds || []);
      hasValidToken = true;
      return;
    }

    hasValidToken = false;
    tokenAllowedCalendars = null;
    hiddenCals = new Set(allCalendars.map(calendar => calendar.id));
  }

  function showLandingScreen(options = {}) {
    const invalidToken = Boolean(options.invalidToken);
    const attemptedToken = options.attemptedToken || '';
    const validatingToken = Boolean(options.validatingToken);
    const authModal = Boolean(options.authModal);
    appShell.style.display = 'none';
    if (profileOnboardingScreen) {
      profileOnboardingScreen.style.display = 'none';
    }
    landingScreen.style.display = 'flex';
    setLandingAuthModal(authModal);
    if (authModal) {
      const landingUrl = new URL(window.location.href);
      if (landingUrl.searchParams.has('add_to_account')) {
        landingUrl.searchParams.delete('add_to_account');
        history.replaceState({}, '', landingUrl.toString());
      }
    }
    startSlimeSimulation();

    if (attemptedToken) tokenInput.value = attemptedToken;

    if (validatingToken) {
      tokenHelp.textContent = 'Validating access token...';
    } else {
      tokenHelp.textContent = (invalidToken || currentToken)
        ? 'Token not recognized. Check the token and try again.'
        : 'A valid token is required to access scheduling data.';
    }
    tokenSubmit.disabled = validatingToken;

    const submitToken = async () => {
      const value = tokenInput.value.trim();
      if (!value) {
        tokenHelp.textContent = 'Please enter a token to continue.';
        return;
      }
      tokenSubmit.disabled = true;
      tokenHelp.textContent = 'Validating\u2026';

      // ── Phase 1: validate token via API ──────────────────────────────────
      // Set currentToken before the request so request() can attach it.
      currentToken = value;
      let validation, cals, session;
      try {
        ({ validation, calendars: cals, session, apiToken: currentToken } = await validateTokenAndLoadCalendars(value));
      } catch (err) {
        // Token was rejected — reset and show feedback.
        currentToken = null;
        tokenHelp.textContent = 'Token not recognised. Check the token and try again.';
        tokenSubmit.disabled = false;
        return;
      }

      // ── Phase 2: token is valid — update state and show the app ──────────
      // Do NOT reset currentToken from here on; any UI error must not
      // invalidate the already-authenticated session.
      await claimTokenResourcesForLoggedInUser(value);
      tokenAllowedCalendars = new Set(validation.calendarIds || []);
      hasValidToken = true;
      currentUser = session && session.authenticated ? session.user : null;
      syncUserIdInUrl(currentUser);
      allCalendars = cals;

      const completeTokenSubmit = async () => {
        if (profileOnboardingScreen) {
          profileOnboardingScreen.style.display = 'none';
        }
        showAppShell();
        renderSidebar();
        void loadAccessCatalog();
        connectCalendarUpdatesSocket();
        try {
          ensureCalendarLoaded();
        } catch (e) {
          console.error('FullCalendar render error (non-fatal):', e);
        }
      };

      if (await maybeRequireProfileOnboarding(completeTokenSubmit)) {
        tokenSubmit.disabled = false;
        return;
      }

      // Remove shared-link tokens from the URL after successful validation.
      const url = new URL(window.location.href);
      url.searchParams.delete('token');
      url.searchParams.delete('link');
      url.searchParams.delete('tokens');
      url.searchParams.delete('links');
      if (currentUser && currentUser.id) {
        url.searchParams.set('user_id', currentUser.id);
      }
      history.replaceState({}, '', url.toString());
      await completeTokenSubmit();
    };

    tokenSubmit.onclick = submitToken;
    tokenInput.onkeydown = event => {
      if (event.key === 'Enter') submitToken();
    };

    if (landingAuthBackdrop) {
      landingAuthBackdrop.onclick = closeLandingAuthModal;
    }

    if (landingAuthCloseButton) {
      landingAuthCloseButton.onclick = closeLandingAuthModal;
    }

    // ── Google OAuth Login ────────────────────────────────────────────────────
    const googleLoginBtn = document.getElementById('google-login-btn');
    const passkeyLoginBtn = document.getElementById('passkey-login-btn');
    const emailLoginInput = document.getElementById('email-login-input');
    const emailLoginBtn = document.getElementById('email-login-btn');
    const googleSignupBtn = document.getElementById('google-signup-btn');
    const passkeySignupBtn = document.getElementById('passkey-signup-btn');
    const emailSignupInput = document.getElementById('email-signup-input');
    const emailSignupBtn = document.getElementById('email-signup-btn');

    const loadAppForAuthenticatedSession = async (sessionToken, sessionUser, originalToken = null) => {
      currentToken = sessionToken;
      currentUser = sessionUser;
      syncUserIdInUrl(currentUser);

      const cals = await request('/api/calendars?token=' + encodeURIComponent(currentToken), 'GET', null, false);
      tokenAllowedCalendars = new Set((cals || []).map(cal => cal.id));
      hasValidToken = true;
      allCalendars = cals;

      const completeLogin = async () => {
        if (profileOnboardingScreen) {
          profileOnboardingScreen.style.display = 'none';
        }
        showAppShell();
        renderSidebar();
        void loadAccessCatalog();
        connectCalendarUpdatesSocket();
        ensureCalendarLoaded();
        if (window.__revealPage) window.__revealPage();

        if (originalToken && originalToken !== sessionToken) {
          claimTokenResourcesForLoggedInUser(originalToken).catch(err => {
            console.warn('[LOGIN] Failed to claim URL token:', err);
          });
        }
      };

      if (await maybeRequireProfileOnboarding(completeLogin)) {
        return;
      }

      await completeLogin();
    };

    const performPasskeyLogin = async () => {
      const authResult = await authenticateWithPasskey();
      if (!authResult?.authenticated || !authResult?.apiToken) {
        throw new Error('Passkey login failed.');
      }
      await loadAppForAuthenticatedSession(authResult.apiToken, authResult.user || null, sharedLinkToken || currentToken);
    };

    const performPasskeySignup = async () => {
      // Prompt for email and name
      const email = prompt('Enter your email for sign-up:');
      if (!email) {
        throw new Error('Email is required for sign-up.');
      }

      const name = prompt('Enter your name (optional):') || email.split('@')[0];

      // Create account via local signup
      const signupResponse = await request('/auth/local-signup', 'POST', { email, name }, false);
      if (!signupResponse?.apiToken) {
        throw new Error('Failed to create account.');
      }

      const newApiToken = signupResponse.apiToken;
      const previousToken = currentToken;
      let activatedSession = false;

      try {
        // Temporarily set currentToken to the new account's token for passkey registration
        currentToken = newApiToken;

        // Get passkey registration options
        const optionsResult = await request('/api/passkeys/register/options', 'POST', {}, true);
        const publicKey = optionsResult?.publicKey;
        if (!publicKey || !publicKey.challenge || !publicKey.user || !publicKey.user.id) {
          throw new Error('Invalid passkey options from server.');
        }

        // Create credential
        const credentialCreationOptions = {
          ...publicKey,
          challenge: base64UrlToBuffer(publicKey.challenge),
          user: {
            ...publicKey.user,
            id: base64UrlToBuffer(publicKey.user.id),
          },
          excludeCredentials: Array.isArray(publicKey.excludeCredentials)
            ? publicKey.excludeCredentials.map((descriptor) => ({
                ...descriptor,
                id: base64UrlToBuffer(descriptor.id),
              }))
            : [],
        };

        const credential = await navigator.credentials.create({ publicKey: credentialCreationOptions });
        if (!credential) {
          throw new Error('Passkey creation was cancelled.');
        }

        const credentialPayload = {
          id: credential.id,
          type: credential.type,
          rawId: bufferToBase64Url(credential.rawId),
          response: {
            clientDataJSON: bufferToBase64Url(credential.response.clientDataJSON),
            attestationObject: bufferToBase64Url(credential.response.attestationObject),
            transports: typeof credential.response.getTransports === 'function' ? credential.response.getTransports() : [],
          },
        };

        // Verify passkey registration
        await request('/api/passkeys/register/verify', 'POST', {
          credential: credentialPayload,
          passkeyName: 'Signup Passkey',
        }, true);

        // Load app with new account. This may pause on profile onboarding.
        await loadAppForAuthenticatedSession(newApiToken, signupResponse.user || null, sharedLinkToken || previousToken);
        activatedSession = true;
      } finally {
        // If signup did not complete, restore the prior token; otherwise keep new session token.
        if (!activatedSession) {
          currentToken = previousToken;
        }
      }
    };

    const startGoogleAuth = async () => {
      console.log('[LOGIN] Login button clicked');

      try {
        // First check if user has a valid persisted session
        const sessionCheckOpts = {
          method: 'GET',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        };
        const sessionResponse = await fetch('/api/auth/check-session', sessionCheckOpts);
        if (sessionResponse.ok) {
          const sessionData = await sessionResponse.json();
          if (sessionData.authenticated && sessionData.apiToken) {
            const urlToken = sharedLinkToken || currentToken; // Preserve the original shared link token if present
            if (sessionData.user && sessionData.user.isTokenOnlyAccount) {
              console.log('[LOGIN] Token-only session detected, redirecting to OAuth');
              if (urlToken) {
                await preservePendingLinkForOauth(urlToken);
              }
              window.location.href = '/auth/google-login';
              return;
            }

            // User has a valid session - use it to authenticate
            console.log('[LOGIN] Valid session found, authenticating');
            const sessionToken = sessionData.apiToken;

            try {
              await loadAppForAuthenticatedSession(sessionToken, sessionData.user, sharedLinkToken || currentToken);
            } catch (error) {
              console.error('[LOGIN] Failed to load calendars with persisted session:', error);
              // Fall through to OAuth as fallback
              if (urlToken) {
                console.log('[LOGIN] Preserving shared link before OAuth redirect');
                await preservePendingLinkForOauth(urlToken);
              }
              window.location.href = '/auth/google-login';
              return;
            }

            return;
          }
        }
      } catch (error) {
        console.warn('[LOGIN] Session check failed, proceeding with OAuth:', error);
      }

      // No valid session - proceed with OAuth flow
      if (sharedLinkToken || currentToken) {
        console.log('[LOGIN] Preserving shared link before OAuth redirect');
        await preservePendingLinkForOauth(sharedLinkToken || currentToken);
      }
      window.location.href = '/auth/google-login';
    };

    const startPasskeyAuth = async () => {
      try {
        await performPasskeyLogin();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showErrorToast('Passkey login failed', message);
      }
    };

    const sendEmailAuthLink = async (inputEl, buttonEl, emptyMessage, fallbackMessage, failureMessage) => {
      const email = String(inputEl?.value || '').trim();
      if (!email) {
        tokenHelp.textContent = emptyMessage;
        return;
      }

      const oldLabel = buttonEl.textContent;
      buttonEl.disabled = true;
      buttonEl.textContent = 'Sending...';
      try {
        const response = await fetch('/auth/email-login/request', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(String(payload.detail || failureMessage));
        }
        tokenHelp.textContent = String(payload.message || fallbackMessage);
      } catch (error) {
        tokenHelp.textContent = error instanceof Error ? error.message : String(error);
      } finally {
        buttonEl.disabled = false;
        buttonEl.textContent = oldLabel;
      }
    };

    if (googleLoginBtn) {
      googleLoginBtn.onclick = startGoogleAuth;
    }
    if (googleSignupBtn) {
      googleSignupBtn.onclick = startGoogleAuth;
    }

    if (passkeyLoginBtn) {
      passkeyLoginBtn.onclick = async () => {
        const oldLabel = passkeyLoginBtn.textContent;
        passkeyLoginBtn.disabled = true;
        passkeyLoginBtn.textContent = 'Logging in...';
        try {
          await startPasskeyAuth();
        } finally {
          passkeyLoginBtn.disabled = false;
          passkeyLoginBtn.textContent = oldLabel;
        }
      };
    }

    if (passkeySignupBtn) {
      passkeySignupBtn.onclick = async () => {
        const oldLabel = passkeySignupBtn.textContent;
        passkeySignupBtn.disabled = true;
        passkeySignupBtn.textContent = 'Signing up...';
        try {
          await performPasskeySignup();
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          showErrorToast('Passkey signup failed', message);
        } finally {
          passkeySignupBtn.disabled = false;
          passkeySignupBtn.textContent = oldLabel;
        }
      };
    }

    if (emailLoginBtn) {
      emailLoginBtn.onclick = async () => {
        await sendEmailAuthLink(
          emailLoginInput,
          emailLoginBtn,
          'Enter your email to receive a login link.',
          'If an account exists for that email, a login link has been sent.',
          'Unable to send login email.',
        );
      };
    }

    if (emailSignupBtn) {
      emailSignupBtn.onclick = async () => {
        await sendEmailAuthLink(
          emailSignupInput,
          emailSignupBtn,
          'Enter your email to receive a sign-up link.',
          'If an account can be created for that email, a sign-up link has been sent.',
          'Unable to send sign-up email.',
        );
      };
    }
  }

  function showAppShell() {
    landingScreen.style.display = 'none';
    if (landingAuthBackdrop) {
      landingAuthBackdrop.hidden = true;
    }
    landingScreen.classList.remove('is-signin-modal');
    if (profileOnboardingScreen) {
      profileOnboardingScreen.style.display = 'none';
    }
    appShell.style.display = 'flex';
    adminNavItem.style.display = isAdminUser() ? 'flex' : 'none';
    setCurrentView('calendar');
  }

  function setLandingAuthModal(open) {
    if (!landingScreen) {
      return;
    }
    landingScreen.classList.toggle('is-signin-modal', open);
    if (landingAuthBackdrop) {
      landingAuthBackdrop.hidden = !open;
    }
  }

  function closeLandingAuthModal() {
    setLandingAuthModal(false);
  }

  if (!window.__landingAuthEscapeBound) {
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && landingScreen.classList.contains('is-signin-modal')) {
        closeLandingAuthModal();
      }
    });
    window.__landingAuthEscapeBound = true;
  }

  function visibleCalendarColors(calendarIds) {
    return (calendarIds || [])
      .filter(calendarId => !hiddenCals.has(calendarId))
      .map(calendarId => allCalendars.find(calendar => calendar.id === calendarId)?.color)
      .filter(Boolean);
  }

  // ── Sidebar ──────────────────────────────────────────────────────────────
  function renderSidebar() {
    calendarList.innerHTML = '';
    // If token is set, only show token-accessible calendars
    const visibleCalendars = tokenAllowedCalendars 
      ? allCalendars.filter(cal => tokenAllowedCalendars.has(cal.id))
      : allCalendars;
    
    for (const [groupName, calendars] of groupCalendars(visibleCalendars)) {
      const groupHeaderRow = document.createElement('div');
      groupHeaderRow.className = 'sidebar-group-header';

      const groupHeader = document.createElement('div');
      groupHeader.className = 'sidebar-section-title sidebar-section-title--group';
      groupHeader.textContent = groupName;

      const groupToggleLabel = document.createElement('label');
      groupToggleLabel.className = 'sidebar-group-toggle';
      const groupToggle = document.createElement('input');
      groupToggle.type = 'checkbox';
      groupToggle.className = 'cal-checkbox';
      groupToggle.style.setProperty('--cal-color', '#94a3b8');
      const visibleCount = calendars.filter(cal => !hiddenCals.has(cal.id)).length;
      groupToggle.checked = calendars.length > 0 && visibleCount === calendars.length;
      groupToggle.indeterminate = visibleCount > 0 && visibleCount < calendars.length;
      groupToggle.addEventListener('change', () => {
        if (groupToggle.checked) {
          for (const cal of calendars) hiddenCals.delete(cal.id);
        } else {
          for (const cal of calendars) hiddenCals.add(cal.id);
        }
        fcCalendar.refetchEvents();
        renderSidebar();
      });
      const groupToggleText = document.createElement('span');
      groupToggleText.textContent = 'Show';
      groupToggleLabel.append(groupToggle, groupToggleText);
      groupHeaderRow.append(groupHeader, groupToggleLabel);
      calendarList.appendChild(groupHeaderRow);

      const groupExpanded = visibleCount > 0;
      if (!groupExpanded) {
        continue;
      }

      for (const cal of calendars) {
        const item = document.createElement('div');
        item.className = 'sidebar-cal-item';

        const meta = document.createElement('label');
        meta.className = 'sidebar-cal-meta';

        const cb = document.createElement('input');
        cb.type      = 'checkbox';
        cb.className = 'cal-checkbox';
        cb.style.setProperty('--cal-color', cal.color);
        cb.checked   = !hiddenCals.has(cal.id);
        cb.addEventListener('change', () => {
          if (cb.checked) hiddenCals.delete(cal.id);
          else            hiddenCals.add(cal.id);
          fcCalendar.refetchEvents();
          renderSidebar();
        });

        const name = document.createElement('span');
        name.className   = 'cal-name';
        name.textContent = cal.name;
        name.style.color = cal.color || '#cbd5e1';

        meta.append(cb, name);

        const infoButton = document.createElement('button');
        infoButton.type = 'button';
        infoButton.className = 'sidebar-cal-info';
        infoButton.setAttribute('aria-label', `Open information for ${cal.name}`);
        infoButton.textContent = 'i';
        bindCalendarHoverTooltip(infoButton, cal);
        infoButton.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          window.location.href = `/calendar-info/${encodeURIComponent(cal.id)}`;
        });

        item.append(meta, infoButton);
        calendarList.appendChild(item);
      }
    }

    if (!calendarList.__calendarHoverBound) {
      calendarList.addEventListener('mouseleave', hideCalendarHoverTooltip);
      calendarList.__calendarHoverBound = true;
    }

    if (adminNavItem) {
      adminNavItem.style.display = isAdminUser() ? 'flex' : 'none';
      adminNavItem.onclick = async () => {
        setCurrentView('admin');
        await loadAdminData();
      };
    }

    if (accessNavItem) {
      accessNavItem.style.display = (hasValidToken && !isServiceAccountUser()) ? 'flex' : 'none';
      accessNavItem.onclick = async () => {
        setCurrentView('access');
        await Promise.all([loadAccessCatalog(), loadPasskeys()]);
      };
    }

    if (upcomingNavItem) {
      upcomingNavItem.style.display = (hasValidToken && !isServiceAccountUser()) ? 'flex' : 'none';
      upcomingNavItem.onclick = async () => {
        setCurrentView('upcoming');
        await loadUpcomingBookings();
      };
    }

    if (shareNavItem) {
      shareNavItem.style.display = currentUser ? 'flex' : 'none';
      shareNavItem.onclick = async () => {
        await openShareLinksDialog();
      };
    }

    if (sidebarLogo) {
      sidebarLogo.onclick = () => {
        setCurrentView('calendar');
      };
    }

    if (calendarNavItem) {
      calendarNavItem.onclick = () => {
        setCurrentView('calendar');
      };
    }

    if (logoutNavItem) {
      logoutNavItem.style.display = currentUser ? 'flex' : 'none';
      logoutNavItem.onclick = async () => {
        await logoutUser();
      };
    }

    if (tokenActionNavItem) {
      const showSaveAction = currentUser && isServiceAccountUser();
      tokenActionNavItem.style.display = showSaveAction ? 'flex' : 'none';
      if (showSaveAction) {
        tokenActionLabel.textContent = 'Save to account';
      }
      tokenActionNavItem.onclick = async () => {
        await handleTokenPageAction();
      };
    }
  }

  // ── Dialog: recurrence controls ──────────────────────────────────────────
  function resetRecurrence() {
    recurEnabled.checked = false;
    recurFreq.value = 'daily'; recurInterval.value = '1'; recurUntil.value = '';
    recurFields.style.display = 'none'; recurUntilField.style.display = 'none';
  }
  function syncRecurrenceVis() {
    const on = recurEnabled.checked;
    recurFields.style.display     = on ? 'grid' : 'none';
    recurUntilField.style.display = on ? 'grid' : 'none';
  }
  recurEnabled.addEventListener('change', syncRecurrenceVis);

  // ── Dialog: open ─────────────────────────────────────────────────────────
  function openDialog(mode, data) {
    dialogState.mode    = mode;
    dialogState.eventId = data.eventId || null;
    dialogTitle.textContent       = mode === 'create' ? 'Create Event' : 'Edit Event';
    deleteButton.style.visibility = mode === 'edit' ? 'visible' : 'hidden';
    const titleParts = splitEventTitle(data.title || '');
    const oauthUserName = currentUser && !currentUser.isTokenOnlyAccount
      ? String(currentUser.name || '').trim()
      : '';
    titleInput.value    = data.name || titleParts.user || (mode === 'create' ? oauthUserName : '');
    eventNameInput.value = data.eventTitle || titleParts.eventName;
    contactInput.value  = data.contact || '';
    startInput.value    = isoToLocalInput(data.start);
    endInput.value      = isoToLocalInput(data.end);
    allDayInput.checked = Boolean(data.allDay);
    renderCalendarCheckboxes(data.calendarIds || (data.calendarId ? [data.calendarId] : []));
    resetRecurrence();
    if (data.recurrence) {
      recurEnabled.checked = true;
      recurFreq.value      = data.recurrence.freq     || 'daily';
      recurInterval.value  = String(data.recurrence.interval || 1);
      recurUntil.value     = isoToLocalInput(data.recurrence.until);
    }
    notesInput.value = data.notes || '';
    committedInput.checked = Boolean(data.committed);
    dialogInitialState = captureDialogState();
    syncRecurrenceVis();
    dialogSuggestionEvents = [];
    dialog.showModal();
    void refreshDialogCalendarAvailability();
    void refreshDialogEventNameSuggestions();
  }

  // ── FullCalendar event source ────────────────────────────────────────────
  function buildWorkingHourHighlights(rangeStart, rangeEnd) {
    const highlights = [];
    if (!(rangeStart instanceof Date) || !(rangeEnd instanceof Date)) {
      return highlights;
    }

    const cursor = new Date(rangeStart);
    cursor.setHours(0, 0, 0, 0);

    const end = new Date(rangeEnd);
    end.setHours(0, 0, 0, 0);

    while (cursor < end) {
      const day = cursor.getDay();
      if (day >= 1 && day <= 5) {
        const start = new Date(cursor);
        start.setHours(9, 0, 0, 0);
        const finish = new Date(cursor);
        finish.setHours(17, 0, 0, 0);
        highlights.push({
          start: start.toISOString(),
          end: finish.toISOString(),
          display: 'background',
          classNames: ['working-hours-highlight'],
        });
      }
      cursor.setDate(cursor.getDate() + 1);
    }

    return highlights;
  }

  async function loadEvents(info, success, failure) {
    try {
      if (!hasValidToken || !currentToken) {
        success([]);
        return;
      }
      const q = new URLSearchParams({
        start: info.start.toISOString(),
        end:   info.end.toISOString(),
      });
      let events = await request('/api/events?' + q);
      dialogLoadedEvents = Array.isArray(events) ? events : [];
      // Filter out calendars the user has hidden via the sidebar
      if (hiddenCals.size > 0) {
        events = events.filter(e => {
          const calendarIds = e.calendarIds || (e.extendedProps && e.extendedProps.calendarIds) || [];
          return calendarIds.some(cid => !hiddenCals.has(cid));
        });
      }
      const highlights = buildWorkingHourHighlights(info.start, info.end);
      success([...highlights, ...events]);
      updateDialogCalendarAvailability();
    } catch (err) { failure(err); }
  }

  // ── Drag / resize ─────────────────────────────────────────────────────────
  async function saveMoveOrResize(info) {
    if (info.event.extendedProps.committed) {
      const allowOverride = await requestCommittedOverride();
      if (!allowOverride) {
        info.revert();
        showSaveToast(
          'Move/resize cancelled',
          'Committed event remained locked'
        );
        return;
      }
    }
    if (info.event.extendedProps.isRecurring) {
      info.revert();
      showSaveToast(
        'Drag/resize disabled',
        'Edit the series instead of individual recurring instances'
      );
      return;
    }
    try {
      await request('/api/events/' + info.event.id, 'PUT', {
        start:  info.event.start ? info.event.start.toISOString() : null,
        end:    info.event.end   ? info.event.end.toISOString()   : null,
        allDay: info.event.allDay,
      });
      showSaveToast('Event updated', info.event.title ? `"${info.event.title}" moved and saved` : 'Changes saved to server');
    } catch (err) {
      info.revert();
      if (showOverlapPopupIfNeeded(err.message, info.event.extendedProps.calendarIds || [])) return;
      showSaveToast('Update failed', err.message);
    }
  }

  // ── FullCalendar initialisation ───────────────────────────────────────────
  function formatDdMm(date) {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    return `${day}/${month}`;
  }

  function updateCalendarToolbarTitle(viewType, start, end) {
    const titleEl = document.querySelector('.fc-toolbar-title');
    if (!titleEl || !(start instanceof Date) || !(end instanceof Date)) {
      return;
    }

    if (viewType === 'timeGridDay') {
      titleEl.textContent = formatDdMm(start);
      return;
    }

    if (viewType === 'timeGridWeek' || viewType === 'listWeek') {
      const rangeEnd = new Date(end);
      rangeEnd.setDate(rangeEnd.getDate() - 1);
      titleEl.textContent = `${formatDdMm(start)} - ${formatDdMm(rangeEnd)}`;
      return;
    }

    if (viewType === 'dayGridMonth') {
      const monthStart = new Date(start.getFullYear(), start.getMonth(), 1);
      const monthEnd = new Date(start.getFullYear(), start.getMonth() + 1, 0);
      titleEl.textContent = `${formatDdMm(monthStart)} - ${formatDdMm(monthEnd)}`;
    }
  }

  const fcCalendar = new FullCalendar.Calendar(mountNode, {
    initialView: 'timeGridWeek',
    firstDay: 1,
    weekends: true,
    slotMinTime: '00:00:00',
    slotMaxTime: '24:00:00',
    businessHours: {
      daysOfWeek: [1, 2, 3, 4, 5],
      startTime: '09:00',
      endTime: '17:00',
    },
    dayHeaderFormat: { weekday: 'short', day: '2-digit', month: '2-digit' },
    height: 'auto',
    nowIndicator: true,
    editable: true,
    selectable: true,
    eventResizableFromStart: true,
    headerToolbar: {
      left:   'prev,next today',
      center: 'title',
      right:  'dayGridMonth,timeGridWeek,timeGridDay,listWeek',
    },
    datesSet: function(info) {
      updateCalendarToolbarTitle(info.view.type, info.start, info.end);
    },
    events: loadEvents,
    select: function(sel) {
      // Pre-select the first visible calendar
      const first = allCalendars.find(c => !hiddenCals.has(c.id));
      openDialog('create', {
        title: '',
        start:      sel.start.toISOString(),
        end:        sel.end ? sel.end.toISOString() : null,
        allDay:     sel.allDay,
        calendarId: first ? first.id : null,
        calendarIds: first ? [first.id] : [],
        recurrence: null,
        notes: '',
        committed: false,
      });
      fcCalendar.unselect();
    },
    eventClick: async function(clickInfo) {
      try {
        const seriesId = clickInfo.event.extendedProps.seriesId || clickInfo.event.id;
        const ev = await request('/api/events/' + seriesId);
        openDialog('edit', {
          eventId:    seriesId,
          title:      ev.title,
          name:       ev.name,
          eventTitle: ev.eventTitle,
          contact:    ev.contact,
          start:      ev.start,
          end:        ev.end,
          allDay:     ev.allDay,
          calendarId: ev.calendarId,
          calendarIds: ev.calendarIds || (ev.calendarId ? [ev.calendarId] : []),
          recurrence: ev.recurrence,
          notes:      ev.notes || '',
          committed:  Boolean(ev.committed),
        });
      } catch (err) {
        showErrorToast('Unable to open event', err.message);
      }
    },
    eventDrop:   saveMoveOrResize,
    eventResize: saveMoveOrResize,
    eventDidMount: function(info) {
      const calendarIds = info.event.extendedProps.calendarIds
        || (info.event.extendedProps.calendarId ? [info.event.extendedProps.calendarId] : []);
      const calendarColors = visibleCalendarColors(calendarIds);
      if (calendarColors.length > 1) {
        const stripeWidth = 10;
        const stops = calendarColors.map((color, index) => {
          const start = index * stripeWidth;
          const end = (index + 1) * stripeWidth;
          return `${color} ${start}px ${end}px`;
        });
        info.el.style.backgroundImage = `repeating-linear-gradient(45deg, ${stops.join(', ')})`;
        info.el.style.backgroundColor = calendarColors[0];
        info.el.style.borderColor = calendarColors[0];
        info.el.style.color = '#fff';
      } else {
        info.el.style.backgroundImage = '';
        if (calendarColors.length === 1) {
          info.el.style.backgroundColor = calendarColors[0];
          info.el.style.borderColor = calendarColors[0];
        }
      }

      const titleEl = info.el.querySelector('.fc-event-title');
      const isCommitted = Boolean(info.event.extendedProps.committed);
      if (titleEl) {
        const existingLock = titleEl.querySelector('.event-lock-icon');
        if (existingLock) existingLock.remove();
        if (isCommitted) {
          const lockIcon = document.createElement('span');
          lockIcon.className = 'event-lock-icon';
          lockIcon.textContent = '🔒';
          titleEl.prepend(lockIcon);
        }
      }

      const notes = String(info.event.extendedProps.notes || '').trim();
      if (notes) {
        const positionTooltip = (event) => {
          const offset = 14;
          const maxX = window.innerWidth - eventNotesTooltip.offsetWidth - 8;
          const maxY = window.innerHeight - eventNotesTooltip.offsetHeight - 8;
          const nextX = Math.min(maxX, event.clientX + offset);
          const nextY = Math.min(maxY, event.clientY + offset);
          eventNotesTooltip.style.left = `${Math.max(8, nextX)}px`;
          eventNotesTooltip.style.top = `${Math.max(8, nextY)}px`;
        };

        info.el.addEventListener('mouseenter', event => {
          eventNotesTooltip.textContent = notes;
          eventNotesTooltip.style.display = 'block';
          positionTooltip(event);
        });
        info.el.addEventListener('mousemove', positionTooltip);
        info.el.addEventListener('mouseleave', () => {
          eventNotesTooltip.style.display = 'none';
        });
      }
    },
  });

  let calendarRendered = false;

  function ensureCalendarLoaded() {
    if (!calendarRendered) {
      fcCalendar.render();
      calendarRendered = true;
    } else {
      fcCalendar.updateSize();
    }
    fcCalendar.refetchEvents();
  }

  window.addEventListener('pageshow', () => {
    if (hasValidToken) ensureCalendarLoaded();
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && hasValidToken) ensureCalendarLoaded();
  });

  // ── Dialog button listeners ───────────────────────────────────────────────
  cancelButton.addEventListener('click', () => dialog.close());
  overlapOkButton.addEventListener('click', () => overlapDialog.close());
  startInput.addEventListener('input', scheduleDialogCalendarAvailabilityRefresh);
  startInput.addEventListener('change', scheduleDialogCalendarAvailabilityRefresh);
  endInput.addEventListener('input', scheduleDialogCalendarAvailabilityRefresh);
  endInput.addEventListener('change', scheduleDialogCalendarAvailabilityRefresh);
  if (groupCreateResourceCancel) {
    groupCreateResourceCancel.addEventListener('click', () => closeGroupResourceCreateDialog(false));
  }
  if (groupCreateResourceConfirm) {
    groupCreateResourceConfirm.addEventListener('click', () => closeGroupResourceCreateDialog(true));
  }
  if (createPasskeyButton) {
    createPasskeyButton.addEventListener('click', async () => {
      await createPasskeyFromSettings();
    });
  }
  if (regenerateOwnLoginLinkButton) {
    regenerateOwnLoginLinkButton.addEventListener('click', async () => {
      const oldLabel = regenerateOwnLoginLinkButton.textContent;
      regenerateOwnLoginLinkButton.disabled = true;
      regenerateOwnLoginLinkButton.textContent = 'Regenerating...';
      try {
        await regenerateOwnLoginLink();
      } catch (error) {
        showErrorToast('Regenerate failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
      } finally {
        regenerateOwnLoginLinkButton.disabled = false;
        regenerateOwnLoginLinkButton.textContent = oldLabel;
      }
    });
  }
  if (shareLinksClose) {
    shareLinksClose.addEventListener('click', () => {
      if (shareLinksDialog && shareLinksDialog.open) {
        shareLinksDialog.close();
      }
    });
  }
  if (ownLoginLinkCopy) {
    ownLoginLinkCopy.addEventListener('click', async (event) => {
      event.preventDefault();
      if (!ownLoginLinkAnchor) {
        return;
      }
      const url = String(ownLoginLinkAnchor.href || '').trim();
      if (!url || url.endsWith('/#')) {
        return;
      }
      try {
        await navigator.clipboard.writeText(url);
        showSaveToast('Copied', 'Login link copied to clipboard.');
      } catch (error) {
        showErrorToast('Copy failed', error instanceof Error ? error.message : String(error), accessPanel || document.body);
      }
    });
  }
  if (passkeyNameInput) {
    passkeyNameInput.addEventListener('keydown', async (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        await createPasskeyFromSettings();
      }
    });
  }
  if (groupCreateResourceDialog) {
    groupCreateResourceDialog.addEventListener('close', () => {
      if (pendingGroupResourceCreateResolve) {
        closeGroupResourceCreateDialog(false);
      }
    });
  }
  if (profileOnboardingForm) {
    profileOnboardingForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!profileOnboardingSubmit) {
        return;
      }
      profileOnboardingSubmit.disabled = true;
      const oldLabel = profileOnboardingSubmit.textContent;
      profileOnboardingSubmit.textContent = 'Saving...';
      if (profileOnboardingError) {
        profileOnboardingError.textContent = '';
      }

      try {
        const name = String(profileOnboardingName?.value || '').trim();
        const contact = String(profileOnboardingContact?.value || '').trim();
        const labGroup = String(profileOnboardingLabGroup?.value || '').trim();
        const saved = await saveProfileWithLabGroupConfirm({ name, contact, labGroup });
        if (profileOnboardingLabGroup) {
          profileOnboardingLabGroup.value = saved.labGroup;
        }

        if (profileOnboardingScreen) {
          profileOnboardingScreen.style.display = 'none';
        }

        const continueHandler = pendingProfileContinue;
        pendingProfileContinue = null;
        if (typeof continueHandler === 'function') {
          await continueHandler();
        }
      } catch (error) {
        if (profileOnboardingError) {
          profileOnboardingError.textContent = error instanceof Error ? error.message : String(error);
        }
      } finally {
        profileOnboardingSubmit.disabled = false;
        profileOnboardingSubmit.textContent = oldLabel;
      }
    });
  }
  if (settingsProfileSaveButton) {
    settingsProfileSaveButton.addEventListener('click', async () => {
      if (settingsProfileError) {
        settingsProfileError.textContent = '';
      }
      const oldLabel = settingsProfileSaveButton.textContent;
      settingsProfileSaveButton.disabled = true;
      settingsProfileSaveButton.textContent = 'Saving...';
      try {
        const name = String(settingsProfileNameInput?.value || '').trim();
        const contact = String(settingsProfileContactInput?.value || '').trim();
        const labGroup = String(settingsProfileLabGroupInput?.value || '').trim();
        const saved = await saveProfileWithLabGroupConfirm({ name, contact, labGroup });
        if (settingsProfileLabGroupInput) {
          settingsProfileLabGroupInput.value = saved.labGroup;
        }
        upcomingBookingsData = null;
        if (currentView === 'upcoming') {
          void loadUpcomingBookings();
        }
        showSaveToast('Profile updated', 'Your profile changes have been saved.', false, accessPanel || document.body);
      } catch (error) {
        if (settingsProfileError) {
          settingsProfileError.textContent = error instanceof Error ? error.message : String(error);
        }
      } finally {
        settingsProfileSaveButton.disabled = false;
        settingsProfileSaveButton.textContent = oldLabel;
      }
    });
  }
  if (labGroupConfirmCancel) {
    labGroupConfirmCancel.addEventListener('click', () => {
      if (pendingLabGroupResolve) {
        const resolve = pendingLabGroupResolve;
        pendingLabGroupResolve = null;
        resolve('');
      }
      if (labGroupConfirmDialog && labGroupConfirmDialog.open) {
        labGroupConfirmDialog.close();
      }
    });
  }
  if (labGroupConfirmApply) {
    labGroupConfirmApply.addEventListener('click', () => {
      const editedValue = String(labGroupConfirmInput?.value || '').trim();
      const selectedValue = String(labGroupConfirmSelect?.value || '').trim();
      const resolvedValue = selectedValue || editedValue;
      if (!resolvedValue) {
        if (labGroupConfirmMessage) {
          labGroupConfirmMessage.textContent = 'Lab group not found, please confirm spelling.';
        }
        return;
      }
      if (pendingLabGroupResolve) {
        const resolve = pendingLabGroupResolve;
        pendingLabGroupResolve = null;
        resolve(resolvedValue);
      }
      if (labGroupConfirmDialog && labGroupConfirmDialog.open) {
        labGroupConfirmDialog.close();
      }
    });
  }
  if (labGroupConfirmDialog) {
    labGroupConfirmDialog.addEventListener('close', () => {
      if (pendingLabGroupResolve) {
        const resolve = pendingLabGroupResolve;
        pendingLabGroupResolve = null;
        resolve('');
      }
    });
  }

  saveButton.addEventListener('click', async function() {
    const dialogDirty = dialogStateChangedSinceOpen();
    const allowCommittedOverride = await confirmCommittedEditIfNeeded(dialogDirty);
    if (!allowCommittedOverride) {
      return;
    }

    const userName = titleInput.value.trim();
    const eventName = eventNameInput.value.trim();
    const contact = contactInput.value.trim();
    const title = combineEventTitle(userName, eventName);
    const startIso = localToIso(startInput.value);
    const endIso   = localToIso(endInput.value);
    const calendarIds = getSelectedCalendarIds();
    const notes = notesInput.value;
    const committed = committedInput.checked;

    if (!title)    { showErrorToast('Validation error', 'User or Event Name is required.', dialog); return; }
    if (!startIso) { showErrorToast('Validation error', 'Start date/time is required.', dialog); return; }
    if (calendarIds.length === 0) {
      showErrorToast('Validation error', 'Select at least one calendar.', dialog);
      return;
    }
    if (endIso && endIso < startIso) {
      showErrorToast('Validation error', 'End must be after start.', dialog); return;
    }

    let recurrencePayload = null;
    if (recurEnabled.checked) {
      const iv = Number.parseInt(recurInterval.value || '1', 10);
      if (!Number.isInteger(iv) || iv < 1) {
        showErrorToast('Validation error', 'Recurrence interval must be at least 1.', dialog); return;
      }
      recurrencePayload = {
        freq:     recurFreq.value,
        interval: iv,
        until:    localToIso(recurUntil.value),
      };
    }

    const payload = {
      title,
      name: userName,
      eventTitle: eventName,
      contact,
      start:      startIso,
      end:        endIso,
      allDay:     allDayInput.checked,
      calendarId: calendarIds[0],
      calendarIds,
      recurrence: recurrencePayload,
      notes,
      committed,
    };

    saveButton.disabled = true;
    try {
      if (dialogState.mode === 'create') {
        await request('/api/events', 'POST', payload);
        showSaveToast('Event created', `"${title}" saved to server`);
      } else {
        await request('/api/events/' + dialogState.eventId, 'PUT', payload);
        showSaveToast('Event updated', `"${title}" saved to server`);
      }
      dialog.close();
      fcCalendar.refetchEvents();
    } catch (err) {
      if (showOverlapPopupIfNeeded(err.message, calendarIds)) return;
      showErrorToast('Save failed', err.message, dialog);
    } finally {
      saveButton.disabled = false;
    }
  });

  deleteButton.addEventListener('click', async function() {
    if (dialogState.mode !== 'edit' || !dialogState.eventId) return;
    if (!window.confirm('Delete this event?')) return;
    deleteButton.disabled = true;
    try {
      await request('/api/events/' + dialogState.eventId, 'DELETE');
      showSaveToast('Event deleted', 'Removed and saved to server');
      dialog.close();
      fcCalendar.refetchEvents();
    } catch (err) {
      showErrorToast('Delete failed', err.message);
    } finally {
      deleteButton.disabled = false;
    }
  });

  // ── Boot: require a valid token before fetching protected scheduler data ──

  // Guard against multiple bootstrap initializations
  if (window.__bootstrapRunning) {
    console.log('[BOOTSTRAP] Bootstrap already running, skipping re-initialization');
    return;
  }
  window.__bootstrapRunning = true;
  console.log('[BOOTSTRAP] Starting bootstrap initialization');

  // Check for token in URL parameter first
  if (!currentToken) {
    // No URL token - check if user has a valid session cookie
    console.log('[BOOTSTRAP] No URL token, checking for session cookie');
    fetch('/api/auth/check-session', {
      method: 'GET',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(res => res.ok ? res.json() : null)
      .then(sessionData => {
        if (sessionData && sessionData.authenticated && sessionData.apiToken) {
          // User has a valid session - use the session token
          console.log('[BOOTSTRAP] Valid session found');
          currentToken = sessionData.apiToken;
          currentUser = sessionData.user;
          authenticatedSessionToken = sessionData.apiToken;
          syncUserIdInUrl(currentUser);
          loadAppWithToken(currentToken);
        } else {
          // No valid session - show landing screen
          console.log('[BOOTSTRAP] No valid session, showing landing screen');
          showLandingScreen({ authModal: new URL(window.location.href).searchParams.has('add_to_account') });
          if (window.__revealPage) window.__revealPage();
        }
      })
      .catch(err => {
        console.warn('[BOOTSTRAP] Session check failed:', err);
        showLandingScreen({ authModal: new URL(window.location.href).searchParams.has('add_to_account') });
        if (window.__revealPage) window.__revealPage();
      });
    return;
  }

  // URL token present — validate silently (keep page hidden) to avoid a
  // flash of the landing screen during the round-trip to the server.
  console.log('[BOOTSTRAP] URL token present');
  getSessionUser()
    .then(sessionData => {
      if (sessionData && sessionData.user && sessionData.apiToken) {
        currentUser = sessionData.user;
        syncUserIdInUrl(currentUser);
      }
      loadAppWithToken(currentToken);
    })
    .catch(() => loadAppWithToken(currentToken));

  async function loadAppWithToken(token) {
    try {
      let apiToken = token;
      if (!isJwtToken(apiToken)) {
        const validation = await request(
          '/api/token/validate/' + encodeURIComponent(apiToken),
          'GET',
          null,
          false,
        );
        if (!validation.valid) {
          throw new Error('Invalid or expired token.');
        }
        apiToken = validation.apiToken || apiToken;
      }

      const [cals, session] = await Promise.all([
        request('/api/calendars?token=' + encodeURIComponent(apiToken), 'GET', null, false),
        request('/api/session/user?token=' + encodeURIComponent(apiToken), 'GET', null, false),
      ]);
      
      currentToken = apiToken;
      tokenAllowedCalendars = new Set((cals || []).map(cal => cal.id));
      hasValidToken = true;
      currentUser = session && session.authenticated ? session.user : currentUser;
      syncUserIdInUrl(currentUser);
      allCalendars = cals;

      const completeBootstrapLogin = async () => {
        if (profileOnboardingScreen) {
          profileOnboardingScreen.style.display = 'none';
        }
        if (currentUser && currentUser.id) {
          const pendingCalendarIdsRaw = localStorage.getItem('pendingCalendarIdsToClaim');
          let pendingCalendarIds = [];
          if (pendingCalendarIdsRaw) {
            try {
              const parsedCalendarIds = JSON.parse(pendingCalendarIdsRaw);
              if (Array.isArray(parsedCalendarIds)) {
                pendingCalendarIds = parsedCalendarIds.filter(calendarId => typeof calendarId === 'string' && calendarId.trim());
              }
            } catch (error) {
              console.warn('[BOOTSTRAP] Invalid pending calendar claim payload:', error);
            }
          }
          const tokenToClaim = sharedLinkToken && sharedLinkToken !== authenticatedSessionToken
            ? sharedLinkToken
            : (token && !isJwtToken(token) && token !== authenticatedSessionToken ? token : null);
          if (tokenToClaim || pendingCalendarIds.length > 0) {
            if (tokenToClaim) {
              console.log('[BOOTSTRAP] Claiming shared link for authenticated user');
            }

            await claimTokenResourcesForLoggedInUser(tokenToClaim || currentToken, pendingCalendarIds.length > 0 ? pendingCalendarIds : null);
            if (pendingCalendarIds.length > 0) {
              localStorage.removeItem('pendingCalendarIdsToClaim');
            }
            // Only redirect if we have a URL token to clean up
            if (token && !isJwtToken(token) && token !== authenticatedSessionToken) {
              redirectToUserOnlyUrl(currentUser);
            }
          }
        }

        showAppShell();
        renderSidebar();
        void loadAccessCatalog();
        connectCalendarUpdatesSocket();
        ensureCalendarLoaded();
        if (window.__revealPage) window.__revealPage();
      };

      if (await maybeRequireProfileOnboarding(completeBootstrapLogin)) {
        if (window.__revealPage) window.__revealPage();
        return;
      }

      await completeBootstrapLogin();
    } catch (err) {
      console.error('[BOOTSTRAP] Token validation or protected data load failed:', err);
      hasValidToken = false;
      currentUser = null;
      syncUserIdInUrl(null);
      tokenAllowedCalendars = null;
      hiddenCals = new Set();
      sharedLinkToken = null;
      showLandingScreen({ invalidToken: true, attemptedToken: token });
      if (window.__revealPage) window.__revealPage();
    }
  }
})();
</script>
    ''')

