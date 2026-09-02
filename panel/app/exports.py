from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Literal

from .database import EventStore


Dataset = Literal["hives", "events", "alarms", "reports"]
FileFormat = Literal["csv", "json"]


def export_rows(store: EventStore, dataset: Dataset) -> list[dict]:
    hives = store.hives(include_inactive=True)
    hive_names = {hive.hive_id: hive.name for hive in hives}
    if dataset == "hives":
        return [hive.model_dump(mode="json") for hive in hives]
    if dataset in {"events", "alarms"}:
        events = store.recent(1_000_000)
        if dataset == "alarms":
            events = [event for event in events if event.status == "ALARM"]
        return [
            {
                "id": event.id,
                "hive_id": event.hive_id,
                "hive_name": hive_names.get(event.hive_id, "Bilinmeyen kovan"),
                "timestamp": event.timestamp.isoformat(),
                "status": event.status,
                "anomaly_fraction": event.anomaly_fraction,
                "consecutive_anomalies": event.consecutive_anomalies,
                "source_file": event.source_file,
                "received_at": event.alindi.isoformat(),
                "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
                "inspection_result": event.inspection_result,
                "inspection_note": event.inspection_note,
            }
            for event in events
        ]
    reports = store.reports(1_000_000)
    return [
        {
            "id": report.id,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "summary": report.summary,
            "recommendations": report.recommendations,
            "hive_ids": report.hive_ids,
            "language": report.language,
            "generator": report.generator,
            "grounding_sources": report.grounding_sources,
            "report_type": report.report_type,
            "event_id": report.event_id,
            "created_at": report.created_at.isoformat(),
        }
        for report in reports
    ]


def build_export(store: EventStore, dataset: Dataset, file_format: FileFormat) -> tuple[bytes, str, str]:
    rows = export_rows(store, dataset)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"waggle-{dataset}-{stamp}.{file_format}"
    if file_format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        return content, "application/json; charset=utf-8", filename

    output = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else _empty_fieldnames(dataset)
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                for key, value in row.items()
            }
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", filename


def _empty_fieldnames(dataset: Dataset) -> list[str]:
    return {
        "hives": ["hive_id", "name", "location", "active", "created_at"],
        "events": ["id", "hive_id", "hive_name", "timestamp", "status", "anomaly_fraction", "consecutive_anomalies", "source_file", "received_at", "acknowledged_at", "inspection_result", "inspection_note"],
        "alarms": ["id", "hive_id", "hive_name", "timestamp", "status", "anomaly_fraction", "consecutive_anomalies", "source_file", "received_at", "acknowledged_at", "inspection_result", "inspection_note"],
        "reports": ["id", "period_start", "period_end", "summary", "recommendations", "hive_ids", "language", "generator", "grounding_sources", "report_type", "event_id", "created_at"],
    }[dataset]
