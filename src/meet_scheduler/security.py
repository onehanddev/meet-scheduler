from uuid import UUID

import jwt
from fastapi import HTTPException, status

from meet_scheduler.config import Settings


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.token_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc


def get_host_id_from_access_token(
    authorization: str | None, settings: Settings
) -> UUID:
    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(token, settings)
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
    try:
        return UUID(host_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc
