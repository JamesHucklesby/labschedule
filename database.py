import json
import secrets
from datetime import datetime
from contextlib import contextmanager
from threading import RLock
from time import sleep, time
from typing import Any, Callable, Generator, TypeVar
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DatabaseError as SQLAlchemyDatabaseError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlalchemy.orm import Session

from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
from models import ENGINE, SessionLocal, Base, CalendarORM, EventORM, GroupORM, GroupUserLinkORM, CalendarGroupLinkORM, LabGroupORM, UserCalendarLinkORM, UserORM, UserSavedShareLinkORM
from utils import _split_legacy_event_title, _compose_display_title

# ── Globals ───────────────────────────────────────────────────────────────────

DB_LOCK = RLock()
_DB_WRITE_LOCK_TIMEOUT_SECONDS = 5.0
_DB_WRITE_RETRIES = 3
_DB_WRITE_RETRY_BASE_DELAY_SECONDS = 0.05

_DICEWARE_WORDS: tuple[str, ...] = (
    'amber', 'anchor', 'apple', 'artist', 'autumn', 'badge', 'bamboo', 'beacon', 'birch', 'bison',
    'blossom', 'breeze', 'brook', 'cable', 'cactus', 'candle', 'canyon', 'captain', 'carpet', 'castle',
    'cedar', 'circle', 'citrus', 'clover', 'cobalt', 'comet', 'coral', 'cotton', 'crystal', 'daisy',
    'delta', 'desert', 'dolphin', 'dragon', 'drift', 'eagle', 'echo', 'ember', 'falcon', 'feather',
    'fern', 'fjord', 'forest', 'fossil', 'galaxy', 'garden', 'glacier', 'granite', 'harbor', 'hazel',
    'helium', 'honey', 'horizon', 'island', 'ivory', 'jacket', 'jasmine', 'jungle', 'juniper', 'kernel',
    'kiwi', 'ladder', 'lagoon', 'lantern', 'lavender', 'legend', 'lemon', 'lilac', 'linen', 'lotus',
    'mango', 'maple', 'marble', 'meadow', 'meteor', 'midnight', 'mint', 'mosaic', 'mountain', 'nectar',
    'night', 'oasis', 'ocean', 'olive', 'onyx', 'orchid', 'otter', 'pebble', 'pepper', 'phoenix',
    'pine', 'pluto', 'prairie', 'quartz', 'rabbit', 'raven', 'reef', 'river', 'rocket', 'rose',
    'sable', 'saffron', 'sapphire', 'scarlet', 'shadow', 'silk', 'silver', 'sky', 'solstice', 'sparrow',
    'spice', 'spruce', 'star', 'stone', 'summit', 'sunset', 'tiger', 'timber', 'topaz', 'trail',
    'tulip', 'twilight', 'valley', 'velvet', 'violet', 'voyage', 'water', 'willow', 'winter', 'zephyr',
)

T = TypeVar('T')


def _normalize_group_name(value: str | None) -> str | None:
    normalized = str(value or '').strip()
    return normalized or None


# ── Session context manager ───────────────────────────────────────────────────

@contextmanager
def _db_session() -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy ORM session, committing on success."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Write lock ────────────────────────────────────────────────────────────────

@contextmanager
def _acquire_write_lock() -> Any:
    acquired = DB_LOCK.acquire(timeout=_DB_WRITE_LOCK_TIMEOUT_SECONDS)
    if not acquired:
        raise HTTPException(status_code=503, detail='Database is busy. Please retry.')
    try:
        yield
    finally:
        DB_LOCK.release()


def _is_db_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, SQLAlchemyOperationalError):
        return True
    dbapi_exc = getattr(exc, 'orig', exc)
    pgcode = getattr(dbapi_exc, 'pgcode', None) or getattr(exc, 'pgcode', None)
    if pgcode in {'40001', '40P01', '55P03'}:
        return True
    exc_text = str(exc).lower()
    return (
        'deadlock detected' in exc_text
        or 'could not obtain lock' in exc_text
        or 'lock timeout' in exc_text
    )


