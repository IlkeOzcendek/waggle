#!/usr/bin/env python3
"""Start a complete local Waggle demo with sample data."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

def wait_for_server(base_url: str, process: subprocess.Popen, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Panel sunucusu başlatılamadı")
        try:
            if requests.get(f"{base_url}/api/health", timeout=1).ok:
                return
        except requests.RequestException:
            time.sleep(.25)
    raise RuntimeError("Panel zamanında hazır olmadı")


def seed_demo(base_url: str, device_key: str) -> None:
    headers = {"X-Device-Key": device_key}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scenarios = [
        ("H1", "healthy", .92),
        ("H2", "uncertain", .66),
        ("H3", "queenless_suspected", .91),
    ]
    for hive_id, event_type, confidence in scenarios:
        payload = {
            "hive_id": hive_id,
            "timestamp": now.isoformat(),
            "event": event_type,
            "confidence": confidence,
        }
        response = requests.post(
            f"{base_url}/api/events", json=payload, headers=headers, timeout=5
        )
        response.raise_for_status()

    report = {
        "period_start": (now - timedelta(days=7)).isoformat(),
        "period_end": now.isoformat(),
        "summary": "H1 düzenli görünüyor. H2 için ek dinleme öneriliyor. H3'te yüksek güvenli ana arı kaybı şüphesi tespit edildi.",
        "recommendations": [
            "H3 kovanını 24 saat içinde fiziksel olarak kontrol edin.",
            "H2 için yeni bir ses kaydı alın.",
            "H1 için rutin takibe devam edin.",
        ],
        "hive_ids": ["H1", "H2", "H3"],
    }
    response = requests.post(
        f"{base_url}/api/reports", json=report, headers=headers, timeout=5
    )
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Waggle yerel demosunu tek komutla başlat")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-seed", action="store_true", help="Örnek veri gönderme")
    args = parser.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    device_key = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "panel.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
    ]
    process = subprocess.Popen(command)
    try:
        wait_for_server(base_url, process)
        if not args.no_seed:
            seed_demo(base_url, device_key)
        print("\n🐝 Waggle demo hazır")
        print(f"Panel: {base_url}")
        print("Kullanıcı adı: admin")
        print("Parola: waggle-demo")
        print("Durdurmak için Control+C\n")
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
