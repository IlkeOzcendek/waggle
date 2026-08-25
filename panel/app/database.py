from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import HiveEvent, HiveEventIn, HiveSummary


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL CHECK (hive_id IN ('H1', 'H2', 'H3')),
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('healthy', 'queenless_suspected', 'uncertain')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    alindi TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_hive_time ON events(hive_id, timestamp DESC);
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

    @staticmethod
    def _event(row: sqlite3.Row) -> HiveEvent:
        return HiveEvent(
            id=row["id"],
            hive_id=row["hive_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event=row["event"],
            confidence=row["confidence"],
            alindi=datetime.fromisoformat(row["alindi"]),
        )
