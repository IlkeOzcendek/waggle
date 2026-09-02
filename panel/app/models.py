from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


EventStatus = Literal["NORMAL", "WATCH", "ALARM"]
EnrollmentState = Literal["device_required", "enrolling", "ready", "monitoring"]
DeviceKind = Literal["phone", "sensor", "folder", "demo"]
HealthEvidence = Literal["queen_seen", "brood_healthy", "hive_healthy", "uncertain"]
InspectionResult = Literal["issue_confirmed", "no_issue_found", "uncertain"]
GroundingSource = Annotated[str, Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")]


class HiveEventIn(BaseModel):
    hive_id: str = Field(pattern=r"^H[1-9][0-9]{0,2}$", examples=["H3"])
    timestamp: datetime
    status: EventStatus
    anomaly_fraction: float = Field(ge=0, le=1)
    consecutive_anomalies: int = Field(default=0, ge=0)
    source_file: str | None = Field(default=None, max_length=255)


class HiveEvent(HiveEventIn):
    id: int
    alindi: datetime
    acknowledged_at: datetime | None = None
    inspection_result: InspectionResult | None = None
    inspection_note: str | None = None
    # Which account recorded the physical inspection. Null on events acknowledged before
    # the panel tracked it, and on anything an unauthenticated edge service wrote.
    acknowledged_by: str | None = None


class AlarmInspectionIn(BaseModel):
    result: InspectionResult
    note: str | None = Field(default=None, max_length=500)


class SensorAnalysis(BaseModel):
    mode: Literal["enrollment", "monitoring"]
    event: HiveEvent | None = None
    windows: int = Field(ge=1)
    model: str | None = None
    note: str


class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: DeviceKind = "phone"


class Device(DeviceCreate):
    device_id: str
    hive_id: str
    active: bool = True
    created_at: datetime
    last_seen_at: datetime | None = None


class EnrollmentStatus(BaseModel):
    hive_id: str
    state: EnrollmentState
    recording_count: int = Field(ge=0)
    recording_days: int = Field(ge=0)
    required_recordings: int = Field(default=42, ge=1)
    required_days: int = Field(default=14, ge=1)
    progress_percent: int = Field(ge=0, le=100)
    can_monitor: bool
    ready_to_train: bool = False
    model_path: str | None = None
    confirmation_count: int = Field(default=0, ge=0)
    required_confirmations: int = Field(default=4, ge=1)
    confirmation_due: bool = True
    last_confirmation_at: datetime | None = None


class HealthConfirmationIn(BaseModel):
    evidence: HealthEvidence
    note: str | None = Field(default=None, max_length=500)


class HealthConfirmation(HealthConfirmationIn):
    id: int
    hive_id: str
    confirmed_at: datetime
    accepted_for_enrollment: bool
    confirmed_by: str | None = None


class HiveSummary(BaseModel):
    hive_id: str
    name: str
    location: str | None = None
    durum: Literal["normal", "uyari", "kritik", "veri_yok"]
    last_status: EventStatus | None
    anomaly_fraction: float | None
    timestamp: datetime | None


class DashboardState(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hives: list[HiveSummary]
    events: list[HiveEvent]


class HiveCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    location: str | None = Field(default=None, max_length=160)


class HiveUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    location: str | None = Field(default=None, max_length=160)


class Hive(HiveCreate):
    hive_id: str
    active: bool = True
    created_at: datetime


class ReportIn(BaseModel):
    period_start: datetime
    period_end: datetime
    summary: str = Field(min_length=10, max_length=4000)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    hive_ids: list[str] = Field(default_factory=lambda: ["H1", "H2", "H3"])
    language: Literal["tr", "en"] = "tr"
    generator: str = Field(default="manual", min_length=2, max_length=80)
    grounding_sources: list[GroundingSource] = Field(default_factory=list, max_length=10)
    report_type: Literal["event", "daily", "weekly"] = "weekly"
    event_id: int | None = Field(default=None, ge=1)

    @field_validator("hive_ids")
    @classmethod
    def validate_hive_ids(cls, value: list[str]) -> list[str]:
        if not value or any(not hive_id.startswith("H") for hive_id in value):
            raise ValueError("Geçerli kovan kimlikleri kullanın")
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


class ComponentStatus(BaseModel):
    key: str
    name: str
    status: Literal["ok", "waiting", "warning"]
    summary: str
    detail: str
    last_seen_at: datetime | None = None


class SystemStatus(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall: Literal["ok", "attention"]
    components: list[ComponentStatus]


class AppSettings(BaseModel):
    panel_name: str = Field(min_length=2, max_length=60)
    location_name: str = Field(min_length=2, max_length=100)
    alarm_threshold: float = Field(ge=0.5, le=0.99)
    sound_enabled: bool = True
    refresh_seconds: int = Field(ge=2, le=60)
    onboarding_completed: bool = False
    weather_enabled: bool = False
    language: Literal["tr", "en"] = "tr"
