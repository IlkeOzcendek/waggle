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
| `admin` | Demo owner | Has the **Demo görünümü** switch (hidden until you hover it, so it stays off camera); a new hive reads `%100 · İzleme etkin` after one recording |
| the one you register | Real owner | No switch; the hive shows its true enrollment progress |

Both accounts have the same powers. `admin` signs in whether or not demo mode is on;
while demo mode is off, start-up warns that it still carries the well-known password.
Changing that password from **Ayarlar → Hesap güvenliği** clears the warning and turns it
into an ordinary owner account.

### Usernames are matched exactly

A username is an identifier, not a word: `İlke`, `ilke` and `Ilke` are three different
accounts, and so are `Ali` and `ALi`. Type the name exactly as it was registered — this is
the single most likely reason a sign-in fails on demo day.

Check which names exist before you present:

```bash
python -m tools.reset_password
```

It lists the accounts without changing anything.

## Presentation flow

1. Show the simple overview and status totals.
2. Open **Çayır Kovanı (H3)** and explain its persistent `ALARM` state.
3. Show its acoustic-change chart and event history.
4. Open **Alarmlar** and acknowledge the H3 alarm. Point at the **YEREL KILAVUZ** block
   under the card: the reviewed notes that fit this alarm, by id. No model is involved —
   the retrieval is local and deterministic, so it works with the local LLM switched off.
5. Open **Raporlar** and show the locally generated Turkish and English AI recommendations.
   Explain that the report is grounded with version-controlled local guidance and
   that retrieved source IDs remain in the assessment record. The **Ölçüm modeli** line in
   the metric strip names the ONNX profile that measured the period, and the provenance
   line gives the whole chain: `ONNX → SQLite → RAG → Foundry Local`. The model that wrote
   the report is the end of that chain, not the start of it.
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
    The switch is invisible until the pointer is on it — it sits in the header between
    the connection label and the **EN** button, so hover there to bring it up.
15. In **Ayarlar → Ekip**, add a worker account and use **Çalışan gözüyle bak** to show the
    restricted panel a field worker gets.
16. Acknowledge an alarm and show that the record names the account that inspected the hive.
17. In **Raporlar**, open **Bu değerlendirme neye dayanıyor** in the right column: it lists
    the exact guidance notes the assessment was grounded in, with their text. The panel used
    to show only a source count.
18. If a second model is configured, point at the line under **Hazırlayan**: green when the
    two local models reached the same decision, amber when they disagreed and the more
    cautious reading was kept.
19. Show the **MODEL KARARI** panel: priority, the pattern identified, whether the change is
    compatible with queen loss, whether a physical inspection is required, and the action
    codes. The summary is what the model *said*; this panel is what it *decided*.
20. Press **Yeni rapor üret** and let the report be generated on-device in front of the room.
    It needs `WAGGLE_LLM_ENABLED=1`; with the flag off the button still works and produces
    the deterministic report, and the panel labels it as such.
21. Download the PDF. The model decision, the cross-check outcome, the text of the guidance
    notes and the account that inspected each hive are all in it — the shared document
    carries the reasoning, not only the conclusion.
22. Open **Ayarlar → Yerel kılavuz**: all 28 notes with their tags and a search box. The
    box runs the same retriever a report is grounded with, not a substring filter — type
    "varroa" and the autumn note comes first. The screen where the base can be inspected
    ranks passages the way the retrieval it explains ranks them.
23. In **Dışa Aktar**, show the four datasets added since the first version — **Saha
    doğrulamaları** (who inspected which hive, when, and what they found), **Yerel kılavuz
    tabanı** (the notes themselves), **Öğrenme kayıtları** and **Cihazlar**.
24. **Öğrenme kayıtları** is the one to dwell on if anyone doubts the learning claim: one
    row per recording, with the calendar day it landed on and whether it was confirmed
    healthy. That is exactly what the 42-recording, 14-day threshold counts, so the
    percentage on the hive card can be recomputed from the file. The audio is not in it —
    it is deleted after feature extraction — and neither are the feature vectors.
25. In the telemetry table of a hive detail, press **Kılavuz** on a `WATCH` row. A watch
    record is where "should I act?" is actually open, and the notes that fit it open under
    the row. Same endpoint as the alarm cards, same no-model path.
26. Open **Sistem Durumu** and show the **Akustik model (ONNX)** card. The panel checks that
    the packaged model and every monitored hive's own profile are still on disk, and reads
    the recorded decision comparison: `referans modelde 5400 satırda karar eşleşmesi
    doğrulandı` — the ONNX conversion did not change a single decision against the joblib
    model it came from. The number comes from `results/mendeley_onnx_parity.json`.
