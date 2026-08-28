from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.config import Settings
from meet_scheduler.dependencies import create_current_host_dependency
from meet_scheduler.hosts.models import Host
from meet_scheduler.hosts.schemas import HostProfileResponse
from meet_scheduler.hosts.service import validate_timezone, validate_username


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
        return validate_username(v)

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
        return validate_timezone(v)


def create_profile_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(tags=["profile"])
    get_current_host = create_current_host_dependency(get_session, get_settings)

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
