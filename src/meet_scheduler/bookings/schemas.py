from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BookingOut(BaseModel):
    id: UUID
    host_id: UUID
    meeting_type_id: UUID
    invitee_name: str
    invitee_email: str
    notes: str | None = None
    start_time: datetime
    end_time: datetime
    slot_start: datetime | None = None
    slot_end: datetime | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    predecessor_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("slot_start", mode="before")
    @classmethod
    def _set_slot_start(cls, value, info):  # noqa: ARG001
        return value

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        # Expose start_time also as slot_start/slot_end for consistency
        if self.slot_start is None:
            object.__setattr__(self, "slot_start", self.start_time)
        if self.slot_end is None:
            object.__setattr__(self, "slot_end", self.end_time)


class CancelRequest(BaseModel):
    management_token: str = Field(min_length=1)


class RescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    management_token: str = Field(min_length=1)
    new_slot_start: datetime

    @field_validator("new_slot_start")
    @classmethod
    def validate_slot_start(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("new_slot_start must include a timezone")
        return value


class RescheduleResponse(BookingOut):
    pass
