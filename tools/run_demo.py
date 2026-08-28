#!/usr/bin/env python3
"""Start a complete local Waggle demo with sample data."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests


def local_network_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses suitable for a nearby phone."""
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return sorted({address for address in addresses if not address.startswith("127.")})

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


def seed_demo(base_url: str, device_key: str, include_report: bool = True) -> None:
    headers = {"X-Device-Key": device_key}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scenarios = [
        ("H1", "NORMAL", .08, 0),
        ("H2", "WATCH", .66, 5),
        ("H3", "ALARM", 1.0, 30),
    ]
    for hive_id, status, anomaly_fraction, consecutive_anomalies in scenarios:
        payload = {
            "hive_id": hive_id,
            "timestamp": now.isoformat(),
            "status": status,
            "anomaly_fraction": anomaly_fraction,
            "consecutive_anomalies": consecutive_anomalies,
            "source_file": "demo.wav",
        }
        response = requests.post(
            f"{base_url}/api/events", json=payload, headers=headers, timeout=5
        )
        response.raise_for_status()

    if not include_report:
        return
    report = {
        "period_start": (now - timedelta(days=7)).isoformat(),
        "period_end": now.isoformat(),
        "summary": "H1 düzenli görünüyor. H2 izleme durumunda. H3'te kalıcı akustik değişim alarmı oluştu.",
        "recommendations": [
            "H3 kovanını 24 saat içinde fiziksel olarak kontrol edin.",
            "H2 için yeni bir ses kaydı alın.",
            "H1 için rutin takibe devam edin.",
        ],
        "hive_ids": ["H1", "H2", "H3"],
        "language": "tr",
        "generator": "deterministic-demo",
    }
    response = requests.post(
        f"{base_url}/api/reports", json=report, headers=headers, timeout=5
    )
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Waggle yerel demosunu tek komutla başlat")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-seed", action="store_true", help="Örnek veri gönderme")
    parser.add_argument(
        "--foundry",
        action="store_true",
        help="Sahte rapor yerine Phi ile Türkçe ve İngilizce rapor üret",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Paneli aynı güvenilir yerel ağdaki telefonlara aç",
    )
    args = parser.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    device_key = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "panel.app.main:app",
        "--host",
        host,
        "--port",
        str(args.port),
    ]
    process = subprocess.Popen(command)
    try:
        wait_for_server(base_url, process)
        if not args.no_seed:
            seed_demo(base_url, device_key, include_report=not args.foundry)
            if args.foundry:
                for language in ("tr", "en"):
                    subprocess.run(
                        [
                            sys.executable, "-m", "brain.foundry_report",
                            "--language", language,
                            "--panel-url", f"{base_url}/api/reports",
                            "--device-key", device_key,
                        ],
                        check=True,
                    )
        print("\n🐝 Waggle demo hazır")
        print(f"Panel: {base_url}")
        print("Kullanıcı adı: admin")
        print("Parola: waggle-demo")
        if args.lan:
            addresses = local_network_addresses()
            if addresses:
                print("Telefon adresi:")
                for address in addresses:
                    print(f"  http://{address}:{args.port}")
            else:
                print("Telefon adresi bulunamadı; FIELD_PHONE.md içindeki adımları izleyin.")
            print("UYARI: --lan modunu yalnızca güvendiğiniz yerel ağda kullanın.")
        print("Sunum akışı: PRESENTATION_GUIDE.md")
        print("Kontrol listesi: DEMO_CHECKLIST.md")
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
