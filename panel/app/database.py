from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import json

from .models import HiveEvent, HiveEventIn, HiveSummary, Report, ReportIn


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL CHECK (hive_id IN ('H1', 'H2', 'H3')),
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

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "acknowledged_at" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN acknowledged_at TEXT")

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

    def summaries(self, hive_ids: tuple[str, ...] = ("H1", "H2", "H3")) -> list[HiveSummary]:
        summaries: list[HiveSummary] = []
        with self.connect() as connection:
            for hive_id in hive_ids:
                row = connection.execute(
                    "SELECT * FROM events WHERE hive_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (hive_id,),
                ).fetchone()
                if row is None:
                    summaries.append(
                        HiveSummary(
                            hive_id=hive_id,
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
