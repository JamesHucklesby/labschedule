from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RecurrenceRule(BaseModel):
    freq: Literal['daily', 'weekly', 'monthly']
    interval: int = Field(default=1, ge=1)
    until: str | None = None


class CalendarResource(BaseModel):
    id: str
    name: str
    group: str
    color: str


class CalendarLink(BaseModel):
    token: str
    name: str
    calendarIds: list[str]


class LinkResourceUpdate(BaseModel):
    calendarIds: list[str] = Field(default_factory=list)
    groupNames: list[str] = Field(default_factory=list)


class LinkCreateRequest(BaseModel):
    name: str
    token: str | None = None
    calendarIds: list[str] = Field(default_factory=list)


class CalendarAccessClaimRequest(BaseModel):
    calendarIds: list[str] = Field(default_factory=list)


class AdminUserCreateRequest(BaseModel):
    name: str
    email: str | None = None
    calendarIds: list[str] = Field(default_factory=list)
    groupNames: list[str] = Field(default_factory=list)


class GroupCreateRequest(BaseModel):
    name: str


class CalendarGroupUpdate(BaseModel):
    groupName: str


class GroupResourceCreateRequest(BaseModel):
    name: str


class CalendarAdminUpdateRequest(BaseModel):
    name: str
    groupName: str
    color: str
    blurb: str
    imageUrl: str


class LogoutRequest(BaseModel):
    user_id: str | None = None


class TokenValidationResult(BaseModel):
    valid: bool
    token: str
    apiToken: str | None = None
    name: str | None = None
    calendarIds: list[str] = Field(default_factory=list)


class EventBase(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str = ''
    name: str = ''
    eventTitle: str = ''
    contact: str = ''
    start: str
    end: str | None = None
    allDay: bool = False
    calendarId: str | None = None
    calendarIds: list[str] = Field(default_factory=list)
    calendarColors: list[str] = Field(default_factory=list)
    recurrence: RecurrenceRule | None = None
    notes: str = ''
    committed: bool = False


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = None
    name: str | None = None
    eventTitle: str | None = None
    contact: str | None = None
    start: str | None = None
    end: str | None = None
    allDay: bool | None = None
    calendarId: str | None = None
    calendarIds: list[str] | None = None
    recurrence: RecurrenceRule | None = None
    notes: str | None = None
    committed: bool | None = None


class Event(EventBase):
    id: str
    version: int = 1
    deleted: bool = False
    modifiedByUserId: str | None = None
    modifiedAt: str | None = None
    backgroundColor: str | None = None
    borderColor: str | None = None
