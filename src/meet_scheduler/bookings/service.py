from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.availability.provider import WeeklyAvailabilityProvider
from meet_scheduler.bookings.models import Booking
from meet_scheduler.hosts.models import Host
from meet_scheduler.meeting_types.models import MeetingType
from meet_scheduler.public.schemas import BookingCreateRequest
from meet_scheduler.slots import service as slots_service


def create_booking(
    session: Session,
    host: Host,
    meeting_type: MeetingType,
    request: BookingCreateRequest,
) -> tuple[Booking, str]:
    slot_start = request.slot_start
    if slot_start.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="slot_start must include a timezone",
        )
    slot_start = slot_start.astimezone(UTC)
    now = slots_service.get_now()
    if host.timezone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    host_date = slot_start.astimezone(ZoneInfo(host.timezone)).date()
    slots = slots_service.generate_slots(
        windows=WeeklyAvailabilityProvider(session).get_windows(host.id),
        host_timezone=host.timezone,
        duration=meeting_type.duration,
        from_date=host_date,
        to_date=host_date,
        invitee_timezone="UTC",
        now=now,
        minimum_notice=meeting_type.minimum_notice,
        horizon_days=meeting_type.horizon_days,
        confirmed_bookings=slots_service.fetch_confirmed_bookings(session, host.id),
    )
    valid_starts = {datetime.fromisoformat(slot["start_utc"]) for slot in slots}
    if slot_start not in valid_starts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "slot_no_longer_available",
                "message": "The selected slot is no longer available.",
            },
        )

    raw_token = token_urlsafe(32)
    booking = Booking(
        host_id=host.id,
        meeting_type_id=meeting_type.id,
        invitee_name=request.invitee_name,
        invitee_email=str(request.invitee_email),
        notes=request.notes,
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "booking_conflict",
                    "message": "The selected slot is no longer available.",
                },
            ) from exc
        raise
    session.refresh(booking)
    return booking, raw_token
