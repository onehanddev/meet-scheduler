from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.bookings.models import Booking
from meet_scheduler.hosts.models import Host
from meet_scheduler.hosts.service import lock_host
from meet_scheduler.meeting_types.models import MeetingType
from meet_scheduler.slots import service as slots_service


class BookingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def create_booking(
    session: Session,
    host: Host,
    meeting_type: MeetingType,
    *,
    invitee_name: str,
    invitee_email: str,
    slot_start: datetime,
    notes: str | None,
) -> tuple[Booking, str]:
    host = lock_host(session, host.id, read_only=True)
    session.refresh(meeting_type)
    slot_start = slot_start.astimezone(UTC)
    now = slots_service.get_now()
    if host.timezone is None:
        raise BookingError("public_resource_not_found", "Not found.", 404)
    host_date = slot_start.astimezone(ZoneInfo(host.timezone)).date()
    slots = slots_service.generate_host_slots(
        session=session,
        host=host,
        meeting_type=meeting_type,
        from_date=host_date,
        to_date=host_date,
        invitee_timezone="UTC",
        now=now,
    )
    valid_starts = {datetime.fromisoformat(slot["start_utc"]) for slot in slots}
    if slot_start not in valid_starts:
        raise BookingError(
            "slot_no_longer_available",
            "The selected slot is no longer available.",
        )

    raw_token = token_urlsafe(32)
    booking = Booking(
        host_id=host.id,
        meeting_type_id=meeting_type.id,
        invitee_name=invitee_name,
        invitee_email=invitee_email,
        notes=notes,
        start_time=slot_start,
        end_time=slot_start + timedelta(minutes=meeting_type.duration),
        status="confirmed",
        management_token_hash=sha256(raw_token.encode()).hexdigest(),
        created_at=now,
        updated_at=now,
    )
    session.add(booking)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        constraint_name = getattr(
            getattr(exc.orig, "diag", None), "constraint_name", None
        )
        if constraint_name == "ex_bookings_host_confirmed_overlap":
            raise BookingError(
                "booking_conflict",
                "The selected slot is no longer available.",
            ) from exc
        raise
    session.refresh(booking)
    return booking, raw_token
