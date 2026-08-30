from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import json

from .models import Device, DeviceCreate, EnrollmentStatus, HealthConfirmation, HealthConfirmationIn, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveSummary, HiveUpdate, Report, ReportIn


SCHEMA = """
CREATE TABLE IF NOT EXISTS hives (
    hive_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('healthy', 'queenless_suspected', 'uncertain')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    consecutive_anomalies INTEGER NOT NULL DEFAULT 0,
    source_file TEXT,
    alindi TEXT NOT NULL,
    acknowledged_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_hive_time ON events(hive_id, timestamp DESC);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    recommendations TEXT NOT NULL,
    hive_ids TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'tr' CHECK (language IN ('tr', 'en')),
    generator TEXT NOT NULL DEFAULT 'manual',
    grounding_sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    panel_name TEXT NOT NULL,
    location_name TEXT NOT NULL,
    alarm_threshold REAL NOT NULL,
    sound_enabled INTEGER NOT NULL,
    refresh_seconds INTEGER NOT NULL,
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    weather_enabled INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT 'tr' CHECK (language IN ('tr', 'en'))
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    hive_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('phone', 'sensor', 'folder', 'demo')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE INDEX IF NOT EXISTS idx_devices_hive ON devices(hive_id, active);
CREATE TABLE IF NOT EXISTS hive_profiles (
    hive_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('device_required', 'enrolling', 'ready', 'monitoring')),
    model_path TEXT,
    enrollment_started_at TEXT,
    ready_at TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE TABLE IF NOT EXISTS enrollment_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    window_count INTEGER NOT NULL,
    healthy_confirmed INTEGER NOT NULL,
    feature_names TEXT,
    features TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id),
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_enrollment_hive_time ON enrollment_recordings(hive_id, recorded_at);
CREATE TABLE IF NOT EXISTS health_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK (evidence IN ('queen_seen', 'brood_healthy', 'hive_healthy', 'uncertain')),
    note TEXT,
    accepted_for_enrollment INTEGER NOT NULL,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE INDEX IF NOT EXISTS idx_health_confirmation_hive_time ON health_confirmations(hive_id, confirmed_at DESC);
"""

