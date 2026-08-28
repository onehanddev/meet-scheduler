from uuid import UUID

from pydantic import BaseModel


class HostProfileResponse(BaseModel):
    id: UUID
    email: str
    username: str | None = None
    display_name: str | None = None
    timezone: str | None = None
