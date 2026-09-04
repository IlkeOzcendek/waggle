from __future__ import annotations

import argparse
import os
import random
import time
from datetime import datetime, timezone

import requests


def event() -> dict[str, object]:
    roll = random.random()
    status = "ALARM" if roll < 0.23 else "WATCH" if roll < 0.33 else "NORMAL"
    anomaly_fraction = random.uniform(.85, 1.0) if status == "ALARM" else random.uniform(.35, .8) if status == "WATCH" else random.uniform(0, .2)
    # The ranges are the ones the packaged profile actually produces: about .05 across a
    # healthy stretch of the published recording and about .37 across the queen-loss
    # stretch, peaking at .47. A demo that invented the scale would teach the wrong one.
    anomaly_severity = random.uniform(.30, .47) if status == "ALARM" else random.uniform(.12, .30) if status == "WATCH" else random.uniform(.02, .10)
    hive_id = random.choice(["H1", "H2", "H3"])
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "hive_id": hive_id,
        "timestamp": moment.isoformat(),
        "status": status,
        "anomaly_fraction": round(anomaly_fraction, 2),
        "anomaly_severity": round(anomaly_severity, 2),
        "consecutive_anomalies": 30 if status == "ALARM" else 5 if status == "WATCH" else 0,
        "source_file": f"phone:{hive_id.lower()}-{moment:%Y%m%d-%H%M}.wav",
        "model": "mendeley_isolation_monitor.onnx",
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
        print(f"{payload['hive_id']} -> {payload['status']} ({payload['anomaly_fraction']:.0%} aykırı)")
        sent += 1
        if not args.count or sent < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
