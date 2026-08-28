"""Deep module: Weekly availability atomic replace."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from meet_scheduler.availability.models import AvailabilityWindow
from meet_scheduler.availability.schemas import (
    AvailabilityReplaceRequest,
    AvailabilityResponse,
    AvailabilityWindowOut,
)
from meet_scheduler.availability.service import parse_time, validate_windows_no_overlap
from meet_scheduler.config import Settings
from meet_scheduler.dependencies import create_current_host_dependency
from meet_scheduler.hosts.models import Host
from meet_scheduler.hosts.service import lock_host


def create_availability_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(tags=["availability"])
    get_current_host = create_current_host_dependency(get_session, get_settings)

    @router.get("/availability", response_model=AvailabilityResponse)
    def get_availability(
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> AvailabilityResponse:
        rows = session.scalars(
            select(AvailabilityWindow).where(
                AvailabilityWindow.host_id == current_host.id
            )
        ).all()
        windows = [
            AvailabilityWindowOut(
                weekday=r.weekday,
                start=r.start_time.strftime("%H:%M"),
                end=r.end_time.strftime("%H:%M"),
            )
            for r in sorted(rows, key=lambda x: (x.weekday, x.start_time))
        ]
        return AvailabilityResponse(windows=windows)

    @router.put("/availability", response_model=AvailabilityResponse)
    def put_availability(
        request: AvailabilityReplaceRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> AvailabilityResponse:
        # Build normalized windows with parsed times
        normalized: list[dict] = []
        for w in request.windows:
            try:
                start_t = parse_time(w.start)
                end_t = parse_time(w.end)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc
            if start_t >= end_t:
                msg = (
                    f"start {w.start} must be before end {w.end}; "
                    "overnight windows not supported"
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=msg,
                )
            normalized.append(
                {"weekday": w.weekday, "start_time": start_t, "end_time": end_t}
            )

        # Validate overlap
        try:
            validate_windows_no_overlap(normalized)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        # Atomic replace in one transaction
        try:
            lock_host(session, current_host.id)
            session.execute(
                delete(AvailabilityWindow).where(
                    AvailabilityWindow.host_id == current_host.id
                )
            )
            for w in normalized:
                session.add(
                    AvailabilityWindow(
                        host_id=current_host.id,
                        weekday=w["weekday"],
                        start_time=w["start_time"],
                        end_time=w["end_time"],
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise

        # Return persisted state sorted
        rows = session.scalars(
            select(AvailabilityWindow).where(
                AvailabilityWindow.host_id == current_host.id
            )
        ).all()
        windows = [
            AvailabilityWindowOut(
                weekday=r.weekday,
                start=r.start_time.strftime("%H:%M"),
                end=r.end_time.strftime("%H:%M"),
            )
            for r in sorted(rows, key=lambda x: (x.weekday, x.start_time))
        ]
        return AvailabilityResponse(windows=windows)

    return router
