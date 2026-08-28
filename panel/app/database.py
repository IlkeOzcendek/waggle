from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import json

from .models import Hive, HiveCreate, HiveEvent, HiveEventIn, HiveSummary, HiveUpdate, Report, ReportIn


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
        return Hive(hive_id=hive_id, name=hive.name.strip(), location=hive.location.strip() if hive.location else None, active=True, created_at=created_at)

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
                 language, generator, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.summary,
                    json.dumps(report.recommendations, ensure_ascii=False),
                    json.dumps(report.hive_ids),
                    report.language,
                    report.generator,
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
