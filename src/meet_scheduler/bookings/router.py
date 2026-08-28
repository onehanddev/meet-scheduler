"""Deep module: Booking lifecycle host + invitee APIs."""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from meet_scheduler.bookings.models import Booking
from meet_scheduler.bookings.schemas import (
    BookingOut,
    CancelRequest,
    RescheduleRequest,
)
from meet_scheduler.bookings.service import cancel_booking, reschedule_booking
from meet_scheduler.config import Settings
from meet_scheduler.dependencies import create_current_host_dependency
from meet_scheduler.hosts.models import Host


def _to_out(booking: Booking) -> BookingOut:
    data = BookingOut.model_validate(booking)
    data.slot_start = booking.start_time
    data.slot_end = booking.end_time
    return data


def create_bookings_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(tags=["bookings"])
    get_current_host = create_current_host_dependency(get_session, get_settings)

    @router.get("/bookings", response_model=list[BookingOut])
    def list_bookings(
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        from_param: Annotated[str | None, Query(alias="from")] = None,
        to_param: Annotated[str | None, Query(alias="to")] = None,
    ) -> list[BookingOut]:
        query = select(Booking).where(Booking.host_id == current_host.id)
        if status_filter is not None:
            if status_filter not in {"confirmed", "cancelled"}:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "validation_error",
                        "message": "status must be confirmed or cancelled",
                    },
                )
            query = query.where(Booking.status == status_filter)
        if from_param is not None:
            try:
                from_dt = datetime.fromisoformat(from_param.replace("Z", "+00:00"))
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid from: {from_param}",
                ) from exc
            query = query.where(Booking.start_time >= from_dt)
        if to_param is not None:
            try:
                to_dt = datetime.fromisoformat(to_param.replace("Z", "+00:00"))
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid to: {to_param}",
                ) from exc
            query = query.where(Booking.start_time <= to_dt)
        query = query.order_by(Booking.start_time.asc())
        bookings = session.scalars(query).all()
        return [_to_out(b) for b in bookings]

    @router.get("/bookings/{booking_id}", response_model=BookingOut)
    def get_booking(
        booking_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> BookingOut:
        booking = session.get(Booking, booking_id)
        if booking is None or booking.host_id != current_host.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Booking not found."},
            )
        return _to_out(booking)

    @router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
    def cancel_booking_endpoint(
        booking_id: UUID,
        request: CancelRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> BookingOut:
        booking = cancel_booking(session, booking_id, request.management_token)
        return _to_out(booking)

    @router.post("/bookings/{booking_id}/reschedule", response_model=BookingOut)
    def reschedule_booking_endpoint(
        booking_id: UUID,
        request: RescheduleRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> BookingOut:
        new_booking = reschedule_booking(
            session, booking_id, request.management_token, request.new_slot_start
        )
        return _to_out(new_booking)

    return router
