import re
from collections.abc import Callable, Iterator
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.config import Settings
from meet_scheduler.models import Host
from meet_scheduler.schemas import HostProfileResponse
from meet_scheduler.security import get_host_id_from_access_token

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


def _normalize_username(value: str) -> str:
    return value.strip().lower()


def _validate_username(value: str) -> str:
    normalized = _normalize_username(value)
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


def _validate_timezone(value: str) -> str:
    stripped = value.strip()
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError(f"Invalid IANA timezone: {stripped}") from exc
    return stripped


class ProfileResponse(HostProfileResponse):
    pass


class ProfileUpdateRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    timezone: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_username(v)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if len(stripped) == 0:
            raise ValueError("display_name cannot be empty or whitespace only")
        if len(stripped) > 100:
            raise ValueError("display_name must be at most 100 characters")
        return stripped

    @field_validator("timezone")
    @classmethod
    def validate_timezone_field(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_timezone(v)


def create_profile_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(tags=["profile"])

    def get_current_host(
        session: Annotated[Session, Depends(get_session)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Host:
        host_id = get_host_id_from_access_token(authorization, get_settings())
        host = session.get(Host, host_id)
        if host is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return host

    @router.get("/me", response_model=ProfileResponse)
    def get_me(current_host: Annotated[Host, Depends(get_current_host)]) -> Host:
        return current_host

    @router.put("/me", response_model=ProfileResponse)
    def put_me(
        request: ProfileUpdateRequest,
        session: Annotated[Session, Depends(get_session)],
        current_host: Annotated[Host, Depends(get_current_host)],
    ) -> Host:
        # No fields provided? Allow no-op but return current
        if request.username is not None:
            normalized = request.username  # already validated and lowercased
            # Check case-insensitive uniqueness: if owned by self, allow same
            if (
                current_host.username is not None
                and current_host.username.lower() == normalized.lower()
            ):
                # same as current, no conflict check needed
                pass
            else:
                existing = session.scalar(
                    select(Host).where(func.lower(Host.username) == normalized.lower())
                )
                if existing is not None and existing.id != current_host.id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Username already taken",
                    )
            current_host.username = normalized

        if request.display_name is not None:
            current_host.display_name = request.display_name

        if request.timezone is not None:
            current_host.timezone = request.timezone

        session.add(current_host)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            # Likely unique violation on username
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            ) from exc
        session.refresh(current_host)
        return current_host

    return router
