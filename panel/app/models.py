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