27. Per-hive profiles carry the same comparison, made at training time and stored with the
    profile: `N/M kovan profili karar eşleşmesiyle doğrulandı`. Training refuses to publish
    a profile whose decisions differ, so a hive only reaches monitoring behind a model whose
    conversion was checked. Delete a model file and the card turns to a warning naming the
    hive.

## The AI layer, in one paragraph

Events go to a local model through Microsoft Agent Framework, which returns one of three
priorities. Before that call, the panel selects grounding notes from **28 reviewed local
guidance entries** — and it selects on the facts of the period, not on the status label:
the anomaly fraction, the length of the anomalous run, how many hives changed at once, and
the calendar month. An alarm in May brings up swarm preparation; the same alarm in December
brings up the winter cluster. A seasonal note is always given one of the slots.

Whatever the model returns is checked before it is used: the priority must be one of the
three allowed tokens, and prose that invents a hive or asserts a diagnosis is thrown away
in favour of the deterministic template. If the model is unreachable the deterministic
engine produces the report, and the panel says so.

The same retriever answers outside reports too — per alarm card, per `WATCH` row in the
telemetry table, and behind the guidance search box. None of those calls a model, so the
guidance is there on a panel whose local LLM is switched off.

### Where the chain starts

Every event records the ONNX model file that decided it, so a report can name the model that
*measured* it and not only the one that phrased it. That is what the **Ölçüm modeli** line on
the Reports page and the row in the PDF are reading, and it is why the provenance line says
`ONNX → SQLite → RAG → Foundry Local`. The conversion itself is evidenced: exporting to ONNX
compares both models' decisions on the same data and refuses to write a model that differs —
zero differences over 5400 rows on the reference model, and the same check at training time
for each hive's own profile, stored with it. **Sistem Durumu** shows both.

### Two models, when configured

`WAGGLE_CROSS_CHECK_MODEL` names a second local model. It is asked the same question, and
if the two disagree the more cautious priority wins — under-calling an alarm costs a
colony, over-calling one costs an inspection. It adds roughly two seconds and can never
fail the report: if the second model is missing or errors, the first assessment stands.

### Agent tools

The agent can call `period_overview`, `hive_history` and `look_up_guidance` — all read-only.
Whether it does depends on the model: Foundry reports tool support per model, and the panel
attaches the tools only to a model that has it. `phi-3.5-mini` does not, so with the default
model the agent works from the prepared prompt. Say "tool support is detected per model",
not "the agent uses tools".

## Generating a report during the demo

`WAGGLE_LLM_ENABLED=1` lets the **Yeni rapor üret** button call the local model; `run_demo.py
--foundry` sets it. Without it the button produces the deterministic report instead — which
is a fine thing to show, but say which one you are showing.

`WAGGLE_CROSS_CHECK_MODEL=qwen2.5-1.5b` adds the second opinion. Both belong in `.env`, which
is not committed.

What the second model actually does, measured on this hardware: on a week of rising WATCH
records `phi-3.5-mini` answered *routine* and `qwen2.5-1.5b` answered *watch*, so the
cautious reading won — the second model caught the first under-calling a developing change,
which is the whole reason it is there. On a week that already contains an ALARM, qwen tends
to echo the status back instead of deciding, the answer is rejected, and the log says so;
nothing is lost, because an ALARM is forced to *immediate* by a deterministic rule anyway.
So: expect the cross-check line on ambiguous weeks, not on alarming ones.

**Generating takes three to five minutes on this machine**, not seconds — measured, with
both languages and the cross-check. Press the button as you *enter* the Reports section and
talk through the guidance card, the model-decision panel and the export section while it
runs; the status line shows the elapsed time and says when it stalls. Do not stand and wait
for it. The reports already in the database are there to be shown meanwhile.

## Privacy and offline message

- Core hive monitoring, SQLite storage, alarms, and the local panel do not require internet.
- Online weather is optional and disabled by default.
- Enabling weather sends the configured latitude and longitude to Open-Meteo.
- The anomaly fraction is not a probability; the alarm requests inspection.
- Foundry Local and Phi generate the report on-device; the recorded generator preserves provenance.
- The local guidance base holds 28 reviewed operational notes only; recordings never enter it.
- Every dataset behind the panel can be exported, including the guidance base the model was
  given and the field inspections people recorded.

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
- Changing a password ends every other session opened with the old one — the phone it was
  signed in on, the borrowed laptop — but not the session you changed it from. The same is
  true of a reset the owner issues and of a recovery code, which is the point of both.
- **The first start after this change signs everyone out once.** Cookies issued earlier do
  not carry the marker the panel now checks. Sign in again; it happens only once.

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
