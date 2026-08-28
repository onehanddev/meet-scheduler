"""Deep module: Public booking surface.

Interface (external seam): 3 entry points
  GET  /{username}/{event_slug}
  GET  /{username}/{event_slug}/slots?from=&to=&timezone=
  POST /{username}/{event_slug}/bookings
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from meet_scheduler.availability.provider import WeeklyAvailabilityProvider
from meet_scheduler.config import Settings
from meet_scheduler.public.schemas import PublicMeetingResponse, SlotsResponse
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

        # Provider boundary — not direct DB query throughout slot code
        provider = WeeklyAvailabilityProvider(session)
        windows = provider.get_windows(host.id)

        if not windows:
            return SlotsResponse(slots=[], timezone=timezone)

        now = slots_service.get_now()
        bookings = slots_service.fetch_confirmed_bookings(session, host.id)

        slots = slots_service.generate_slots(
            windows=windows,
            host_timezone=host.timezone,
            duration=mt.duration,
            from_date=from_date,
            to_date=to_date,
            invitee_timezone=timezone,
            now=now,
            minimum_notice=mt.minimum_notice,
            horizon_days=mt.horizon_days,
            confirmed_bookings=bookings,
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

    @router.post("/{username}/{event_slug}/bookings", status_code=201)
    def create_booking_public(
        username: str,
        event_slug: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict:
        resolve_host_and_meeting(session, username, event_slug)
        return {
            "detail": "booking not yet implemented",
            "management_token": "placeholder",
        }

    return router
