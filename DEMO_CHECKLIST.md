# Waggle demo checklist

## Before the presentation

- Pull the latest approved `main` branch.
- Turn off VPN and Wi-Fi once to verify the core offline flow before presentation day.
- Confirm Python dependencies are installed: `pip install -r requirements.txt`.
  `reportlab` is needed for the report PDF download and is easy to miss.
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

Open <http://127.0.0.1:8000> and sign in with `admin` / `waggle-demo`. The sign-in
screen shows those credentials while demo mode is on.

### The two accounts

`run_demo.py` turns demo mode on, which seeds `admin` as a demo owner. To show the panel
as a real beekeeper sees it, register a second account from **Sistem sahibi hesabı
oluştur** on the sign-in screen and sign in with that one instead.

| Account | What it is | Difference |
| --- | --- | --- |
| `admin` | Demo owner | Has the **Demo görünümü** switch; a new hive reads `%100 · İzleme etkin` after one recording |
| the one you register | Real owner | No switch; the hive shows its true enrollment progress |

Both accounts have the same powers. The demo account cannot sign in once
`WAGGLE_DEMO_MODE` is back to `0`.

## Presentation flow

1. Show the simple overview and status totals.
2. Open **Çayır Kovanı (H3)** and explain its persistent `ALARM` state.
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
12. In **Cihazlar ve model**, show the three enrollment thresholds as a checklist and point
    out that the day count is per calendar day — sending forty files in one afternoon still
    adds a single day.
13. Send several recordings at once: pick multiple files, or use **Cihazdan canlı dinle**
    to record from the microphone. Recordings are sent one by one with progress.
14. Flip the **Demo görünümü** switch to show the same hive as the server really has it.
15. In **Ayarlar → Ekip**, add a worker account and use **Çalışan gözüyle bak** to show the
    restricted panel a field worker gets.
16. Acknowledge an alarm and show that the record names the account that inspected the hive.

## Privacy and offline message

- Core hive monitoring, SQLite storage, alarms, and the local panel do not require internet.
- Online weather is optional and disabled by default.
- Enabling weather sends the configured latitude and longitude to Open-Meteo.
- The anomaly fraction is not a probability; the alarm requests inspection.
- Foundry Local and Phi generate the report on-device; the recorded generator preserves provenance.
- The local RAG knowledge base contains reviewed operational guidance only; recordings never enter it.

## Accounts and passwords

- The panel is offline, so there is no e-mail reset. Three ways back into an account:
  a **recovery code** generated in **Ayarlar → Kurtarma kodu** and used from
  **Parolamı unuttum** on the sign-in screen; the owner issuing a worker a new password
  from **Ayarlar → Ekip**; or, on the machine hosting the panel,
  `python -m tools.reset_password --username <name>`.
- A recovery code is shown once and works once. Generating a new one voids the old.
- A worker cannot do anything until they replace the temporary password the owner handed
  over — otherwise "who inspected this hive" would not name one person.
- Disabling a worker ends their open session immediately, not when their cookie expires.

## Known limits on demo day

- **Live microphone recording needs a secure connection.** It works on the panel machine
  at `127.0.0.1`, but browsers block the microphone over plain http, so it will not work
  on a phone reached through `--lan`. Record with Voice Memos there and use **Dosya
  yükle** instead.
- `run_demo.py` writes its sample events and the seeded demo account into the configured
  `WAGGLE_DB`. Point `WAGGLE_DB` at a scratch file if the real hive history must stay clean.

## Recovery

- If the page does not open, stop the command with Control+C and run it again.
- If port 8000 is busy, run `python tools/run_demo.py --port 8001`.
- If Foundry Local is unavailable, the report layer uses its labelled deterministic safety fallback.
- If the database should remain unchanged, start with `--no-seed`.
- Unsent edge events remain in `.waggle_pending_events.jsonl` and are retried later.
- If a change you just made is not on screen, the running server is still the old process:
  Python loads its modules at start-up, so stop it with Control+C and start it again, then
  hard-refresh the browser.
