# Lab Schedule — Bioinformatics Access Portal

Real-time collaborative calendar application for lab scheduling with Google OAuth authentication.

## Features

- ✅ Real-time calendar synchronization via WebSocket
- ✅ Google OAuth 2.0 authentication (aucklanduni.ac.nz domain-restricted)
- ✅ Drag-and-drop event management
- ✅ Recurring event support (daily, weekly, monthly with intervals)
- ✅ Multi-calendar support with token-based access control
- ✅ Offline detection with reconnection handling
- ✅ Save notifications with user feedback
- ✅ FullCalendar UI (week/day/month/list views)
- ✅ PostgreSQL backend with environment-based connection settings

## Quick Start

### 1. Configure Environment

Copy the example environment file and fill in your OAuth and PostgreSQL settings:

```bash
cp .env.example .env
```

Required database settings are `DATABASE_URL` or the `POSTGRES_*` variables. If you are using Docker Compose, the app container will receive a `DATABASE_URL` automatically.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Google OAuth

See [OAUTH_SETUP.md](OAUTH_SETUP.md) for detailed setup instructions.

Quick summary:
1. Create a [Google Cloud Project](https://console.cloud.google.com/)
2. Enable Google+ API
3. Create OAuth 2.0 credentials (Web application)
4. Copy `.env.example` to `.env` and fill in credentials:

```bash
cp .env.example .env
# Edit .env with your Google OAuth credentials
```

The login flow is preconfigured for `aucklanduni.ac.nz` via Google’s hosted-domain hint. If you want Google to prefill a specific Auckland account, set `GOOGLE_LOGIN_HINT` in `.env`.

### 4. Run the Application

```bash
python main.py
```

Open `http://localhost:8080` in your browser.

### Docker Compose

You can also run the app and PostgreSQL together with:

```bash
docker compose up --build
```

Automated backups are handled by `scripts/backup_postgres.py` and are started by the app container at boot via `scripts/start_app_with_backup.sh`.
The app Docker image installs `pg_dump` from PostgreSQL 18 client packages to match the database server version.
The script:
- creates a full SQL dump using `pg_dump`,
- compresses each dump to a `.zip` file in `./backups/`,
- keeps at most one backup for any 24-hour period,
- removes backup `.zip` files older than 30 days,
- runs every 24 hours by default.

You can tune behavior with env vars in Compose: `BACKUP_ENABLED`, `BACKUP_INTERVAL_HOURS`, and `BACKUP_RETENTION_DAYS`.

For secure production deployment, set these app environment variables:
- `APP_ENV=production`
- `APP_BASE_URL=https://<your-domain>`
- `APP_SECRET_KEY=<strong-random-secret>`
- `SESSION_COOKIE_SECURE=true`
- `APP_ALLOWED_HOSTS=<your-domain,localhost>`

Optional runtime hardening and optimization:
- `ENABLE_SECURITY_HEADERS=1`
- `ENABLE_GZIP=1`
- `GZIP_MINIMUM_SIZE=500`

Run it once:

```bash
python scripts/backup_postgres.py --run-once
```

Run continuously (24-hour interval):

```bash
python scripts/backup_postgres.py
```

If Docker reports a credential-helper error while pulling `python:3.11-slim`, run the Windows helper instead:

```powershell
.
un-docker.ps1
```

That helper runs Compose with a clean `DOCKER_CONFIG`, which bypasses broken saved credentials for public image pulls.

## Authentication

- Users sign in with their **@aucklanduni.ac.nz** Google account
- First login automatically creates a user record in PostgreSQL
- Credentials are NOT stored; only Google OAuth tokens are used for verification
- The Google login redirect includes the Auckland University hosted-domain hint, and can optionally prefill a specific email address via `GOOGLE_LOGIN_HINT`
- Session tokens provide calendar access based on user permissions

## API Endpoints

### Events
- `GET /api/events?start=<iso>&end=<iso>` — List events
- `GET /api/events/{event_id}` — Get event details
- `POST /api/events` — Create event
- `PUT /api/events/{event_id}` — Update event
- `DELETE /api/events/{event_id}` — Delete event

### Calendars
- `GET /api/calendars?token=<token>` — List accessible calendars

### WebSocket
- `WS /ws/calendar-updates` — Single real-time channel for calendar and access updates

### Authentication
- `GET /auth/google-login` — Initiate Google OAuth flow
- `GET /auth/callback` — OAuth callback handler

## Database Schema

### calendars
- `id` — Calendar ID
- `name` — Calendar name
- `group` — Calendar group/category
- `color` — Display color

### events
- `id`, `version`, `deleted` — Event tracking
- `title`, `description`, `start`, `end` — Event details
- `all_day` — All-day event flag
- `calendar_ids` — Accessible calendar IDs (JSON array)
- `recurrence_*` — Recurrence rules

### users
- `id` — User ID
- `google_id` — Google account ID
- `email` — User email (@aucklanduni.ac.nz)
- `name`, `picture_url` — User profile
- `calendar_ids` — Accessible calendars
- `created_at`, `last_login` — Timestamps

### links
- Legacy table removed. Access tokens are stored on `users.login_token`.

## Development

### Reset Database

```bash
docker compose down -v
docker compose up --build
```

### Environment Variables

See `.env.example` for all available configuration options.

Key variables:

- `DATABASE_URL` or the `POSTGRES_*` variables for PostgreSQL connectivity
- `APP_BASE_URL` for building absolute login URLs
- `GOOGLE_REDIRECT_URI` for OAuth callback configuration

### Testing

Token-based access:
```
http://localhost:8080/?token=science
```

OAuth login:
```
http://localhost:8080/auth/google-login
```

## Troubleshooting

**Blank screen on load?**
- Check browser console for errors
- Verify token is valid: `GET /api/calendars?token=<token>`

**OAuth not working?**
- See [OAUTH_SETUP.md](OAUTH_SETUP.md) troubleshooting section
- Verify .env file exists and credentials are correct

**Real-time sync not working?**
- Check WebSocket connection in browser DevTools
- Verify firewall allows WebSocket connections

## License

Proprietary — Bioinformatics Lab

