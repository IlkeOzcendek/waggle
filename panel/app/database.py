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
    created_at TEXT NOT NULL
);
"""


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
                alindi TEXT NOT NULL,
                acknowledged_at TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO events
            (id, hive_id, timestamp, event, confidence, alindi, acknowledged_at)
            SELECT id, hive_id, timestamp, event, confidence, alindi, acknowledged_at
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

    def add(self, event: HiveEventIn) -> HiveEvent:
        received_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO events (hive_id, timestamp, event, confidence, alindi) VALUES (?, ?, ?, ?, ?)",
                (
                    event.hive_id,
                    event.timestamp.isoformat(),
                    event.event,
                    event.confidence,
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
                            last_event=None,
                            confidence=None,
                            timestamp=None,
                        )
                    )
                    continue
                event = self._event(row)
                status = "normal"
                if event.event == "queenless_suspected":
                    status = "kritik" if event.confidence >= 0.85 else "uyari"
                elif event.event == "uncertain":
                    status = "uyari"
                summaries.append(
                    HiveSummary(
                        hive_id=hive_id,
                        name=hive["name"],
                        location=hive["location"],
                        durum=status,
                        last_event=event.event,
                        confidence=event.confidence,
                        timestamp=event.timestamp,
                    )
                )
        return summaries

    def add_report(self, report: ReportIn) -> Report:
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reports
                (period_start, period_end, summary, recommendations, hive_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.summary,
                    json.dumps(report.recommendations, ensure_ascii=False),
                    json.dumps(report.hive_ids),
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
        return HiveEvent(
            id=row["id"],
            hive_id=row["hive_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event=row["event"],
            confidence=row["confidence"],
            alindi=datetime.fromisoformat(row["alindi"]),
            acknowledged_at=(
                datetime.fromisoformat(row["acknowledged_at"])
                if "acknowledged_at" in row.keys() and row["acknowledged_at"]
                else None
            ),
        )
