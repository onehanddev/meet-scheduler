"""Deep module: MeetingType lifecycle.

Interface (external seam): 5 entry points behind one router factory.
"""

from collections.abc import Callable, Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.config import Settings
from meet_scheduler.dependencies import create_current_host_dependency
from meet_scheduler.hosts.models import Host
from meet_scheduler.meeting_types.models import MeetingType
from meet_scheduler.meeting_types.schemas import (
    MeetingTypeCreateRequest,
    MeetingTypeResponse,
    MeetingTypeUpdateRequest,
)
from meet_scheduler.meeting_types.service import (
    apply_update,
    get_by_host,
    resolve_horizon,
    resolve_notice,
)


def _to_response(mt: MeetingType) -> MeetingTypeResponse:
    resp = MeetingTypeResponse.model_validate(mt)
    resp.horizon = mt.horizon_days
    resp.minimum_notice_minutes = mt.minimum_notice
    return resp


def create_meeting_type_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(tags=["meeting-types"])
    get_current_host = create_current_host_dependency(get_session, get_settings)

    @router.post(
        "/meeting-types",
        response_model=MeetingTypeResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_meeting_type(
        request: MeetingTypeCreateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        if get_by_host(session, current_host.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting type already exists",
            )
        notice = resolve_notice(request.model_dump())
        horizon = resolve_horizon(request.model_dump())
        mt = MeetingType(
            host_id=current_host.id,
            title=request.title.strip(),
            event_slug=request.event_slug,
            duration=request.duration,
            active=request.active if request.active is not None else True,
            minimum_notice=notice if notice is not None else 60,
            horizon_days=horizon if horizon is not None else 60,
        )
        session.add(mt)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting type already exists",
            ) from exc
        session.refresh(mt)
        return _to_response(mt)

    @router.get("/meeting-types", response_model=list[MeetingTypeResponse])
    def list_meeting_types(
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> list[MeetingTypeResponse]:
        mt = get_by_host(session, current_host.id)
        return [_to_response(mt)] if mt is not None else []

    @router.get("/meeting-types/{meeting_type_id}", response_model=MeetingTypeResponse)
    def get_meeting_type_by_id(
        meeting_type_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        mt = session.get(MeetingType, meeting_type_id)
        if mt is None or mt.host_id != current_host.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting type not found"
            )
        return _to_response(mt)

    @router.put("/meeting-types/{meeting_type_id}", response_model=MeetingTypeResponse)
    def update_meeting_type_by_id(
        meeting_type_id: UUID,
        request: MeetingTypeUpdateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        mt = session.get(MeetingType, meeting_type_id)
        if mt is None or mt.host_id != current_host.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting type not found"
            )
        mt = apply_update(mt, request.model_dump(), session)
        session.add(mt)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Conflict"
            ) from exc
        session.refresh(mt)
        return _to_response(mt)

    @router.patch(
        "/meeting-types/{meeting_type_id}", response_model=MeetingTypeResponse
    )
    def patch_meeting_type_by_id(
        meeting_type_id: UUID,
        request: MeetingTypeUpdateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        return update_meeting_type_by_id(
            meeting_type_id, request, session, current_host
        )

    # Singleton update without id — deep: host identity implies resource
    @router.put("/meeting-types", response_model=MeetingTypeResponse)
    def update_meeting_type(
        request: MeetingTypeUpdateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        mt = get_by_host(session, current_host.id)
        if mt is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting type not found"
            )
        mt = apply_update(mt, request.model_dump(), session)
        session.add(mt)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Conflict"
            ) from exc
        session.refresh(mt)
        return _to_response(mt)

    @router.patch("/meeting-types", response_model=MeetingTypeResponse)
    def patch_meeting_type(
        request: MeetingTypeUpdateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> MeetingTypeResponse:
        return update_meeting_type(request, session, current_host)

    return router
