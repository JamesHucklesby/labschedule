from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import (
    DATABASE_URL,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_SSLMODE,
    POSTGRES_CONNECT_TIMEOUT_SECONDS,
)


class Base(DeclarativeBase):
    pass


class GroupORM(Base):
    __tablename__ = 'groups'

    name: Mapped[str] = mapped_column(String, primary_key=True)


class GroupUserLinkORM(Base):
    __tablename__ = 'group_user_links'

    group_name: Mapped[str] = mapped_column(ForeignKey('groups.name'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'approved'"))
    requested_at: Mapped[str | None] = mapped_column(Text, server_default=text('CURRENT_TIMESTAMP::text'))
    approved_by_user_id: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[str | None] = mapped_column(Text)


class CalendarGroupLinkORM(Base):
    __tablename__ = 'calendar_group_links'

    calendar_id: Mapped[str] = mapped_column(ForeignKey('calendars.id'), primary_key=True)
    group_name: Mapped[str] = mapped_column(ForeignKey('groups.name'), primary_key=True)


class UserCalendarLinkORM(Base):
    __tablename__ = 'user_calendar_links'

    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    calendar_id: Mapped[str] = mapped_column(ForeignKey('calendars.id'), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'approved'"))
    requested_at: Mapped[str | None] = mapped_column(Text, server_default=text('CURRENT_TIMESTAMP::text'))
    approved_by_user_id: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[str | None] = mapped_column(Text)


class CalendarORM(Base):
    __tablename__ = 'calendars'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column('group', ForeignKey('groups.name'), nullable=False, server_default=text("'General'"))
    color: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'#2563eb'"))
    blurb: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    image_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    image_thumb_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class EventORM(Base):
    __tablename__ = 'events'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_uid: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text('1'))
    deleted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start: Mapped[str] = mapped_column(Text, nullable=False)
    end_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    all_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    recurrence_freq: Mapped[str | None] = mapped_column(Text)
    recurrence_interval: Mapped[int | None] = mapped_column(Integer)
    recurrence_until: Mapped[str | None] = mapped_column(Text)
    calendar_id: Mapped[str | None] = mapped_column(ForeignKey('calendars.id'))
    calendar_ids: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'[]'"))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    committed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    modified_by_user_id: Mapped[str | None] = mapped_column(Text)
    modified_at: Mapped[str | None] = mapped_column(Text)
    user_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    event_title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    contact: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class UserORM(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    google_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"))
    login_token: Mapped[str | None] = mapped_column(Text, unique=True)
    picture_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text('CURRENT_TIMESTAMP::text'))
    last_login: Mapped[str | None] = mapped_column(Text, server_default=text('CURRENT_TIMESTAMP::text'))


def _build_database_url() -> Any:
    if DATABASE_URL:
        return DATABASE_URL
    return URL.create(
        'postgresql+psycopg2',
        username=POSTGRES_USER,
        password=POSTGRES_PASSWORD or None,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
    )


_DB_CONNECT_ARGS: dict[str, Any] = {
    'connect_timeout': POSTGRES_CONNECT_TIMEOUT_SECONDS,
    'sslmode': POSTGRES_SSLMODE,
}

ENGINE = create_engine(
    _build_database_url(),
    pool_pre_ping=True,
    connect_args=_DB_CONNECT_ARGS,
)

SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)
