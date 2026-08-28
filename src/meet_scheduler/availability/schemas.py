import re
from datetime import time

from pydantic import BaseModel, field_validator

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_time(value: str) -> time:
    if not isinstance(value, str):
        raise ValueError("time must be string HH:MM")
    m = TIME_RE.match(value.strip())
    if not m:
        raise ValueError("time must be HH:MM 00:00-23:59")
    hour = int(m.group(1))
    minute = int(m.group(2))
    return time(hour=hour, minute=minute)


class AvailabilityWindowIn(BaseModel):
    weekday: int
    start: str
    end: str

    @field_validator("weekday")
    @classmethod
    def validate_weekday(cls, v: int) -> int:
        if not isinstance(v, int):
            raise ValueError("weekday must be integer 0-6")
        if v < 0 or v > 6:
            raise ValueError("weekday must be between 0 and 6")
        return v

    @field_validator("start", "end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        # triggers TIME_RE validation
        _parse_time(v)
        return v.strip()


class AvailabilityReplaceRequest(BaseModel):
    windows: list[AvailabilityWindowIn]


class AvailabilityWindowOut(BaseModel):
    weekday: int
    start: str
    end: str


class AvailabilityResponse(BaseModel):
    windows: list[AvailabilityWindowOut]
