#!/usr/bin/env python3
"""Send model output to Waggle with retry and an offline queue."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


DEFAULT_URL = os.getenv("WAGGLE_API_URL", "http://127.0.0.1:8001/api/events")
DEFAULT_KEY = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
DEFAULT_QUEUE = Path(os.getenv("WAGGLE_QUEUE", ".waggle_pending_events.jsonl"))


def post_event(url: str, device_key: str, event: dict, attempts: int = 3) -> bool:
    for attempt in range(attempts):
        try:
            response = requests.post(
                url,
                json=event,
                headers={"X-Device-Key": device_key},
                timeout=5,
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            if attempt + 1 < attempts:
                time.sleep(1 + attempt)
    return False


def read_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def write_queue(path: Path, events: list[dict]) -> None:
    if not events:
        path.unlink(missing_ok=True)
        return
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def flush_queue(url: str, device_key: str, queue_path: Path) -> int:
    pending = read_queue(queue_path)
    remaining = []
    for index, event in enumerate(pending):
        if not post_event(url, device_key, event):
            remaining.extend(pending[index:])
            break
    write_queue(queue_path, remaining)
    return len(pending) - len(remaining)


def queue_event(path: Path, event: dict) -> None:
    pending = read_queue(path)
    pending.append(event)
    write_queue(path, pending)


def deliver_event(
    event: dict,
    url: str = DEFAULT_URL,
    device_key: str = DEFAULT_KEY,
    queue_path: Path = DEFAULT_QUEUE,
) -> bool:
    """Flush queued records, then send or durably queue one model event."""
    flush_queue(url, device_key, queue_path)
    if post_event(url, device_key, event):
        return True
    queue_event(queue_path, event)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Waggle model olayını panele gönder")
    parser.add_argument("--hive", required=True, help="Kovan kimliği, örn. H4")
    parser.add_argument(
        "--status",
        required=True,
        choices=("NORMAL", "WATCH", "ALARM"),
    )
    parser.add_argument("--anomaly-fraction", required=True, type=float)
    parser.add_argument("--consecutive-anomalies", type=int, default=0)
    parser.add_argument("--source-file")
    # Which acoustic model decided this event. It is the first link in the chain a
    # report rests on, so an edge service should name it rather than leave it blank.
    parser.add_argument("--model", help="Kararı veren model dosyası, örn. H4.onnx")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--device-key", default=DEFAULT_KEY)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    args = parser.parse_args()

    if not 0 <= args.anomaly_fraction <= 1:
        parser.error("--anomaly-fraction 0 ile 1 arasında olmalı")
    if args.consecutive_anomalies < 0:
        parser.error("--consecutive-anomalies negatif olamaz")

    flushed = flush_queue(args.url, args.device_key, args.queue)
    if flushed:
        print(f"Bekleyen {flushed} olay gönderildi.")

    event = {
        "hive_id": args.hive,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": args.status,
        "anomaly_fraction": args.anomaly_fraction,
        "consecutive_anomalies": args.consecutive_anomalies,
        "source_file": args.source_file,
        "model": args.model,
    }
    if post_event(args.url, args.device_key, event):
        print(
            f"Olay gönderildi: {args.hive} / {args.status} / "
            f"anomaly_fraction={args.anomaly_fraction:.2f}"
        )
        return 0

    queue_event(args.queue, event)
    print(f"Bağlantı kurulamadı; olay çevrimdışı kuyruğa alındı: {args.queue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