def _run_write_with_retry(operation: Callable[[], T]) -> T:
    last_exc: Exception | None = None
    for attempt in range(_DB_WRITE_RETRIES):
        try:
            return operation()
        except (SQLAlchemyOperationalError, SQLAlchemyDatabaseError) as exc:
            if not _is_db_retryable_error(exc):
                raise
            last_exc = exc
            if attempt >= _DB_WRITE_RETRIES - 1:
                break
            sleep(_DB_WRITE_RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
    raise HTTPException(status_code=503, detail='Database is busy. Please retry.') from last_exc


def _ensure_group_names(session: Session, group_names: list[str]) -> None:
    unique_names = sorted({name for name in (_normalize_group_name(value) for value in group_names) if name})
    for group_name in unique_names:
        session.execute(
            text('INSERT INTO groups (name) VALUES (:name) ON CONFLICT (name) DO NOTHING'),
            {'name': group_name},
        )


def _ensure_lab_group_names(session: Session, lab_group_names: list[str]) -> None:
    unique_names = sorted({name for name in (_normalize_group_name(value) for value in lab_group_names) if name})
    for lab_group_name in unique_names:
        session.execute(
            text('INSERT INTO lab_groups (name) VALUES (:name) ON CONFLICT (name) DO NOTHING'),
            {'name': lab_group_name},
        )


def _get_user_calendar_ids(session: Session, user_id: str) -> list[str]:
    calendar_ids = session.scalars(
        select(UserCalendarLinkORM.calendar_id)
        .where(UserCalendarLinkORM.user_id == user_id)
        .where(UserCalendarLinkORM.status == 'approved')
        .order_by(UserCalendarLinkORM.calendar_id.asc())
    ).all()
    return [str(calendar_id) for calendar_id in calendar_ids if calendar_id]


def _replace_user_calendar_links(
    session: Session,
    user_id: str,
    calendar_ids: list[str],
    *,
    approved_by_user_id: str | None = None,
    approved_at: str | None = None,
    requested_at: str | None = None,
) -> None:
    effective_requested_at = requested_at or approved_at or datetime.now().astimezone().isoformat()
    deduped = []
    seen: set[str] = set()
    for calendar_id in calendar_ids:
        normalized = str(calendar_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    session.execute(
        text('DELETE FROM user_calendar_links WHERE user_id = :user_id'),
        {'user_id': user_id},
    )
    for calendar_id in deduped:
        session.add(
            UserCalendarLinkORM(
                user_id=user_id,
                calendar_id=calendar_id,
                status='approved',
                requested_at=effective_requested_at,
                approved_by_user_id=approved_by_user_id,
                approved_at=approved_at,
            )
        )


def _upsert_user_calendar_link(
    session: Session,
    user_id: str,
    calendar_id: str,
    *,
    status: str,
    approved_by_user_id: str | None = None,
    requested_at: str | None = None,
    approved_at: str | None = None,
) -> None:
    effective_requested_at = requested_at or approved_at or datetime.now().astimezone().isoformat()
    session.execute(
        pg_insert(UserCalendarLinkORM).values(
            user_id=user_id,
            calendar_id=calendar_id,
            status=status,
            requested_at=effective_requested_at,
            approved_by_user_id=approved_by_user_id,
            approved_at=approved_at,
        ).on_conflict_do_update(
            index_elements=[UserCalendarLinkORM.user_id, UserCalendarLinkORM.calendar_id],
            set_={
                'status': status,
                'requested_at': effective_requested_at,
                'approved_by_user_id': approved_by_user_id,
                'approved_at': approved_at,
            },
        )
    )


def _replace_user_group_links(
    session: Session,
    user_id: str,
    group_names: list[str],
    *,
    approved_by_user_id: str | None = None,
    approved_at: str | None = None,
    requested_at: str | None = None,
) -> None:
    effective_requested_at = requested_at or approved_at or datetime.now().astimezone().isoformat()
    deduped: list[str] = []
    seen: set[str] = set()
    for group_name in group_names:
        normalized = _normalize_group_name(group_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    session.execute(
        text('DELETE FROM group_user_links WHERE user_id = :user_id'),
        {'user_id': user_id},
    )

    for group_name in deduped:
        session.execute(
            pg_insert(GroupUserLinkORM).values(
                group_name=group_name,
                user_id=user_id,
                status='approved',
                requested_at=effective_requested_at,
                approved_by_user_id=approved_by_user_id,
                approved_at=approved_at,
            ).on_conflict_do_update(
                index_elements=[GroupUserLinkORM.group_name, GroupUserLinkORM.user_id],
                set_={
                    'status': 'approved',
                    'requested_at': effective_requested_at,
                    'approved_by_user_id': approved_by_user_id,
                    'approved_at': approved_at,
                },
            )
        )


def _record_user_saved_share_link(session: Session, user_id: str, source_user_id: str) -> None:
    normalized_user_id = str(user_id or '').strip()
    normalized_source_user_id = str(source_user_id or '').strip()
    if not normalized_user_id or not normalized_source_user_id or normalized_user_id == normalized_source_user_id:
        return
    session.execute(
        pg_insert(UserSavedShareLinkORM).values(
            user_id=normalized_user_id,
            source_user_id=normalized_source_user_id,
            created_at=datetime.now().astimezone().isoformat(),
        ).on_conflict_do_nothing(
            index_elements=[UserSavedShareLinkORM.user_id, UserSavedShareLinkORM.source_user_id],
        )
    )


def _upsert_user_group_link(
    session: Session,
    user_id: str,
    group_name: str,
    *,
    status: str,
    approved_by_user_id: str | None = None,
    requested_at: str | None = None,
    approved_at: str | None = None,
) -> None:
    effective_requested_at = requested_at or approved_at or datetime.now().astimezone().isoformat()
    session.execute(
        pg_insert(GroupUserLinkORM).values(
            group_name=group_name,
            user_id=user_id,
            status=status,
            requested_at=effective_requested_at,
            approved_by_user_id=approved_by_user_id,
            approved_at=approved_at,
        ).on_conflict_do_update(
            index_elements=[GroupUserLinkORM.group_name, GroupUserLinkORM.user_id],
            set_={
                'status': status,
                'requested_at': effective_requested_at,
                'approved_by_user_id': approved_by_user_id,
                'approved_at': approved_at,
            },
        )
    )


def _replace_calendar_group_links(session: Session, calendar_id: str, group_names: list[str]) -> None:
    # Flush pending ORM inserts first so newly created calendars are visible
    # before we write dependent link rows.
    session.flush()
    calendar_exists = session.scalar(
        select(CalendarORM.id)
        .where(CalendarORM.id == calendar_id)
        .limit(1)
    )
    if calendar_exists is None:
        raise HTTPException(status_code=404, detail='Calendar not found.')

    deduped: list[str] = []
    seen: set[str] = set()
    for group_name in group_names:
        normalized = _normalize_group_name(group_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    session.execute(
        text('DELETE FROM calendar_group_links WHERE calendar_id = :calendar_id'),
        {'calendar_id': calendar_id},
    )
    for group_name in deduped:
        session.add(CalendarGroupLinkORM(calendar_id=calendar_id, group_name=group_name))


def _get_user_group_name_from_links(session: Session, user_id: str) -> str | None:
    group_name = session.scalar(
        select(GroupUserLinkORM.group_name)
        .where(GroupUserLinkORM.user_id == user_id)
        .where(GroupUserLinkORM.status == 'approved')
        .where(GroupUserLinkORM.group_name.isnot(None))
        .where(func.trim(GroupUserLinkORM.group_name) != '')
        .order_by(GroupUserLinkORM.group_name.asc())
        .limit(1)
    )
    return _normalize_group_name(group_name)


def _get_user_group_names_from_links(session: Session, user_id: str) -> list[str]:
    group_names = session.scalars(
        select(GroupUserLinkORM.group_name)
        .where(GroupUserLinkORM.user_id == user_id)
        .where(GroupUserLinkORM.status == 'approved')
        .where(GroupUserLinkORM.group_name.isnot(None))
        .where(func.trim(GroupUserLinkORM.group_name) != '')
        .distinct()
        .order_by(GroupUserLinkORM.group_name.asc())
    ).all()
    return [name for name in (_normalize_group_name(value) for value in group_names) if name]


def _merge_user_access_from_source(
    session: Session,
    *,
    source_user_id: str,
    target_user_id: str,
    requested_calendar_ids: list[str] | None = None,
    approved_by_user_id: str | None = None,
    approved_at: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    source_calendar_ids = sorted(_get_user_calendar_ids(session, source_user_id) or [])
    source_group_names = sorted(_get_user_group_names_from_links(session, source_user_id) or [])

    if requested_calendar_ids:
        requested_set = {str(calendar_id).strip() for calendar_id in requested_calendar_ids if str(calendar_id or '').strip()}
        claimed_calendar_ids = [calendar_id for calendar_id in source_calendar_ids if calendar_id in requested_set]
    else:
        claimed_calendar_ids = source_calendar_ids

    current_calendar_ids = sorted(_get_user_calendar_ids(session, target_user_id) or [])
    merged_calendar_ids = sorted(set(current_calendar_ids).union(claimed_calendar_ids))

    current_group_names = sorted(_get_user_group_names_from_links(session, target_user_id) or [])
    merged_group_names = sorted(set(current_group_names).union(source_group_names))

    effective_approved_by_user_id = approved_by_user_id or target_user_id
    effective_approved_at = approved_at or datetime.now().astimezone().isoformat()
    effective_requested_at = requested_at or effective_approved_at

    _replace_user_calendar_links(
        session,
        target_user_id,
        merged_calendar_ids,
        approved_by_user_id=effective_approved_by_user_id,
        approved_at=effective_approved_at,
        requested_at=effective_requested_at,
    )
    _replace_user_group_links(
        session,
        target_user_id,
        merged_group_names,
        approved_by_user_id=effective_approved_by_user_id,
        approved_at=effective_approved_at,
        requested_at=effective_requested_at,
    )

    return {
        'sourceCalendarIds': source_calendar_ids,
        'sourceGroupNames': source_group_names,
        'claimedCalendarIds': claimed_calendar_ids,
        'mergedCalendarIds': merged_calendar_ids,
        'mergedGroupNames': merged_group_names,
    }


# ── Version helpers ───────────────────────────────────────────────────────────

def _epoch_ms_now() -> int:
    return int(time() * 1000)


def _next_event_version_ms(session: Session, event_uid: str) -> int:
    max_version = session.scalar(
        select(func.max(EventORM.version)).where(EventORM.event_uid == event_uid)
    )
    return max(_epoch_ms_now(), (int(max_version) if max_version is not None else 0) + 1)


# ── Token / email generators ──────────────────────────────────────────────────

def _generate_unique_login_token(session: Session) -> str:
    """Generate a diceware-style token unique in users.login_token."""
    for _ in range(20):
        candidate = ''.join(secrets.choice(_DICEWARE_WORDS) for _ in range(4)).lower()
        exists = session.scalar(
            select(UserORM.id).where(UserORM.login_token == candidate).limit(1)
        )
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail='Failed to generate a unique login token.')


def _generate_unique_local_email(session: Session) -> str:
    """Generate a unique local placeholder email for non-Google admin-created users."""
    for _ in range(20):
        candidate = f'local-{uuid4().hex[:16]}@local.invalid'
        exists = session.scalar(
            select(UserORM.id).where(UserORM.email == candidate).limit(1)
        )
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail='Failed to generate a unique local email.')


# ── Query helpers ─────────────────────────────────────────────────────────────

def _build_latest_events_stmt() -> tuple[Any, Any, Any]:
    """Return (stmt, event_alias, ranked_subq) — latest EventORM version per event_uid."""
    from sqlalchemy import desc
    from sqlalchemy.orm import aliased

    ranked_subq = (
        select(
            EventORM,
            func.row_number().over(
                partition_by=EventORM.event_uid,
                order_by=[desc(EventORM.version), desc(EventORM.id)],
            ).label('rn'),
        ).subquery('ranked')
    )
    event_alias = aliased(EventORM, ranked_subq)
    base_stmt = select(event_alias).where(ranked_subq.c.rn == 1)
    return base_stmt, event_alias, ranked_subq


# ── Schema init / migrations ──────────────────────────────────────────────────

def init_db() -> None:
    Base.metadata.create_all(ENGINE)

    with ENGINE.connect() as conn:
        print(
            f'[startup] Connected to PostgreSQL at {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}.',
            flush=True,
        )

        conn.execute(text('DROP TABLE IF EXISTS links'))
        conn.execute(text('DROP TABLE IF EXISTS access_requests'))

        for ddl in [
            'CREATE TABLE IF NOT EXISTS groups (name TEXT PRIMARY KEY)',
            'CREATE TABLE IF NOT EXISTS lab_groups (name TEXT PRIMARY KEY)',
            'CREATE TABLE IF NOT EXISTS group_user_links (group_name TEXT NOT NULL REFERENCES groups(name) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, status TEXT NOT NULL DEFAULT \'approved\', requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, approved_by_user_id TEXT, approved_at TEXT, PRIMARY KEY (group_name, user_id))',
            'CREATE TABLE IF NOT EXISTS calendar_group_links (calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE, group_name TEXT NOT NULL REFERENCES groups(name) ON DELETE CASCADE, PRIMARY KEY (calendar_id, group_name))',
            'CREATE TABLE IF NOT EXISTS user_calendar_links (user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE, status TEXT NOT NULL DEFAULT \'approved\', requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, approved_by_user_id TEXT, approved_at TEXT, PRIMARY KEY (user_id, calendar_id))',
            'CREATE TABLE IF NOT EXISTS user_saved_share_links (user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, source_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, source_user_id))',
            "CREATE TABLE IF NOT EXISTS user_passkeys (credential_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL DEFAULT 'Passkey', public_key TEXT NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS event_uid TEXT',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 1',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS deleted INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS recurrence_freq TEXT',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS recurrence_interval INTEGER',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS recurrence_until TEXT',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS calendar_id TEXT REFERENCES calendars(id)',
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS calendar_ids TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''",
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS committed INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS modified_by_user_id TEXT',
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS modified_at TEXT',
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS user_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_title TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS contact TEXT NOT NULL DEFAULT ''",
            'ALTER TABLE events ADD COLUMN IF NOT EXISTS end_time TEXT',
            "ALTER TABLE calendars ADD COLUMN IF NOT EXISTS \"group\" TEXT NOT NULL DEFAULT 'General'",
            "ALTER TABLE calendars ADD COLUMN IF NOT EXISTS blurb TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE calendars ADD COLUMN IF NOT EXISTS image_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE calendars ADD COLUMN IF NOT EXISTS image_thumb_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'",
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS service_account BOOLEAN NOT NULL DEFAULT false',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS login_token TEXT',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS email_login_token TEXT',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS email_login_expires_at TEXT',
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS contact TEXT NOT NULL DEFAULT ''",
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS lab_group TEXT',
            "ALTER TABLE group_user_links ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'approved'",
            "ALTER TABLE group_user_links ADD COLUMN IF NOT EXISTS requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            'ALTER TABLE group_user_links ADD COLUMN IF NOT EXISTS approved_by_user_id TEXT',
            'ALTER TABLE group_user_links ADD COLUMN IF NOT EXISTS approved_at TEXT',
            "ALTER TABLE user_calendar_links ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'approved'",
            "ALTER TABLE user_calendar_links ADD COLUMN IF NOT EXISTS requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            'ALTER TABLE user_calendar_links ADD COLUMN IF NOT EXISTS approved_by_user_id TEXT',
            'ALTER TABLE user_calendar_links ADD COLUMN IF NOT EXISTS approved_at TEXT',
            'ALTER TABLE user_passkeys ADD COLUMN IF NOT EXISTS public_key TEXT NOT NULL DEFAULT \'\'',
            "ALTER TABLE user_passkeys ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT 'Passkey'",
            'ALTER TABLE user_passkeys ADD COLUMN IF NOT EXISTS sign_count INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE user_passkeys ADD COLUMN IF NOT EXISTS transports TEXT',
            "ALTER TABLE user_passkeys ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        ]:
            conn.execute(text(ddl))
        conn.commit()

        # Rename/migrate legacy "end" column → "end_time".
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'events' AND column_name IN ('end', 'end_time')
        """))
        existing_cols = {row[0] for row in result}
        if 'end' in existing_cols and 'end_time' not in existing_cols:
            conn.execute(text('ALTER TABLE events RENAME COLUMN "end" TO end_time'))
            conn.commit()
            print('[startup] Renamed legacy "end" column to "end_time".', flush=True)
        elif 'end' in existing_cols and 'end_time' in existing_cols:
            conn.execute(text('UPDATE events SET end_time = COALESCE(end_time, "end") WHERE end_time IS NULL'))
            conn.execute(text('ALTER TABLE events DROP COLUMN "end"'))
            conn.commit()
            print('[startup] Migrated data from "end" to "end_time" and dropped legacy column.', flush=True)

        # Widen version column from INTEGER → BIGINT.
        conn.execute(text("""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'events' AND column_name = 'version'
                  AND data_type = 'integer'
              ) THEN
                ALTER TABLE events ALTER COLUMN version TYPE BIGINT;
              END IF;
            END$$
        """))
        conn.commit()

        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login_token ON users(login_token)'))
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_login_token ON users(email_login_token)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_user_passkeys_user_id ON user_passkeys(user_id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_users_lab_group ON users(lab_group)'))
        conn.execute(text('ALTER TABLE users ALTER COLUMN lab_group DROP DEFAULT'))
        conn.execute(text('ALTER TABLE users ALTER COLUMN lab_group DROP NOT NULL'))
        conn.execute(text("UPDATE users SET lab_group = NULL WHERE lab_group IS NOT NULL AND trim(lab_group) = ''"))
        conn.execute(text("""
            UPDATE users
            SET role = CASE
              WHEN lower(email) = 'jhuc964@aucklanduni.ac.nz' OR lower(name) = 'james hucklesby' THEN 'admin'
              WHEN role IS NULL OR trim(role) = '' THEN 'user'
              ELSE role
            END
        """))
        conn.commit()

    with _db_session() as session:
        # Seed group names from calendars and link tables.
        group_names: set[str] = set()
        group_names.update(
            name for (name,) in session.execute(
                select(CalendarORM.group_name).distinct()
            ).all() if _normalize_group_name(name)
        )
        group_names.update(
            name for (name,) in session.execute(
                select(GroupUserLinkORM.group_name).distinct()
            ).all() if _normalize_group_name(name)
        )
        group_names.add('General')

        _ensure_group_names(session, list(group_names))
        lab_group_names = [
            str(name).strip()
            for name in session.scalars(
                select(UserORM.lab_group)
                .where(UserORM.lab_group.isnot(None))
                .where(func.trim(UserORM.lab_group) != '')
                .distinct()
                .order_by(UserORM.lab_group.asc())
            ).all()
            if str(name or '').strip()
        ]
        _ensure_lab_group_names(session, lab_group_names)

        legacy_calendar_group_pairs = session.scalars(select(CalendarORM)).all()
        for calendar in legacy_calendar_group_pairs:
            session.merge(CalendarGroupLinkORM(calendar_id=calendar.id, group_name=calendar.group_name or 'General'))

        legacy_user_columns = set(
            name for (name,) in session.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'users'
                      AND column_name IN ('calendar_ids', 'group_ids', 'group_name')
                """)
            ).all()
        )
        legacy_users = []
        if legacy_user_columns:
            columns = ['id']
            if 'calendar_ids' in legacy_user_columns:
                columns.append('calendar_ids')
            if 'group_ids' in legacy_user_columns:
                columns.append('group_ids')
            if 'group_name' in legacy_user_columns:
                columns.append('group_name')
            legacy_users = session.execute(text(f"SELECT {', '.join(columns)} FROM users ORDER BY id ASC")).all()

        for legacy_user in legacy_users:
            legacy_user_map = legacy_user._mapping
            user_id = str(legacy_user_map['id'])
            if 'calendar_ids' in legacy_user_columns:
                raw_calendar_ids = legacy_user_map.get('calendar_ids')
                try:
                    calendar_ids = json.loads(raw_calendar_ids) if raw_calendar_ids else []
                except json.JSONDecodeError:
                    calendar_ids = []
                valid_calendar_ids = set(session.scalars(select(CalendarORM.id)).all())
                filtered_calendar_ids = [str(calendar_id) for calendar_id in calendar_ids if calendar_id and str(calendar_id) in valid_calendar_ids]
                _replace_user_calendar_links(session, user_id, filtered_calendar_ids)

            legacy_group_values: list[str] = []
            if 'group_ids' in legacy_user_columns:
                raw_group_ids = legacy_user_map.get('group_ids')
                try:
                    legacy_group_values.extend(json.loads(raw_group_ids) if raw_group_ids else [])
                except json.JSONDecodeError:
                    pass
            if 'group_name' in legacy_user_columns:
                legacy_group_values.append(legacy_user_map.get('group_name'))

            unique_group_values: list[str] = []
            seen_group_values: set[str] = set()
            for group_name in legacy_group_values:
                normalized = _normalize_group_name(group_name)
                if not normalized or normalized in seen_group_values:
                    continue
                seen_group_values.add(normalized)
                unique_group_values.append(normalized)

            if unique_group_values:
                _replace_user_group_links(session, user_id, unique_group_values)

        users_without_tokens = session.scalars(
            select(UserORM).where(
                or_(UserORM.login_token.is_(None), func.trim(UserORM.login_token) == '')
            ).order_by(UserORM.id.asc())
        ).all()
        for user in users_without_tokens:
            user.login_token = _generate_unique_login_token(session)

        events_no_cal_ids = session.scalars(
            select(EventORM).where(
                or_(EventORM.calendar_ids.is_(None), EventORM.calendar_ids == '')
            )
        ).all()
        for event in events_no_cal_ids:
            cal_ids = [event.calendar_id] if event.calendar_id else []
            event.calendar_ids = json.dumps(cal_ids)

        session.execute(text("UPDATE events SET event_uid = id WHERE event_uid IS NULL OR event_uid = ''"))
        session.execute(text('UPDATE events SET version = 1 WHERE version IS NULL OR version < 1'))
        session.execute(text('UPDATE events SET deleted = 0 WHERE deleted IS NULL'))
        session.execute(text("UPDATE events SET notes = '' WHERE notes IS NULL"))
        session.execute(text('UPDATE events SET committed = 0 WHERE committed IS NULL'))
        session.execute(text("UPDATE events SET user_name = '' WHERE user_name IS NULL"))
        session.execute(text("UPDATE events SET event_title = '' WHERE event_title IS NULL"))
        session.execute(text("UPDATE events SET contact = '' WHERE contact IS NULL"))
        session.execute(text("UPDATE users SET contact = '' WHERE contact IS NULL"))
        session.execute(text("UPDATE users SET lab_group = NULL WHERE lab_group IS NOT NULL AND trim(lab_group) = ''"))

        events_needing_split = session.scalars(
            select(EventORM).where(
                or_(EventORM.user_name.is_(None), EventORM.user_name == ''),
            )
        ).all()
        for event in events_needing_split:
            inferred_user, inferred_et = _split_legacy_event_title(event.title)
            event.user_name = inferred_user
            event.event_title = inferred_et

        session.execute(text("""
            UPDATE events
            SET modified_at = COALESCE(modified_at, start, CURRENT_TIMESTAMP::text)
            WHERE modified_at IS NULL OR trim(modified_at) = ''
        """))

        # Normalize legacy modified_by_user_id values before adding FK.
        session.execute(text("""
            UPDATE events
            SET modified_by_user_id = NULL
            WHERE modified_by_user_id IS NOT NULL
              AND trim(modified_by_user_id) = ''
        """))
        session.execute(text("""
            UPDATE events e
            SET modified_by_user_id = NULL
            WHERE modified_by_user_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM users u
                WHERE u.id = e.modified_by_user_id
              )
        """))

        _ensure_group_names(session, ['General'])

    with _db_session() as session:
        # Add the FK constraints after the groups table has been populated and committed.
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'calendars_group_fkey'
                        AND table_name = 'calendars'
                ) THEN
                    ALTER TABLE calendars
                        ADD CONSTRAINT calendars_group_fkey
                        FOREIGN KEY ("group") REFERENCES groups(name);
                END IF;
            END$$
        """))
        session.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'users_group_name_fkey'
                        AND table_name = 'users'
                ) THEN
                    ALTER TABLE users DROP CONSTRAINT users_group_name_fkey;
                END IF;
            END$$
        """))
        session.execute(text('ALTER TABLE users DROP COLUMN IF EXISTS group_name'))
        session.execute(text('ALTER TABLE users DROP COLUMN IF EXISTS group_ids'))
        session.execute(text('ALTER TABLE users DROP COLUMN IF EXISTS calendar_ids'))
        session.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'users'
                      AND constraint_name = 'users_lab_group_fkey'
                ) THEN
                    ALTER TABLE users DROP CONSTRAINT users_lab_group_fkey;
                END IF;
            END$$
        """))
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'users'
                      AND constraint_name = 'users_lab_group_fkey'
                ) THEN
                    ALTER TABLE users
                        ADD CONSTRAINT users_lab_group_fkey
                        FOREIGN KEY (lab_group) REFERENCES lab_groups(name)
                        ON DELETE SET NULL;
                END IF;
            END$$
        """))
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'events'
                      AND constraint_name = 'events_modified_by_user_id_fkey'
                ) THEN
                    ALTER TABLE events
                        ADD CONSTRAINT events_modified_by_user_id_fkey
                        FOREIGN KEY (modified_by_user_id) REFERENCES users(id)
                        ON DELETE SET NULL;
                END IF;
            END$$
        """))
