from pydantic import BaseModel


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
    invitee_name: str
    invitee_email: str
    slot_start: str
    notes: str | None = None
