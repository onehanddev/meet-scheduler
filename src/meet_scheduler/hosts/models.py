from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from meet_scheduler.database import Base


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(30), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default="Asia/Kolkata", server_default="Asia/Kolkata"
    )

    __table_args__ = (
        Index(
            "uq_hosts_username_lower",
            func.lower(username),
            unique=True,
            postgresql_where=(username.is_not(None)),
        ),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti: Mapped[UUID] = mapped_column(primary_key=True)
    host_id: Mapped[UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
