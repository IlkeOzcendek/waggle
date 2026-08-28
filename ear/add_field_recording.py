"""

It safely gets one WAV recording and append its measured metadata

"""

from pathlib import Path

import argparse # taking value using the terminal
import csv

from datetime import datetime, timezone

import shutil # For being able to make high level operations related to files and folders
import wave

FIELDS = [
    "file", "session_id", "site_id", "hive_id", "timestamp_utc", "local_hour",
    "collection_phase", "recording_trigger", "queen_state",
    "hours_since_state_change", "queen_confirmation", "inspection_outcome",
    "device_id", "microphone_model", "microphone_position", "sample_rate_hz",
    "duration_seconds", "temperature_c", "humidity_pct", "weather",
    "intervention_notes",
]

def arguments(): # Collecting the needed information here
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("wav", type = Path)

    parser.add_argument("--field-dir", type = Path, default = Path("data/field"))

    parser.add_argument("--timestamp", required = True, help = "ISO-8601 with timezone")

    parser.add_argument("--site", required = True)
    parser.add_argument("--hive", required = True)
    parser.add_argument("--device", required = True)
    parser.add_argument("--microphone", required = True)
    parser.add_argument("--position", required = True)
    parser.add_argument("--temperature", required = True, type = float)
    parser.add_argument("--humidity", required = True, type = float)

    parser.add_argument("--phase", choices = ("enrollment", "monitoring", "event"), default = "enrollment")

    parser.add_argument("--trigger", choices = ("scheduled", "model_alarm", "manual_check", "intervention"), default = "scheduled")

    parser.add_argument("--queen-state", choices = ("queenright", "queenless"), default = "queenright")

    parser.add_argument("--hours-since-change", type = float, default = 0.0)
    parser.add_argument("--confirmation", default = "visual_inspection")

    parser.add_argument("--inspection", choices = ("not_inspected", "queen_present", "queen_missing", "other_issue", "no_issue"), default="not_inspected")

    parser.add_argument("--weather", default = "")
    parser.add_argument("--notes", default = "none")

    return parser.parse_args()

def safe_token(value): # It cleans up the names entered such as site/hive/device names and converts them into a safe name format
    token = "".join(c if c.isalnum() or c in "-_" else "-" for c in value.strip())

    if not token:
        raise SystemExit("site, hive and device identifiers cannot be empty")
    return token

def main():
    args = arguments()

    if not args.wav.is_file() or args.wav.suffix.lower() != ".wav":
        raise SystemExit(f"Not a WAV file: {args.wav}")

    try:
        timestamp = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))

    except ValueError as exc:
        raise SystemExit("--timestamp must be valid ISO-8601") from exc

    if timestamp.tzinfo is None:
        raise SystemExit("--timestamp must include a timezone")

    if not 0 <= args.humidity <= 100:
        raise SystemExit("--humidity must be between 0 and 100")

    with wave.open(str(args.wav), "rb") as audio:
        if audio.getnchannels() != 1:
            raise SystemExit("WAV must be mono")

        rate = audio.getframerate()

        duration = audio.getnframes() / rate

        if audio.getsampwidth() != 2:
            raise SystemExit("WAV must use 16-bit PCM")

    site, hive, device = map(safe_token, (args.site, args.hive, args.device))

    utc = timestamp.astimezone(timezone.utc)

    stamp = utc.strftime("%Y-%m-%dT%H%M%SZ")

    session = f"{site}_{hive}_{stamp}_{device}"

    destination_name = f"{session}_{args.queen_state}.wav"

    args.field_dir.mkdir(parents = True, exist_ok = True)

    destination = args.field_dir / destination_name

    manifest = args.field_dir / "manifest.csv"

    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")

    rows = []
    if manifest.exists():

        with manifest.open(newline = "", encoding = "utf-8") as stream:
            reader = csv.DictReader(stream)

            if reader.fieldnames != FIELDS:
                raise SystemExit("Existing manifest columns do not match current template")

            rows = list(reader)

        if any(row["session_id"] == session for row in rows):
            raise SystemExit(f"Session already exists: {session}")

    row = {
        "file": destination_name, "session_id": session, "site_id": site,
        "hive_id": hive, "timestamp_utc": utc.isoformat().replace("+00:00", "Z"),
        "local_hour": str(timestamp.hour),
        "collection_phase": args.phase, "recording_trigger": args.trigger,
        "queen_state": args.queen_state,
        "hours_since_state_change": f"{args.hours_since_change:g}",
        "queen_confirmation": args.confirmation, "inspection_outcome": args.inspection,
        "device_id": device, "microphone_model": args.microphone,
        "microphone_position": args.position, "sample_rate_hz": str(rate),
        "duration_seconds": f"{duration:.3f}", "temperature_c": f"{args.temperature:g}",
        "humidity_pct": f"{args.humidity:g}", "weather": args.weather,
        "intervention_notes": args.notes,
    }

    # ** Copies first and then atomically replace the manifest so it never references a missing recording. Existing recordings are never overwritten **

    shutil.copy2(args.wav, destination)

    temporary = manifest.with_suffix(".csv.tmp")

    try:
        with temporary.open("w", newline = "", encoding = "utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames = FIELDS)

            writer.writeheader(); writer.writerows(rows); writer.writerow(row)

        temporary.replace(manifest)

    except Exception:
        destination.unlink(missing_ok = True)
        temporary.unlink(missing_ok = True)

        raise

    print(f"recording = {destination}")
    print(f"manifest = {manifest}")
    print(f"session_id = {session}")

if __name__ == "__main__":
    main()