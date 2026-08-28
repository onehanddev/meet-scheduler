from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meet_scheduler.hosts.models import Host
from meet_scheduler.meeting_types.models import MeetingType


def resolve_host_and_meeting(
    session: Session, username: str, event_slug: str
) -> tuple[Host, MeetingType]:
    host = session.scalar(
        select(Host).where(func.lower(Host.username) == username.lower())
    )
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "public_resource_not_found", "message": "Not found."},
        )
    mt = session.scalar(
        select(MeetingType).where(
            MeetingType.host_id == host.id,
            func.lower(MeetingType.event_slug) == event_slug.lower(),
        )
    )
    if mt is None or not mt.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "public_resource_not_found", "message": "Not found."},
        )
    return host, mt
