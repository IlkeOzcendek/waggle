from __future__ import annotations

import argparse
import random
import time
from datetime import datetime

import requests


def event() -> dict[str, object]:
    roll = random.random()
    event_type = "queenless_suspected" if roll < 0.23 else "uncertain" if roll < 0.33 else "healthy"
    return {
        "hive_id": random.choice(["H1", "H2", "H3"]),
        "timestamp": datetime.now().replace(microsecond=0).isoformat(),
        "event": event_type,
        "confidence": round(random.uniform(.82, .97) if event_type == "queenless_suspected" else random.uniform(.60, .96), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Waggle paneline sahte kovan olayları gönderir.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/events")
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--count", type=int, default=0, help="0 verilirse durdurulana kadar çalışır")
    args = parser.parse_args()

    sent = 0
    while not args.count or sent < args.count:
        payload = event()
        response = requests.post(args.url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"{payload['hive_id']} -> {payload['event']} ({payload['confidence']:.0%})")
        sent += 1
        if not args.count or sent < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
