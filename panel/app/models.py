from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


EventType = Literal["healthy", "queenless_suspected", "uncertain"]


class HiveEventIn(BaseModel):
    hive_id: str = Field(pattern=r"^H[1-3]$", examples=["H3"])
    timestamp: datetime
    event: EventType
    confidence: float = Field(ge=0, le=1)


class HiveEvent(HiveEventIn):
    id: int
    alindi: datetime


class HiveSummary(BaseModel):
    hive_id: str
    durum: Literal["normal", "uyari", "kritik", "veri_yok"]
    last_event: EventType | None
    confidence: float | None
    timestamp: datetime | None


class DashboardState(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hives: list[HiveSummary]
    events: list[HiveEvent]


class ReportIn(BaseModel):
    period_start: datetime
    period_end: datetime
    summary: str = Field(min_length=10, max_length=4000)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    hive_ids: list[str] = Field(default_factory=lambda: ["H1", "H2", "H3"])

    @field_validator("hive_ids")
    @classmethod
    def validate_hive_ids(cls, value: list[str]) -> list[str]:
        if not value or any(hive_id not in {"H1", "H2", "H3"} for hive_id in value):
            raise ValueError("hive_ids yalnızca H1, H2 ve H3 içerebilir")
        return list(dict.fromkeys(value))


class Report(ReportIn):
    id: int
    created_at: datetime


class WeatherState(BaseModel):
    location: str
    temperature_c: float
    humidity_percent: int
    wind_kmh: float
    weather_code: int
    observed_at: datetime
