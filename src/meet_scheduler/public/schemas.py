from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class PublicMeetingResponse(BaseModel):
    username: str
    display_name: str | None
    timezone: str | None
    title: str
    duration: int
    event_slug: str | None = None


class SlotOut(BaseModel):
    start: str
    end: str
    start_utc: str | None = None
    end_utc: str | None = None


class SlotsResponse(BaseModel):
    slots: list[SlotOut]
    timezone: str | None = None


class BookingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitee_name: str = Field(min_length=1, max_length=200)
    invitee_email: EmailStr
    slot_start: datetime
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("invitee_name")
    @classmethod
    def validate_invitee_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("invitee_name cannot be blank")
        return stripped

    @field_validator("slot_start")
    @classmethod
    def validate_slot_start(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("slot_start must include a timezone")
        return value


class BookingCreateResponse(BaseModel):
    id: UUID
    status: str
    invitee_name: str
    invitee_email: EmailStr
    notes: str | None
    slot_start: datetime
    slot_end: datetime
    management_token: str
