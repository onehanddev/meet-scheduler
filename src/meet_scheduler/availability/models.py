from datetime import time
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, Integer, Time
from sqlalchemy.orm import Mapped, mapped_column

from meet_scheduler.database import Base


class AvailabilityWindow(Base):
    __tablename__ = "availability_windows"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    host_id: Mapped[UUID] = mapped_column(
        ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    __table_args__ = (
        Index("ix_availability_windows_host_id", "host_id"),
        Index("ix_availability_windows_host_weekday", "host_id", "weekday"),
    )
