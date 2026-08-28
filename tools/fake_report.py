from __future__ import annotations

from datetime import datetime, timedelta

import requests


def main() -> None:
    period_end = datetime.now().replace(microsecond=0)
    payload = {
        "period_start": (period_end - timedelta(days=7)).isoformat(),
        "period_end": period_end.isoformat(),
        "summary": "H1 düzenli görünüyor. H2 için ek dinleme öneriliyor. H3'te yüksek güvenli ana arı kaybı şüphesi tespit edildi.",
        "recommendations": [
            "H3 kovanını 24 saat içinde fiziksel olarak kontrol edin.",
            "H2 için yeni bir ses kaydı alın ve eğilimi izleyin.",
            "H1 için rutin takibe devam edin.",
        ],
        "hive_ids": ["H1", "H2", "H3"],
    }
    response = requests.post("http://127.0.0.1:8000/api/reports", json=payload, timeout=5)
    response.raise_for_status()
    print(f"Rapor oluşturuldu: #{response.json()['id']}")


if __name__ == "__main__":
    main()
