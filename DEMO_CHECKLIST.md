# Waggle demo checklist

## Before the presentation

- Pull the latest approved `main` branch.
- Turn off VPN and Wi-Fi once to verify the core offline flow before presentation day.
- Confirm Python dependencies are installed in `.venv311`.
- Copy `.env.example` to `.env` and configure secrets outside local demos.
- Close any process already using port 8000.
- Keep the device key private outside local demos.
- Run `python -m unittest discover -s panel/tests -v`.
- Keep [`PRESENTATION_GUIDE.md`](PRESENTATION_GUIDE.md) open on a phone or a second screen.

## Start the demo

```bash
source .venv311/bin/activate
python tools/run_demo.py --foundry
```

Open <http://127.0.0.1:8000> and sign in with `admin` / `waggle-demo`.

## Presentation flow

1. Show the simple overview and status totals.
2. Open **Deneme Kovanı (H3)** and explain its persistent `ALARM` state.
3. Show its acoustic-change chart and event history.
4. Open **Alarmlar** and acknowledge the H3 alarm.
5. Open **Raporlar** and show the locally generated Turkish and English AI recommendations.
   Explain that the report is grounded with version-controlled local guidance and
   that retrieved source IDs remain in the assessment record.
6. Use the **TR / EN** control to switch the whole interface and preferred report language.
7. Open **Kovanlarım → Cihazlar ve model** and show the phone/device relationship.
8. Add a new hive and show `Cihaz bekleniyor → Öğrenme devam ediyor`; explain the
   42-session / 14-day / 4-field-confirmation gate and that enrollment cannot generate alarms.
9. Show H3 as the pre-enrolled demo profile. Its phone/WAV input uses ONNX and sends
   the same event JSON through the panel pipeline.
10. Explain that raw enrollment audio is deleted after 21-feature extraction and
    that SQLite stores the compact learning and event records.
11. Show that online weather is disabled by default and requires explicit user consent.

## Privacy and offline message

- Core hive monitoring, SQLite storage, alarms, and the local panel do not require internet.
- Online weather is optional and disabled by default.
- Enabling weather sends the configured latitude and longitude to Open-Meteo.
- The anomaly fraction is not a probability; the alarm requests inspection.
- Foundry Local and Phi generate the report on-device; the recorded generator preserves provenance.
- The local RAG knowledge base contains reviewed operational guidance only; recordings never enter it.

## Recovery

- If the page does not open, stop the command with Control+C and run it again.
- If port 8000 is busy, run `python tools/run_demo.py --port 8001`.
- If Foundry Local is unavailable, the report layer uses its labelled deterministic safety fallback.
- If the database should remain unchanged, start with `--no-seed`.
- Unsent edge events remain in `.waggle_pending_events.jsonl` and are retried later.
- If live interaction fails, use previously captured panel screenshots while explaining the same flow.
