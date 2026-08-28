"""Deep module: Public booking surface.

Interface (external seam): 3 entry points
  GET  /{username}/{event_slug}
  GET  /{username}/{event_slug}/slots?from=&to=&timezone=
  POST /{username}/{event_slug}/bookings
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from meet_scheduler.bookings.service import create_booking
from meet_scheduler.config import Settings
from meet_scheduler.public.schemas import (
    BookingCreateRequest,
    BookingCreateResponse,
    PublicMeetingResponse,
    SlotsResponse,
)
from meet_scheduler.public.service import resolve_host_and_meeting
from meet_scheduler.slots import service as slots_service


def _parse_date_param(value: str, field: str) -> date:
    raw = value.strip()
    # Accept YYYY-MM-DD or full ISO datetime; extract date part
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.date()
        return date.fromisoformat(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field}: must be YYYY-MM-DD or ISO datetime",
        ) from exc


def create_public_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],  # noqa: ARG001 — seam uniformity
) -> APIRouter:
    router = APIRouter(tags=["public"])

    @router.get("/{username}/{event_slug}/slots", response_model=SlotsResponse)
    def get_public_slots(
        username: str,
        event_slug: str,
        session: Annotated[Session, Depends(get_session)],
        from_param: Annotated[str, Query(alias="from")],
        to_param: Annotated[str, Query(alias="to")],
        timezone: str = Query(..., description="Invitee IANA timezone"),
    ) -> SlotsResponse:
        # Validate invitee timezone
        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid timezone: {timezone}",
            ) from exc

        from_date = _parse_date_param(from_param, "from")
        to_date = _parse_date_param(to_param, "to")
        if from_date > to_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'from' must be <= 'to'",
            )

        host, mt = resolve_host_and_meeting(session, username, event_slug)

        # Host must have timezone; if missing, no slots
        if not host.timezone:
            return SlotsResponse(slots=[], timezone=timezone)
        try:
            ZoneInfo(host.timezone)
        except Exception:
            return SlotsResponse(slots=[], timezone=timezone)

        now = slots_service.get_now()
        slots = slots_service.generate_host_slots(
            session=session,
            host=host,
            meeting_type=mt,
            from_date=from_date,
            to_date=to_date,
            invitee_timezone=timezone,
            now=now,
        )
        return SlotsResponse(slots=slots, timezone=timezone)

    @router.get("/{username}/{event_slug}", response_model=PublicMeetingResponse)
    def get_public_meeting(
        username: str,
        event_slug: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> PublicMeetingResponse:
        host, mt = resolve_host_and_meeting(session, username, event_slug)
        return PublicMeetingResponse(
            username=host.username or username,
            display_name=host.display_name,
            timezone=host.timezone,
            title=mt.title,
            duration=mt.duration,
            event_slug=mt.event_slug,
        )

    @router.post(
        "/{username}/{event_slug}/bookings",
        response_model=BookingCreateResponse,
        status_code=201,
    )
    def create_booking_public(
        username: str,
        event_slug: str,
        request: BookingCreateRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> BookingCreateResponse:
        host, meeting_type = resolve_host_and_meeting(session, username, event_slug)
        booking, management_token = create_booking(
            session,
            host,
            meeting_type,
            username=username,
            event_slug=event_slug,
            invitee_name=request.invitee_name,
            invitee_email=str(request.invitee_email),
            slot_start=request.slot_start,
            notes=request.notes,
        )
        return BookingCreateResponse(
            id=booking.id,
            status=booking.status,
            invitee_name=booking.invitee_name,
            invitee_email=booking.invitee_email,
            notes=booking.notes,
            slot_start=booking.start_time.astimezone(UTC),
            slot_end=booking.end_time.astimezone(UTC),
            management_token=management_token,
        )

    return router
