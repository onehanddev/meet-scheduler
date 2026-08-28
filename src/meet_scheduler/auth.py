from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meet_scheduler.config import Settings
from meet_scheduler.models import Host, RefreshToken

password_hasher = PasswordHasher()
ACCESS_TOKEN_EXPIRES_IN_SECONDS = 15 * 60
REFRESH_TOKEN_EXPIRES_IN_SECONDS = 30 * 24 * 60 * 60


class RegistrationRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class HostResponse(BaseModel):
    id: UUID
    email: str


class CredentialsResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRES_IN_SECONDS


class RefreshRequest(BaseModel):
    refresh_token: str


def create_token(
    *,
    host_id: UUID,
    token_type: str,
    expires_in: int,
    settings: Settings,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(host_id),
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "jti": str(uuid4()),
        },
        settings.token_secret,
        algorithm="HS256",
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def _decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.token_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc


def _persist_refresh_token(
    *, refresh_token: str, settings: Settings, session: Session
) -> None:
    payload = jwt.decode(
        refresh_token,
        settings.token_secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    jti = payload.get("jti")
    sub = payload.get("sub")
    exp = payload.get("exp")
    if jti is None or sub is None or exp is None:
        return
    expires_at = datetime.fromtimestamp(exp, tz=UTC)
    created_at = datetime.now(UTC)
    session.add(
        RefreshToken(
            jti=UUID(jti),
            host_id=UUID(sub),
            revoked=False,
            expires_at=expires_at,
            created_at=created_at,
        )
    )


def create_auth_router(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["authentication"])

    def get_current_host(
        session: Annotated[Session, Depends(get_session)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Host:
        token = _extract_bearer_token(authorization)
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        payload = _decode_token(token, get_settings())
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        host_id = payload.get("sub")
        if host_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        host = session.get(Host, UUID(host_id))
        if host is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return host

    @router.post(
        "/register",
        response_model=HostResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def register(
        request: RegistrationRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> Host:
        host = Host(
            email=request.email.strip().lower(),
            password_hash=password_hasher.hash(request.password),
        )
        session.add(host)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            ) from None
        session.refresh(host)
        return host

    @router.post("/login", response_model=CredentialsResponse)
    def login(
        request: LoginRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> CredentialsResponse:
        host = session.scalar(
            select(Host).where(Host.email == request.email.strip().lower())
        )
        if host is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        try:
            password_hasher.verify(host.password_hash, request.password)
        except VerifyMismatchError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            ) from None

        settings = get_settings()
        access_token = create_token(
            host_id=host.id,
            token_type="access",
            expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
            settings=settings,
        )
        refresh_token = create_token(
            host_id=host.id,
            token_type="refresh",
            expires_in=REFRESH_TOKEN_EXPIRES_IN_SECONDS,
            settings=settings,
        )
        _persist_refresh_token(
            refresh_token=refresh_token, settings=settings, session=session
        )
        session.commit()
        return CredentialsResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    @router.get("/me", response_model=HostResponse)
    def me(current_host: Annotated[Host, Depends(get_current_host)]) -> Host:
        return current_host

    @router.post("/refresh", response_model=CredentialsResponse)
    def refresh(
        request: RefreshRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> CredentialsResponse:
        settings = get_settings()
        payload = _decode_token(request.refresh_token, settings)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        jti = payload.get("jti")
        sub = payload.get("sub")
        if jti is None or sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        token_record = session.get(RefreshToken, UUID(jti))
        if token_record is None or token_record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        if str(token_record.host_id) != sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        host = session.get(Host, token_record.host_id)
        if host is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        token_record.revoked = True
        session.add(token_record)

        new_access_token = create_token(
            host_id=host.id,
            token_type="access",
            expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
            settings=settings,
        )
        new_refresh_token = create_token(
            host_id=host.id,
            token_type="refresh",
            expires_in=REFRESH_TOKEN_EXPIRES_IN_SECONDS,
            settings=settings,
        )
        _persist_refresh_token(
            refresh_token=new_refresh_token, settings=settings, session=session
        )
        session.commit()
        return CredentialsResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
        )

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        request: RefreshRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        settings = get_settings()
        payload = _decode_token(request.refresh_token, settings)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        jti = payload.get("jti")
        if jti is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        token_record = session.get(RefreshToken, UUID(jti))
        if token_record is None or token_record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        token_record.revoked = True
        session.add(token_record)
        session.commit()
        return None

    return router