REQUIRED_BACKUP_COLUMNS = {
    "hives": {"hive_id", "name", "location", "active", "created_at"},
    "events": {"id", "hive_id", "timestamp", "event", "confidence", "alindi"},
    "reports": {"id", "period_start", "period_end", "summary", "recommendations", "hive_ids", "created_at"},
    "settings": {"id", "panel_name", "location_name", "alarm_threshold", "sound_enabled", "refresh_seconds"},
}


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "acknowledged_at" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN acknowledged_at TEXT")
            if "consecutive_anomalies" not in columns:
                connection.execute(
                    "ALTER TABLE events ADD COLUMN consecutive_anomalies INTEGER NOT NULL DEFAULT 0"
                )
            if "source_file" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN source_file TEXT")
            settings_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(settings)")
            }
            if "onboarding_completed" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0"
                )
            if "weather_enabled" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN weather_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "language" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN language TEXT NOT NULL DEFAULT 'tr'"
                )
            report_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(reports)")
            }
            if "language" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN language TEXT NOT NULL DEFAULT 'tr'"
                )
            if "generator" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN generator TEXT NOT NULL DEFAULT 'manual'"
                )
            if "grounding_sources" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN grounding_sources TEXT NOT NULL DEFAULT '[]'"
                )
            enrollment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(enrollment_recordings)")
            }
            if "feature_names" not in enrollment_columns:
                connection.execute("ALTER TABLE enrollment_recordings ADD COLUMN feature_names TEXT")
            if "features" not in enrollment_columns:
                connection.execute("ALTER TABLE enrollment_recordings ADD COLUMN features TEXT")
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'events'"
            ).fetchone()["sql"]
            if "hive_id IN" in table_sql:
                self._migrate_events_table(connection)
            now = datetime.now(timezone.utc).isoformat()
            defaults = [
                ("H1", "Bahçe Kovanı", "Bahçe", now),
                ("H2", "Orman Kovanı", "Orman", now),
                ("H3", "Deneme Kovanı", "Test alanı", now),
            ]
            connection.executemany(
                "INSERT OR IGNORE INTO hives (hive_id, name, location, created_at) VALUES (?, ?, ?, ?)",
                defaults,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO hive_profiles (hive_id, state, model_path, ready_at) VALUES (?, 'monitoring', ?, ?)",
                [(hive_id, "results/mendeley_isolation_monitor.onnx", now) for hive_id, *_ in defaults],
            )
            connection.execute(
                """INSERT OR IGNORE INTO settings
                (id, panel_name, location_name, alarm_threshold, sound_enabled, refresh_seconds)
                VALUES (1, 'Waggle', 'Demo Kovanları', 0.85, 1, 5)"""
            )

    @staticmethod
    def _migrate_events_table(connection: sqlite3.Connection) -> None:
        connection.execute("DROP INDEX IF EXISTS idx_events_hive_time")
        connection.execute("ALTER TABLE events RENAME TO events_legacy")
        connection.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hive_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL CHECK (event IN ('healthy', 'queenless_suspected', 'uncertain')),
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                consecutive_anomalies INTEGER NOT NULL DEFAULT 0,
                source_file TEXT,
                alindi TEXT NOT NULL,
                acknowledged_at TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO events
            (id, hive_id, timestamp, event, confidence, consecutive_anomalies,
             source_file, alindi, acknowledged_at)
            SELECT id, hive_id, timestamp, event, confidence, 0, NULL, alindi,
                   acknowledged_at
            FROM events_legacy"""
        )
        connection.execute("DROP TABLE events_legacy")
        connection.execute(
            "CREATE INDEX idx_events_hive_time ON events(hive_id, timestamp DESC)"
        )

    def hives(self, include_inactive: bool = False) -> list[Hive]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hives WHERE active = 1 OR ? = 1 ORDER BY active DESC, CAST(SUBSTR(hive_id, 2) AS INTEGER)",
                (int(include_inactive),),
            ).fetchall()
        return [self._hive(row) for row in rows]

    def add_hive(self, hive: HiveCreate) -> Hive:
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            rows = connection.execute("SELECT hive_id FROM hives").fetchall()
            numbers = [int(row["hive_id"][1:]) for row in rows if row["hive_id"][1:].isdigit()]
            hive_id = f"H{max(numbers, default=0) + 1}"
            connection.execute(
                "INSERT INTO hives (hive_id, name, location, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (hive_id, hive.name.strip(), hive.location.strip() if hive.location else None, created_at.isoformat()),
            )
            connection.execute(
                "INSERT INTO hive_profiles (hive_id, state) VALUES (?, 'device_required')",
                (hive_id,),
            )
        return Hive(hive_id=hive_id, name=hive.name.strip(), location=hive.location.strip() if hive.location else None, active=True, created_at=created_at)

    def devices(self, hive_id: str) -> list[Device]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices WHERE hive_id = ? ORDER BY active DESC, created_at",
                (hive_id,),
            ).fetchall()
        return [self._device(row) for row in rows]

    def add_device(self, hive_id: str, device: DeviceCreate) -> Device:
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            profile = connection.execute(
                "SELECT state FROM hive_profiles WHERE hive_id = ?", (hive_id,)
            ).fetchone()
            active_devices = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE hive_id = ? AND active = 1", (hive_id,)
            ).fetchone()[0]
            if profile and profile["state"] == "enrolling" and active_devices:
                raise ValueError("Öğrenme sırasında tek bir mikrofon kullanılmalıdır")
            count = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE hive_id = ?", (hive_id,)
            ).fetchone()[0]
            device_id = f"{hive_id}-D{count + 1}"
            connection.execute(
                "INSERT INTO devices (device_id, hive_id, name, kind, created_at) VALUES (?, ?, ?, ?, ?)",
                (device_id, hive_id, device.name.strip(), device.kind, created_at.isoformat()),
            )
            connection.execute(
                "UPDATE hive_profiles SET state = 'enrolling', enrollment_started_at = COALESCE(enrollment_started_at, ?) WHERE hive_id = ? AND state = 'device_required'",
                (created_at.isoformat(), hive_id),
            )
        return Device(device_id=device_id, hive_id=hive_id, name=device.name.strip(), kind=device.kind, created_at=created_at)

    def enrollment_status(self, hive_id: str) -> EnrollmentStatus:
        with self.connect() as connection:
            profile = connection.execute(
                "SELECT state, model_path FROM hive_profiles WHERE hive_id = ?", (hive_id,)
            ).fetchone()
            counts = connection.execute(
                "SELECT COUNT(*) AS recordings, COUNT(DISTINCT SUBSTR(recorded_at, 1, 10)) AS days FROM enrollment_recordings WHERE hive_id = ? AND healthy_confirmed = 1",
                (hive_id,),
            ).fetchone()
            confirmations = connection.execute(
                "SELECT COALESCE(SUM(accepted_for_enrollment), 0) AS accepted, MAX(CASE WHEN accepted_for_enrollment = 1 THEN confirmed_at END) AS last_at FROM health_confirmations WHERE hive_id = ?",
                (hive_id,),
            ).fetchone()
        state = profile["state"] if profile else "device_required"
        recordings, days = int(counts["recordings"]), int(counts["days"])
        confirmation_count = int(confirmations["accepted"])
        last_confirmation = datetime.fromisoformat(confirmations["last_at"]) if confirmations["last_at"] else None
        confirmation_due = last_confirmation is None or datetime.now(timezone.utc) - last_confirmation > timedelta(days=4)
        progress = min(100, round(
            40 * min(recordings / 42, 1) + 40 * min(days / 14, 1) + 20 * min(confirmation_count / 4, 1)
        ))
        return EnrollmentStatus(
            hive_id=hive_id, state=state, recording_count=recordings,
            recording_days=days, progress_percent=100 if state in {"ready", "monitoring"} else progress,
            can_monitor=state in {"ready", "monitoring"},
            ready_to_train=recordings >= 42 and days >= 14 and confirmation_count >= 4 and state == "enrolling",
            model_path=profile["model_path"] if profile else None,
            confirmation_count=confirmation_count,
            confirmation_due=confirmation_due and state == "enrolling",
            last_confirmation_at=last_confirmation,
        )

    def add_health_confirmation(self, hive_id: str, confirmation: HealthConfirmationIn) -> HealthConfirmation:
        confirmed_at = datetime.now(timezone.utc)
        accepted = confirmation.evidence != "uncertain"
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO health_confirmations (hive_id, confirmed_at, evidence, note, accepted_for_enrollment) VALUES (?, ?, ?, ?, ?)",
                (hive_id, confirmed_at.isoformat(), confirmation.evidence, confirmation.note.strip() if confirmation.note else None, int(accepted)),
            )
        return HealthConfirmation(
            id=cursor.lastrowid, hive_id=hive_id, confirmed_at=confirmed_at,
            evidence=confirmation.evidence, note=confirmation.note,
            accepted_for_enrollment=accepted,
        )

    def add_enrollment_recording(self, hive_id: str, device_id: str, filename: str, values, feature_names) -> EnrollmentStatus:
        now = datetime.now(timezone.utc)
        with self.connect() as connection:
            device = connection.execute(
                "SELECT 1 FROM devices WHERE device_id = ? AND hive_id = ? AND active = 1",
                (device_id, hive_id),
            ).fetchone()
            if device is None:
                raise ValueError("Cihaz bu kovana bağlı değil")
            connection.execute(
                "INSERT INTO enrollment_recordings (hive_id, device_id, recorded_at, filename, window_count, healthy_confirmed, feature_names, features) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (hive_id, device_id, now.isoformat(), filename, len(values), json.dumps(list(feature_names)), json.dumps(values.tolist() if hasattr(values, "tolist") else values)),
            )
            connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?", (now.isoformat(), device_id)
            )
        return self.enrollment_status(hive_id)

    def enrollment_features(self, hive_id: str):
        import numpy as np

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT feature_names, features FROM enrollment_recordings WHERE hive_id = ? AND healthy_confirmed = 1 AND features IS NOT NULL ORDER BY recorded_at, id",
                (hive_id,),
            ).fetchall()
        if not rows:
            raise ValueError("Öğrenme özelliği bulunamadı")
        schemas = [json.loads(row["feature_names"]) for row in rows]
        if any(schema != schemas[0] for schema in schemas[1:]):
            raise ValueError("Özellik şeması kayıtlar arasında değişmiş")
        matrices = [np.asarray(json.loads(row["features"]), dtype=np.float64) for row in rows]
        return np.concatenate(matrices), schemas[0]

    def activate_profile(self, hive_id: str, model_path: str) -> EnrollmentStatus:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "UPDATE hive_profiles SET state = 'monitoring', model_path = ?, ready_at = ? WHERE hive_id = ?",
                (model_path, now, hive_id),
            )
        return self.enrollment_status(hive_id)

    def touch_device(self, device_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (datetime.now(timezone.utc).isoformat(), device_id),
            )

    def has_hive(self, hive_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM hives WHERE hive_id = ? AND active = 1", (hive_id,)
            ).fetchone() is not None

    def update_hive(self, hive_id: str, hive: HiveUpdate) -> Hive | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE hives SET name = ?, location = ? WHERE hive_id = ?",
                (hive.name.strip(), hive.location.strip() if hive.location else None, hive_id),
            )
            row = connection.execute("SELECT * FROM hives WHERE hive_id = ?", (hive_id,)).fetchone()
        return self._hive(row) if row else None

    def set_hive_active(self, hive_id: str, active: bool) -> Hive | None:
        with self.connect() as connection:
            connection.execute("UPDATE hives SET active = ? WHERE hive_id = ?", (int(active), hive_id))
            row = connection.execute("SELECT * FROM hives WHERE hive_id = ?", (hive_id,)).fetchone()
        return self._hive(row) if row else None

    def backup_to(self, destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination_path)
        try:
            with self.connect() as source:
                source.backup(target)
        finally:
            target.close()
        return destination_path

    @staticmethod
    def validate_backup(source: str | Path) -> None:
        connection = sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("Yedek dosyasının SQLite bütünlük kontrolü başarısız")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for table, required_columns in REQUIRED_BACKUP_COLUMNS.items():
                if table not in tables:
                    raise ValueError(f"Yedekte gerekli {table} tablosu bulunamadı")
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if not required_columns.issubset(columns):
                    raise ValueError(f"Yedekteki {table} tablosu Waggle ile uyumlu değil")
        except sqlite3.DatabaseError as exc:
            raise ValueError("Dosya geçerli bir SQLite yedeği değil") from exc
        finally:
            connection.close()

    def restore_from(self, source: str | Path) -> None:
        self.validate_backup(source)
        backup = sqlite3.connect(str(source))
        try:
            with self.connect() as destination:
                backup.backup(destination)
        finally:
            backup.close()

    def diagnostics(self) -> dict[str, object]:
        """Return lightweight, read-only database and integration metrics."""
        with self.connect() as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("hives", "events", "reports")
            }
            last_event = connection.execute("SELECT MAX(alindi) FROM events").fetchone()[0]
            last_report = connection.execute("SELECT MAX(created_at) FROM reports").fetchone()[0]
        return {
            "integrity": integrity,
            "counts": counts,
            "last_event_at": datetime.fromisoformat(last_event) if last_event else None,
            "last_report_at": datetime.fromisoformat(last_report) if last_report else None,
        }

    def add(self, event: HiveEventIn) -> HiveEvent:
        received_at = datetime.now(timezone.utc)
        legacy_event = {
            "NORMAL": "healthy",
            "WATCH": "uncertain",
            "ALARM": "queenless_suspected",
        }[event.status]
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO events
                (hive_id, timestamp, event, confidence, consecutive_anomalies,
                 source_file, alindi) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.hive_id,
                    event.timestamp.isoformat(),
                    legacy_event,
                    event.anomaly_fraction,
                    event.consecutive_anomalies,
                    event.source_file,
                    received_at.isoformat(),
                ),
            )
            event_id = cursor.lastrowid
        return HiveEvent(id=event_id, alindi=received_at, **event.model_dump())

    def recent(self, limit: int = 50) -> list[HiveEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY timestamp DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._event(row) for row in rows]

    def acknowledge(self, event_id: int) -> HiveEvent | None:
        acknowledged_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            connection.execute(
                "UPDATE events SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
                (acknowledged_at.isoformat(), event_id),
            )
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event(row) if row else None

    def summaries(self) -> list[HiveSummary]:
        summaries: list[HiveSummary] = []
        with self.connect() as connection:
            hives = connection.execute(
                "SELECT * FROM hives WHERE active = 1 ORDER BY CAST(SUBSTR(hive_id, 2) AS INTEGER)"
            ).fetchall()
            for hive in hives:
                hive_id = hive["hive_id"]
                row = connection.execute(
                    "SELECT * FROM events WHERE hive_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (hive_id,),
                ).fetchone()
                if row is None:
                    summaries.append(
                        HiveSummary(
                            hive_id=hive_id,
                            name=hive["name"],
                            location=hive["location"],
                            durum="veri_yok",
                            last_status=None,
                            anomaly_fraction=None,
                            timestamp=None,
                        )
                    )
                    continue
                event = self._event(row)
                status = {
                    "NORMAL": "normal",
                    "WATCH": "uyari",
                    "ALARM": "kritik",
                }[event.status]
                summaries.append(
                    HiveSummary(
                        hive_id=hive_id,
                        name=hive["name"],
                        location=hive["location"],
                        durum=status,
                        last_status=event.status,
                        anomaly_fraction=event.anomaly_fraction,
                        timestamp=event.timestamp,
                    )
                )
        return summaries

    def settings(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return {
            "panel_name": row["panel_name"],
            "location_name": row["location_name"],
            "alarm_threshold": row["alarm_threshold"],
            "sound_enabled": bool(row["sound_enabled"]),
            "refresh_seconds": row["refresh_seconds"],
            "onboarding_completed": bool(row["onboarding_completed"]),
            "weather_enabled": bool(row["weather_enabled"]),
            "language": row["language"],
        }

    def update_settings(self, values: dict[str, object]) -> dict[str, object]:
        with self.connect() as connection:
            connection.execute(
                """UPDATE settings SET panel_name = ?, location_name = ?, alarm_threshold = ?,
                sound_enabled = ?, refresh_seconds = ?, onboarding_completed = ?,
                weather_enabled = ?, language = ? WHERE id = 1""",
                (
                    values["panel_name"], values["location_name"], values["alarm_threshold"],
                    int(bool(values["sound_enabled"])), values["refresh_seconds"],
                    int(bool(values["onboarding_completed"])),
                    int(bool(values["weather_enabled"])),
                    values.get("language", "tr"),
                ),
            )
        return self.settings()

    def add_report(self, report: ReportIn) -> Report:
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reports
                (period_start, period_end, summary, recommendations, hive_ids,
                 language, generator, grounding_sources, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.summary,
                    json.dumps(report.recommendations, ensure_ascii=False),
                    json.dumps(report.hive_ids),
                    report.language,
                    report.generator,
                    json.dumps(report.grounding_sources),
                    created_at.isoformat(),
                ),
            )
            report_id = cursor.lastrowid
        return Report(id=report_id, created_at=created_at, **report.model_dump())

    def reports(self, limit: int = 10) -> list[Report]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY period_end DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Report(
                id=row["id"],
                period_start=datetime.fromisoformat(row["period_start"]),
                period_end=datetime.fromisoformat(row["period_end"]),
                summary=row["summary"],
                recommendations=json.loads(row["recommendations"]),
                hive_ids=json.loads(row["hive_ids"]),
                language=row["language"] if "language" in row.keys() else "tr",
                generator=row["generator"] if "generator" in row.keys() else "manual",
                grounding_sources=json.loads(row["grounding_sources"]) if "grounding_sources" in row.keys() else [],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _hive(row: sqlite3.Row) -> Hive:
        return Hive(
            hive_id=row["hive_id"],
            name=row["name"],
            location=row["location"],
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            device_id=row["device_id"], hive_id=row["hive_id"], name=row["name"],
            kind=row["kind"], active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None,
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> HiveEvent:
        status = {
            "healthy": "NORMAL",
            "uncertain": "WATCH",
            "queenless_suspected": "ALARM",
        }[row["event"]]
        return HiveEvent(
            id=row["id"],
            hive_id=row["hive_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            status=status,
            anomaly_fraction=row["confidence"],
            consecutive_anomalies=(
                row["consecutive_anomalies"]
                if "consecutive_anomalies" in row.keys() else 0
            ),
            source_file=(row["source_file"] if "source_file" in row.keys() else None),
            alindi=datetime.fromisoformat(row["alindi"]),
            acknowledged_at=(
                datetime.fromisoformat(row["acknowledged_at"])
                if "acknowledged_at" in row.keys() and row["acknowledged_at"]
                else None
            ),
        )
