import re
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from meet_scheduler.hosts.models import Host

RESERVED_USERNAMES = {
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

USERNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


def normalize_username(value: str) -> str:
    return value.strip().lower()


def validate_username(value: str) -> str:
    normalized = normalize_username(value)
    if len(normalized) < 3 or len(normalized) > 30:
        raise ValueError("Username must be between 3 and 30 characters")
    if normalized in RESERVED_USERNAMES:
        raise ValueError(f"Username '{normalized}' is reserved")
    if not USERNAME_RE.match(normalized):
        raise ValueError(
            "Username must be URL-safe: lowercase alphanumeric, hyphen, underscore, "
            "must start and end with alphanumeric"
        )
    return normalized


def validate_timezone(value: str) -> str:
    stripped = value.strip()
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError(f"Invalid IANA timezone: {stripped}") from exc
    return stripped


def lock_host(session: Session, host_id: UUID, *, read_only: bool = False) -> Host:
    lock_options = {"read": True, "key_share": True} if read_only else {}
    return session.scalars(
        select(Host)
        .where(Host.id == host_id)
        .with_for_update(**lock_options)
        .execution_options(populate_existing=True)
    ).one()
