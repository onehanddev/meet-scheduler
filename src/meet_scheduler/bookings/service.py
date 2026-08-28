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
    username: str,
    event_slug: str,
    invitee_name: str,
    invitee_email: str,
    slot_start: datetime,
    notes: str | None,
) -> tuple[Booking, str]:
    host = lock_host(session, host.id, read_only=True)
    # Lock meeting_type row with FOR SHARE so concurrent bookings can share
    # the lock but a concurrent DELETE/deactivate (which takes FOR UPDATE
    # via host lock + mt update) will block. Also handles deleted row.
    from sqlalchemy import select as sa_select

    locked_mt = session.scalars(
        sa_select(MeetingType)
        .where(MeetingType.id == meeting_type.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if locked_mt is None:
        raise BookingError("public_resource_not_found", "Not found.", 404)
    meeting_type = locked_mt
    # Distinct errors so invitee/host can tell *why* it 404s — not just "Not found."
    if host.username is None or host.username.casefold() != username.casefold():
        raise BookingError(
            "host_not_found", f"Host '{username}' not found.", 404
        )
    if meeting_type.event_slug.casefold() != event_slug.casefold():
        raise BookingError(
            "meeting_type_not_found",
            f"Meeting type '{event_slug}' not found for host '{username}'.",
            404,
        )
    if not meeting_type.active:
        raise BookingError(
            "meeting_type_inactive",
            "This meeting type is deactivated. Host must reactivate it.",
            404,
        )
    slot_start = slot_start.astimezone(UTC)
    now = slots_service.get_now()
    if host.timezone is None:
        raise BookingError(
            "host_timezone_not_set",
            "Host has not set timezone — bookings disabled until "
            "host sets timezone via PUT /me {\"timezone\": \"Asia/Kolkata\"}.",
            422,
        )
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
