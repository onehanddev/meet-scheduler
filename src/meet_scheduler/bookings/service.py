from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select as sa_select
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


def _hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _verify_token(booking: Booking, token: str) -> bool:
    if booking.management_token_hash is None:
        return False
    return booking.management_token_hash == _hash_token(token)


def _lock_booking_for_update(session: Session, booking_id: UUID) -> Booking | None:
    return session.scalars(
        sa_select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


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
    locked_mt = session.scalars(
        sa_select(MeetingType)
        .where(MeetingType.id == meeting_type.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if locked_mt is None:
        raise BookingError("public_resource_not_found", "Not found.", 404)
    meeting_type = locked_mt
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
        management_token_hash=_hash_token(raw_token),
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


def cancel_booking(
    session: Session, booking_id: UUID, token: str
) -> Booking:
    booking = _lock_booking_for_update(session, booking_id)
    if booking is None:
        raise BookingError("booking_not_found", "Booking not found.", 404)
    if not _verify_token(booking, token):
        raise BookingError(
            "invalid_management_token", "Invalid management token.", 401
        )
    if booking.status == "cancelled":
        session.commit()
        return booking
    now = slots_service.get_now()
    booking.status = "cancelled"
    booking.updated_at = now
    session.add(booking)
    session.commit()
    session.refresh(booking)
    return booking


def reschedule_booking(
    session: Session, booking_id: UUID, token: str, new_slot_start: datetime
) -> Booking:
    booking = _lock_booking_for_update(session, booking_id)
    if booking is None:
        raise BookingError("booking_not_found", "Booking not found.", 404)
    if not _verify_token(booking, token):
        raise BookingError(
            "invalid_management_token", "Invalid management token.", 401
        )
    if booking.status != "confirmed":
        raise BookingError(
            "booking_not_confirmed",
            "Only confirmed bookings can be rescheduled.",
            409,
        )
    new_slot_start = new_slot_start.astimezone(UTC)
    if new_slot_start == booking.start_time:
        raise BookingError(
            "reschedule_same_interval",
            "New slot must differ from current booking.",
            409,
        )
    # Lock host and meeting_type for transactional revalidation
    host = lock_host(session, booking.host_id, read_only=True)
    locked_mt = session.scalars(
        sa_select(MeetingType)
        .where(MeetingType.id == booking.meeting_type_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if locked_mt is None:
        raise BookingError("public_resource_not_found", "Not found.", 404)
    meeting_type = locked_mt
    if not meeting_type.active:
        raise BookingError(
            "meeting_type_inactive",
            "This meeting type is deactivated. Host must reactivate it.",
            404,
        )
    if host.timezone is None:
        raise BookingError(
            "host_timezone_not_set",
            "Host has not set timezone — bookings disabled.",
            422,
        )
    now = slots_service.get_now()
    host_date = new_slot_start.astimezone(ZoneInfo(host.timezone)).date()
    # Fetch confirmed bookings excluding current booking so its own old slot
    # does not appear as overlap for validation
    all_confirmed = slots_service.fetch_confirmed_bookings(session, host.id)
    # Filter out current booking's interval
    filtered_confirmed = [
        (s, e)
        for s, e in all_confirmed
        if not (s == booking.start_time and e == booking.end_time)
    ]
    # Generate slots using provider windows directly with filtered bookings
    from meet_scheduler.availability.provider import WeeklyAvailabilityProvider

    windows = WeeklyAvailabilityProvider(session).get_windows(host.id)
    slots = slots_service.generate_slots(
        windows=windows,
        host_timezone=host.timezone,
        duration=meeting_type.duration,
        from_date=host_date,
        to_date=host_date,
        invitee_timezone="UTC",
        now=now,
        minimum_notice=meeting_type.minimum_notice,
        horizon_days=meeting_type.horizon_days,
        confirmed_bookings=filtered_confirmed,
    )
    valid_starts = {datetime.fromisoformat(slot["start_utc"]) for slot in slots}
    if new_slot_start not in valid_starts:
        raise BookingError(
            "slot_no_longer_available",
            "The selected slot is no longer available.",
        )

    new_end = new_slot_start + timedelta(minutes=meeting_type.duration)
    # Atomically: create new booking row, cancel old.
    # Preserve management token by copying hash; keep trace via predecessor_id
    new_booking = Booking(
        host_id=booking.host_id,
        meeting_type_id=booking.meeting_type_id,
        invitee_name=booking.invitee_name,
        invitee_email=booking.invitee_email,
        notes=booking.notes,
        start_time=new_slot_start,
        end_time=new_end,
        status="confirmed",
        management_token_hash=booking.management_token_hash,
        predecessor_id=booking.id,
        created_at=now,
        updated_at=now,
    )
    session.add(new_booking)
    # Cancel old booking so its interval freed for exclude constraint
    booking.status = "cancelled"
    booking.updated_at = now
    session.add(booking)
    # We need to flush to catch exclude violation early; but commit atomically
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
    session.refresh(new_booking)
    return new_booking
