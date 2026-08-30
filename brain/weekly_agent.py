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

def run_weekly_report( # It retrieves events from the last 7 days from the API, filters them to those 7 days and stops if no events are found. Then it generates and saves a Turkish report and an English report and returns both reports
    panel_url: str,
    device_key: str,
    alias: str = "phi-3.5-mini",
    now: datetime | None = None,
) -> list[dict]:
    
    """
    
    It fetches the last seven days, generates TR / EN reports and persists both in SQLite
    
    """

    period_end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond = 0)

    period_start = period_end - timedelta(days = 7)

    headers = {"X-Device-Key": device_key}

    response = requests.get( # The system sends a request to the panel API getting the last or maximum 200 events and saves the received response to a response variable
        f"{panel_url.rstrip('/')}/api/agent/events?limit=200",
        headers = headers,
        timeout = 10,
    )

    response.raise_for_status()

    events = events_for_period(response.json(), period_start, period_end)
    
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


def main() -> None: # It gets the terminal settings and then generates weekly report and writes how many reports were generated, finishes if --watch doesn't exist and if it does then it waits the default 7 days and run again
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("--panel-url", default = "http://127.0.0.1:8000")
    parser.add_argument("--device-key", default = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"))
    parser.add_argument("--model", default = "phi-3.5-mini")
    parser.add_argument("--watch", action = "store_true", help = "Keep running and generate a report every interval")
    parser.add_argument("--interval-hours", type = float, default = 168)

    args = parser.parse_args()

    while True:
        reports = run_weekly_report(args.panel_url, args.device_key, args.model)

        print(f"weekly_reports_created={len(reports)}")

        if not args.watch:
            break

        time.sleep(max(args.interval_hours, 1 / 60) * 3600)

if __name__ == "__main__":
    main()
