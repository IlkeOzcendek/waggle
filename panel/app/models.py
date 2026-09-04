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
    # How deep the anomalous windows fell outside the profile, where anomaly_fraction says
    # only how many of them did. Optional: an edge service or a hive profile from before
    # the acoustic model reported it sends events without one.
    anomaly_severity: float | None = Field(default=None, ge=0, le=1)
    consecutive_anomalies: int = Field(default=0, ge=0)
    source_file: str | None = Field(default=None, max_length=255)
    # The acoustic model file that produced this decision, so a report can trace its
    # measurements back to the ONNX profile and not only to the model that phrased them.
    model: str | None = Field(default=None, max_length=120)
    # Conditions at the moment of the recording, stamped by the panel and only when the
    # operator turned online weather on. Null everywhere else, and null is not "calm and
    # dry": wind and rain corrupt a recording, so a period whose weather was never
    # observed has to be read as unknown rather than as good. Never back-filled — the
    # weather of an alarm three days old was not measured and cannot be invented.
    temperature_c: float | None = Field(default=None, ge=-90, le=70)
    humidity_percent: int | None = Field(default=None, ge=0, le=100)
    wind_kmh: float | None = Field(default=None, ge=0, le=500)
    # WMO weather interpretation code, as Open-Meteo reports it.
    weather_code: int | None = Field(default=None, ge=0, le=99)


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


class ModelAssessment(BaseModel):
    """The structured judgement behind a report.

    It was being produced, validated and then thrown away: only the grounding ids reached
    the panel, so the one concrete output of the model — what it decided and why — could
    not be shown or audited. Every field is a closed set the validator already enforces.
    """

    priority: Literal["routine", "watch", "immediate"]
    pattern: str = Field(max_length=80)
    queen_loss_compatible: bool = False
    inspection_required: bool = False
    action_codes: list[str] = Field(default_factory=list, max_length=8)
    cross_check_model: str | None = Field(default=None, max_length=80)
    cross_check_agreed: bool | None = None


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
    assessment: ModelAssessment | None = None

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
    # How long this component may stay silent before its silence is a fault. Sent so the
    # panel can say "son veri 25 dakika önce, beklenen aralık 15 dakika" instead of "son
    # olay beklenen süreden eski", which names neither the delay nor the expectation.
    stale_after_seconds: int | None = None
    # What to actually do about it. A status page that reports a fault and stops has moved
    # the problem from the machine to the reader without helping them.
    remedies: list[str] = Field(default_factory=list, max_length=5)
    # Whether this component has a record of its own past contacts to show. Only the two
    # that receive something from outside do; the panel offers the link nowhere else,
    # rather than opening an empty timeline.
    has_history: bool = False


class ContactRecord(BaseModel):
    """One past contact with a component, for its connection history."""

    at: datetime
    label: str
    status: Literal["NORMAL", "WATCH", "ALARM", "ok"]


class ComponentHistory(BaseModel):
    component: str
    entries: list[ContactRecord]


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
    # Where the apiary is, as the weather service is asked about it. Separate from
    # location_name because that is a label and this is a place: they were allowed to
    # disagree, and the panel reported one town's conditions under another town's name —
    # then wrote that reading onto every event recorded while online weather was on.
    # Defaulted so a caller that predates the fields keeps the stored pair.
    latitude: float = Field(default=39.7897, ge=-90, le=90)
    longitude: float = Field(default=32.8065, ge=-180, le=180)
