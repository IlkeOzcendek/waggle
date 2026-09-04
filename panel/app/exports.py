from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Literal

from .database import EventStore


Dataset = Literal["hives", "events", "alarms", "reports", "confirmations", "guidance", "enrollment", "devices"]
FileFormat = Literal["csv", "json"]

# Which column carries the moment a row belongs to, and what group the dataset sits in on
# the export page. Three datasets have no period at all: a hive, a device and a guidance
# note describe the setup a measurement happened in, not the measurement. Filtering them
# by a date range would strip the very rows the filtered events point at, so a range never
# touches them — and the page has to say so rather than quietly return everything.
CATALOGUE: dict[str, dict] = {
    "hives": {"group": "operations", "time_field": None},
    "events": {"group": "operations", "time_field": "timestamp"},
    "alarms": {"group": "operations", "time_field": "timestamp"},
    "reports": {"group": "operations", "time_field": "created_at"},
    "confirmations": {"group": "operations", "time_field": "confirmed_at"},
    "enrollment": {"group": "system", "time_field": "recorded_at"},
    "devices": {"group": "system", "time_field": None},
    "guidance": {"group": "system", "time_field": None},
}


def _within(value, since: datetime | None, until: datetime | None) -> bool:
    """Whether a stored timestamp falls inside the requested range.

    A row whose timestamp cannot be read is kept. Dropping it would silently shrink an
    export that is meant to be the complete record, and a malformed date is a reason to
    look at the row, not to hide it.
    """
    if since is None and until is None:
        return True
    if not value:
        return True
    stamp = value if isinstance(value, datetime) else None
    if stamp is None:
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return True
    # Some tables store the moment without a zone. Comparing those against an aware bound
    # raises rather than filtering, which would lose the export instead of narrowing it.
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if since is not None and stamp < since:
        return False
    if until is not None and stamp > until:
        return False
    return True


def filter_rows(rows: list[dict], dataset: Dataset, since: datetime | None = None,
                until: datetime | None = None) -> list[dict]:
    """The rows of a dataset that fall inside a range, or all of them when it has no period."""
    field = CATALOGUE[dataset]["time_field"]
    if field is None or (since is None and until is None):
        return rows
    return [row for row in rows if _within(row.get(field), since, until)]


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
                # How deep the deviation was, beside how often it occurred. Two rows at the
                # same ratio are not the same measurement and the export said they were.
                "anomaly_severity": event.anomaly_severity,
                "consecutive_anomalies": event.consecutive_anomalies,
                "source_file": event.source_file,
                # The acoustic model behind the decision. An export that cannot say which
                # model measured a row is not an audit trail.
                "model": event.model,
                # The conditions the recording was taken in. Wind and rain put their own
                # sound on the microphone, so an export that cannot say what the weather
                # was cannot be used to tell a real alarm from a windy afternoon. Null
                # wherever online weather was off — never back-filled.
                "temperature_c": event.temperature_c,
                "humidity_percent": event.humidity_percent,
                "wind_kmh": event.wind_kmh,
                "weather_code": event.weather_code,
                "received_at": event.alindi.isoformat(),
                "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
                # Who inspected the hive is the audit trail behind an AI decision, and it
                # was being written to the database but left out of every export.
                "acknowledged_by": event.acknowledged_by,
                "inspection_result": event.inspection_result,
                "inspection_note": event.inspection_note,
            }
            for event in events
        ]
    if dataset == "confirmations":
        return store.health_confirmations()
    if dataset == "enrollment":
        # The 42-recording, 14-day gate is the project's central claim about learning a
        # specific hive. The panel showed the percentage and nothing let anyone check it.
        return store.enrollment_recordings()
    if dataset == "devices":
        return store.all_devices()
    if dataset == "guidance":
        # The reviewed notes an assessment can be grounded in. Exporting them is what lets
        # someone check the reasoning rather than take the report's word for it.
        from brain.local_rag import load_knowledge

        return [
            {
                "id": entry["id"],
                "tags": ", ".join(entry["tags"]),
                "tr": entry["tr"],
                "en": entry["en"],
                "conditions": json.dumps(entry.get("conditions", {}), ensure_ascii=False),
            }
            for entry in load_knowledge()
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
            "priority": report.assessment.priority if report.assessment else None,
            "pattern": report.assessment.pattern if report.assessment else None,
            "inspection_required": report.assessment.inspection_required if report.assessment else None,
            "cross_check_model": report.assessment.cross_check_model if report.assessment else None,
            "cross_check_agreed": report.assessment.cross_check_agreed if report.assessment else None,
        }
        for report in reports
    ]


# A spreadsheet reads a cell beginning with any of these as a formula, not as text. The
# export exists to be opened in one — it even carries a byte-order mark so Excel will —
# and the values in it are typed by people: hive names, apiary locations, inspection notes.
# A field worker's note reading `=HYPERLINK(...)` would have run on the owner's machine.
FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    """One CSV cell, with any spreadsheet formula in it defused into the text it is.

    The apostrophe is the convention every spreadsheet understands: it displays the value
    unchanged and refuses to evaluate it. Numbers are left alone — they arrive as numbers
    from the database, never as text a person typed, so a leading minus there is a sign.
    """
    if isinstance(value, list):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(FORMULA_LEADERS):
        return "'" + value
    return value


