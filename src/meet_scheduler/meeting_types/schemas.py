from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from meet_scheduler.meeting_types.service import validate_slug, validate_title


class MeetingTypeResponse(BaseModel):
    id: UUID
    host_id: UUID
    title: str
    event_slug: str
    duration: int
    active: bool
    minimum_notice: int
    horizon_days: int
    # Compat aliases echoed for existing clients/tests — not required
    horizon: int | None = None
    minimum_notice_minutes: int | None = None

    model_config = {"from_attributes": True}

    def model_post_init(self, __context: object) -> None:
        if self.horizon is None:
            object.__setattr__(self, "horizon", self.horizon_days)
        if self.minimum_notice_minutes is None:
            object.__setattr__(self, "minimum_notice_minutes", self.minimum_notice)


class MeetingTypeCreateRequest(BaseModel):
    title: str
    event_slug: str
    duration: Literal[15, 30, 45, 60]
    active: bool | None = None
    minimum_notice: int | None = Field(default=None, ge=0, le=10080)
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    # Internal compat aliases — accepted but canonical wins
    horizon: int | None = Field(default=None, ge=1, le=365)
    minimum_notice_minutes: int | None = Field(default=None, ge=0, le=10080)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return validate_title(v)

    @field_validator("event_slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        return validate_slug(v)


class MeetingTypeUpdateRequest(BaseModel):
    title: str | None = None
    event_slug: str | None = None
    duration: Literal[15, 30, 45, 60] | None = None
    active: bool | None = None
    minimum_notice: int | None = Field(default=None, ge=0, le=10080)
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    horizon: int | None = Field(default=None, ge=1, le=365)
    minimum_notice_minutes: int | None = Field(default=None, ge=0, le=10080)

    @field_validator("title")
    @classmethod
    def validate_title_opt(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_title(v)

    @field_validator("event_slug")
    @classmethod
    def validate_slug_opt(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_slug(v)
