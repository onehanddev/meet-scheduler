import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meet_scheduler.meeting_types.models import MeetingType

RESERVED_SLUGS = {
    "admin",
    "api",
    "auth",
    "docs",
    "health",
    "healthz",
    "login",
    "logout",
    "me",
    "openapi",
    "redoc",
    "refresh",
    "register",
    "static",
}

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


def normalize_slug(value: str) -> str:
    return value.strip().lower()


def validate_slug(value: str) -> str:
    normalized = normalize_slug(value)
    if len(normalized) < 1 or len(normalized) > 30:
        raise ValueError("event_slug must be between 1 and 30 characters")
    if normalized in RESERVED_SLUGS:
        raise ValueError(f"event_slug '{normalized}' is reserved")
    if not SLUG_RE.match(normalized):
        raise ValueError(
            "event_slug must be URL-safe: lowercase alphanumeric, hyphen, underscore, "
            "must start and end with alphanumeric"
        )
    return normalized


def validate_title(value: str) -> str:
    stripped = value.strip()
    if len(stripped) == 0:
        raise ValueError("title cannot be empty")
    if len(stripped) > 200:
        raise ValueError("title must be at most 200 characters")
    return stripped


def resolve_notice(data: dict) -> int | None:
    if data.get("minimum_notice") is not None:
        return data["minimum_notice"]
    if data.get("minimum_notice_minutes") is not None:
        return data["minimum_notice_minutes"]
    return None


def resolve_horizon(data: dict) -> int | None:
    if data.get("horizon_days") is not None:
        return data["horizon_days"]
    if data.get("horizon") is not None:
        return data["horizon"]
    return None


def get_by_host(session: Session, host_id: UUID) -> MeetingType | None:
    return session.scalar(select(MeetingType).where(MeetingType.host_id == host_id))


def apply_update(mt: MeetingType, payload: dict, session: Session) -> MeetingType:
    if payload.get("title") is not None:
        mt.title = payload["title"].strip()
    if payload.get("event_slug") is not None:
        new_slug = payload["event_slug"]
        existing = session.scalar(
            select(MeetingType).where(
                MeetingType.host_id == mt.host_id,
                func.lower(MeetingType.event_slug) == new_slug.lower(),
                MeetingType.id != mt.id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="event_slug already taken",
            )
        mt.event_slug = new_slug
    if payload.get("duration") is not None:
        mt.duration = payload["duration"]
    if payload.get("active") is not None:
        mt.active = payload["active"]
    notice = resolve_notice(payload)
    if notice is not None:
        mt.minimum_notice = notice
    horizon = resolve_horizon(payload)
    if horizon is not None:
        mt.horizon_days = horizon
    return mt
