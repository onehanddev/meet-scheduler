from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from meet_scheduler.availability.models import AvailabilityWindow


class AvailabilityProvider(Protocol):
    """Boundary for slot calculation — not direct DB queries throughout codebase."""

    def get_windows(self, host_id: UUID) -> list[dict]:
        """Return list of {weekday, start_time, end_time} host-local."""
        ...


class WeeklyAvailabilityProvider:
    """Initial provider: returns only weekly recurring windows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_windows(self, host_id: UUID) -> list[dict]:
        rows = self.session.scalars(
            select(AvailabilityWindow).where(AvailabilityWindow.host_id == host_id)
        ).all()
        return [
            {
                "weekday": r.weekday,
                "start_time": r.start_time,
                "end_time": r.end_time,
            }
            for r in rows
        ]

    def get_windows_for_host(self, host_id: UUID) -> list[AvailabilityWindow]:
        return list(
            self.session.scalars(
                select(AvailabilityWindow).where(AvailabilityWindow.host_id == host_id)
            ).all()
        )
