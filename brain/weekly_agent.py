"""

It is an offline weekly report agent for the Waggle panel

"""

from __future__ import annotations # Type hints allowance for more flexible and forward looking use

from datetime import datetime, timedelta, timezone

import argparse
import os
import time

import requests

from brain.foundry_report import generate_agent_report

def _parse_timestamp(value: str) -> datetime: # convertion to utc datetime format
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def events_for_period(events: list[dict], period_start: datetime, period_end: datetime) -> list[dict]: # It retrieves all events and then filters and returns those within the given date and time range
    return [event for event in events if period_start <= _parse_timestamp(event["timestamp"]) <= period_end]

def run_period_report(
    panel_url: str,
    device_key: str,
    alias: str = "phi-3.5-mini",
    now: datetime | None = None,
    report_type: str = "weekly",
    event_id: int | None = None,
) -> list[dict]:
    
    """
    
    It fetches the last seven days, generates TR / EN reports and persists both in SQLite
    
    """

    period_end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond = 0)

    period_start = period_end - (timedelta(days=1) if report_type == "daily" else timedelta(days=7))

    headers = {"X-Device-Key": device_key}

    response = requests.get( # The system sends a request to the panel API getting the last or maximum 200 events and saves the received response to a response variable
        f"{panel_url.rstrip('/')}/api/agent/events?limit=200",
        headers = headers,
        timeout = 10,
    )

    response.raise_for_status()

    available_events = response.json()
    if report_type == "event":
        events = [event for event in available_events if event["id"] == event_id]
        if events:
            period_start = period_end = _parse_timestamp(events[0]["timestamp"])
    else:
        events = events_for_period(available_events, period_start, period_end)
    
    if not events:
        return []

    created = []
    for language in ("tr", "en"):
        report = generate_agent_report(events, language, alias)

        payload = { # The report gathers the date, summary, recommendations, hive type, language, model and source information into a single payload ready to be sent to the API
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "summary": report.summary,
            "recommendations": report.recommendations,
            "hive_ids": report.hive_ids,
            "language": report.language,
            "generator": report.generator,
            "grounding_sources": report.assessment.get("knowledge_ids", []),
            "report_type": report_type,
            "event_id": event_id if report_type == "event" else None,
        }

        posted = requests.post( # It sends or registers the payload report we prepared to the API and then place the response from the API into the posted file
            f"{panel_url.rstrip('/')}/api/reports",
            json = payload,
            headers = headers,
            timeout = 10,
        )

        posted.raise_for_status()

        created.append(posted.json())

    return created


def run_weekly_report(panel_url: str, device_key: str, alias: str = "phi-3.5-mini", now: datetime | None = None) -> list[dict]:
    """Backward-compatible weekly entry point used by the demo and tests."""
    return run_period_report(panel_url, device_key, alias, now, "weekly")


def main() -> None: # It gets the terminal settings and then generates weekly report and writes how many reports were generated, finishes if --watch doesn't exist and if it does then it waits the default 7 days and run again
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("--panel-url", default = "http://127.0.0.1:8000")
    parser.add_argument("--device-key", default = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"))
    parser.add_argument("--model", default = "phi-3.5-mini")
    parser.add_argument("--watch", action = "store_true", help = "Keep running and generate a report every interval")
    parser.add_argument("--interval-hours", type = float, default = 168)
    parser.add_argument("--report-type", choices=("event", "daily", "weekly"), default="weekly")
    parser.add_argument("--event-id", type=int)

    args = parser.parse_args()

    while True:
        if args.report_type == "event" and not args.event_id:
            parser.error("--event-id is required for an event report")
        reports = run_period_report(args.panel_url, args.device_key, args.model, report_type=args.report_type, event_id=args.event_id)

        print(f"{args.report_type}_reports_created={len(reports)}")

        if not args.watch:
            break

        time.sleep(max(args.interval_hours, 1 / 60) * 3600)

if __name__ == "__main__":
    main()
