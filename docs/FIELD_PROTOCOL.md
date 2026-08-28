# Field recording protocol

## Purpose

This protocol describes how to enroll and monitor one hive with Waggle while
reducing changes caused by recording hardware, placement, time and weather.
Waggle detects persistent deviation from a hive's learned healthy acoustic
profile. It does not diagnose queen death by sound alone.

Queen handling and hive inspection must be performed by an experienced
beekeeper in accordance with colony welfare practices and local regulations.

## Healthy enrollment

1. Record the hive for at least 14 days before enabling alarms.
2. Collect at least 42 confirmed healthy sessions: morning, afternoon and
   evening recordings distributed across the enrollment period.
3. Record each session for 5 – 10 minutes.
4. Have a beekeeper confirm that the queen is present during enrollment.
5. Keep the device, microphone, gain, position and orientation unchanged.
6. Restart enrollment if the recording hardware or placement changes.

The development override in the profile building tool may be used for software
demonstrations but a profile created with insufficient enrollment data must
not be treated as field validated.

## Recording standard

- Lossless WAV
- Mono
- 16 - bit PCM
- Preferably 16 kHz sample rate
- Automatic gain control, noise suppression and speech enhancement disabled
- Original recording retained without destructive editing

Note speech, hive opening, physical contact, rain, machinery or other unusual
noise during a recording

## Required metadata

Each recording must identify:

- Site, hive, session and device
- UTC timestamp and local hour
- Microphone model and fixed position
- Temperature and humidity when sensors are available
- Collection phase: `enrollment` or `monitoring`
- Beekeeper inspection result

Use one manifest row per continuous recording. Short analysis windows derived
from the same session are not independent field samples

## Add and validate a recording

Use the ingestion tool instead of renaming files or editing the manifest by
hand:

```bash
python ear/add_field_recording.py healthy.wav \
  --field-dir data/field \
  --timestamp 2026-09-14T12:00:00+03:00 \
  --site SITE01 --hive HIVE03 --device DEV01 \
  --microphone "microphone-model" --position "fixed-position" \
  --temperature 25 --humidity 60 --inspection queen_present
```

Validate the manifest and enrollment readiness:

```bash
python ear/validate_field_manifest.py data/field/manifest.csv \
  --require-files --personalized-readiness
```

## Monitoring and inspection

Use a separate profile and state file for each hive. After an alarm, inspect
the colony and record one of these outcomes: `queen_present`, `queen_missing`,
`other_issue` or `no_issue`.

An alarm means that a persistent acoustic change compatible with queen loss
was detected. Disease, swarming, weather, external noise, microphone movement
and other colony stresses can produce similar changes. The required action is
to check the hive and queen not to assume a confirmed diagnosis.
