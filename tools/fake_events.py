from __future__ import annotations

import argparse
import os
import random
import time
from datetime import datetime, timezone

import requests


def event() -> dict[str, object]:
    roll = random.random()
    event_type = "queenless_suspected" if roll < 0.23 else "uncertain" if roll < 0.33 else "healthy"
    return {
        "hive_id": random.choice(["H1", "H2", "H3"]),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "event": event_type,
        "confidence": round(random.uniform(.82, .97) if event_type == "queenless_suspected" else random.uniform(.60, .96), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Waggle paneline sahte kovan olayları gönderir.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/events")
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--count", type=int, default=0, help="0 verilirse durdurulana kadar çalışır")
    parser.add_argument("--device-key", default=os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"))
    args = parser.parse_args()

    sent = 0
    while not args.count or sent < args.count:
        payload = event()
        response = requests.post(
            args.url,
            json=payload,
            headers={"X-Device-Key": args.device_key},
            timeout=5,
        )
        response.raise_for_status()
        print(f"{payload['hive_id']} -> {payload['event']} ({payload['confidence']:.0%})")
        sent += 1
        if not args.count or sent < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