def _serialise(rows: list[dict], dataset: Dataset, file_format: FileFormat) -> bytes:
    if file_format == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")

    output = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else _empty_fieldnames(dataset)
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(value) for key, value in row.items()})
    # The byte-order mark is what makes a spreadsheet open a UTF-8 CSV as UTF-8 rather
    # than mangling every Turkish character in it.
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def build_export(store: EventStore, dataset: Dataset, file_format: FileFormat,
                 since: datetime | None = None, until: datetime | None = None) -> tuple[bytes, str, str]:
    rows = filter_rows(export_rows(store, dataset), dataset, since, until)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"waggle-{dataset}-{stamp}.{file_format}"
    media = "application/json; charset=utf-8" if file_format == "json" else "text/csv; charset=utf-8"
    return _serialise(rows, dataset, file_format), media, filename


def export_summary(store: EventStore, since: datetime | None = None,
                   until: datetime | None = None) -> list[dict]:
    """How many rows each dataset would export, and whether the range applied to it.

    The page asks people to choose what to download, and a choice made without knowing
    that a dataset is empty — or that the range it just set does not apply to it — is not
    an informed one.
    """
    summary = []
    for dataset, meta in CATALOGUE.items():
        try:
            rows = export_rows(store, dataset)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - one unreadable dataset must not blank the page
            summary.append({"dataset": dataset, "group": meta["group"], "count": None,
                            "period_filtered": False, "available": False})
            continue
        ranged = filter_rows(rows, dataset, since, until)  # type: ignore[arg-type]
        summary.append({
            "dataset": dataset,
            "group": meta["group"],
            "count": len(ranged),
            "total": len(rows),
            # False for the setup datasets, which a range never narrows.
            "period_filtered": bool(meta["time_field"]),
            "available": True,
        })
    return summary


def build_bundle(store: EventStore, datasets: list[Dataset], file_format: FileFormat,
                 since: datetime | None = None, until: datetime | None = None) -> tuple[bytes, str, str]:
    """Several datasets in one archive, with a manifest saying what is in it.

    A CSV holds one table, so "everything in one file" can only mean an archive. The
    manifest is what makes the archive readable a year later: which range was asked for,
    which datasets ignore a range, and how many rows each file actually holds.
    """
    stamp = datetime.now()
    manifest = {
        "generated_at": stamp.astimezone().isoformat(timespec="seconds"),
        "format": file_format,
        "period_start": since.isoformat() if since else None,
        "period_end": until.isoformat() if until else None,
        "datasets": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for dataset in datasets:
            rows = filter_rows(export_rows(store, dataset), dataset, since, until)
            name = f"waggle-{dataset}.{file_format}"
            archive.writestr(name, _serialise(rows, dataset, file_format))
            manifest["datasets"].append({
                "dataset": dataset,
                "file": name,
                "rows": len(rows),
                "period_filtered": bool(CATALOGUE[dataset]["time_field"]),
            })
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    filename = f"waggle-export-{stamp.strftime('%Y%m%d-%H%M%S')}.zip"
    return buffer.getvalue(), "application/zip", filename


def _empty_fieldnames(dataset: Dataset) -> list[str]:
    return {
        "hives": ["hive_id", "name", "location", "active", "created_at"],
        "events": ["id", "hive_id", "hive_name", "timestamp", "status", "anomaly_fraction", "anomaly_severity", "consecutive_anomalies", "source_file", "model", "temperature_c", "humidity_percent", "wind_kmh", "weather_code", "received_at", "acknowledged_at", "acknowledged_by", "inspection_result", "inspection_note"],
        "alarms": ["id", "hive_id", "hive_name", "timestamp", "status", "anomaly_fraction", "anomaly_severity", "consecutive_anomalies", "source_file", "model", "temperature_c", "humidity_percent", "wind_kmh", "weather_code", "received_at", "acknowledged_at", "acknowledged_by", "inspection_result", "inspection_note"],
        "reports": ["id", "period_start", "period_end", "summary", "recommendations", "hive_ids", "language", "generator", "grounding_sources", "report_type", "event_id", "created_at", "priority", "pattern", "inspection_required", "cross_check_model", "cross_check_agreed"],
        "confirmations": ["id", "hive_id", "confirmed_at", "evidence", "note", "accepted_for_enrollment", "confirmed_by"],
        "guidance": ["id", "tags", "conditions", "tr", "en"],
        "enrollment": ["id", "hive_id", "hive_name", "device_id", "recorded_at", "recorded_day", "filename", "window_count", "healthy_confirmed"],
        "devices": ["device_id", "hive_id", "hive_name", "name", "kind", "active", "created_at", "last_seen_at"],
    }[dataset]
