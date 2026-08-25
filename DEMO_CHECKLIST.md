# Waggle demo checklist

## Before the presentation

- Pull the latest approved `main` branch.
- Confirm Python dependencies are installed in `.venv`.
- Close any process already using port 8000.
- Keep the device key private outside local demos.
- Run `python -m unittest discover -s panel/tests -v`.

## Start the demo

```bash
source .venv/bin/activate
python tools/run_demo.py
```

Open <http://127.0.0.1:8000> and sign in with `admin` / `waggle-demo`.

## Presentation flow

1. Show the simple overview and status totals.
2. Open **Deneme Kovanı (H3)** and explain the 91% queenless suspicion.
3. Show its confidence chart and event history.
4. Open **Alarmlar** and acknowledge the H3 alarm.
5. Open **Raporlar** and show the weekly AI recommendations.
6. Open **Kovanlarım** and explain automatic device identifiers.
7. Optionally add a new hive and show its initial **Veri yok** state.
8. Explain that the real audio model sends the same event JSON through the device client.

## Recovery

- If the page does not open, stop the command with Control+C and run it again.
- If port 8000 is busy, run `python tools/run_demo.py --port 8001`.
- If the database should remain unchanged, start with `--no-seed`.
- Unsent edge events remain in `.waggle_pending_events.jsonl` and are retried later.
