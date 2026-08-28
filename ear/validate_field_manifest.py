"""

It validates the field metadata before audio enters the training pipeline

"""

from pathlib import Path

import argparse # taking value using the terminal
import csv

from datetime import datetime

import wave

REQUIRED = {
    "file", "session_id", "site_id", "hive_id", "timestamp_utc", "local_hour",
    "collection_phase", "recording_trigger", "inspection_outcome",
    "queen_state", "hours_since_state_change", "queen_confirmation",
    "device_id", "microphone_model", "microphone_position",
    "sample_rate_hz", "duration_seconds", "intervention_notes",
}

VALID_STATES = {"queenright", "queenless"}
VALID_PHASES = {"enrollment", "monitoring", "event"}
VALID_TRIGGERS = {"scheduled", "model_alarm", "manual_check", "intervention"}
VALID_INSPECTIONS = {"not_inspected", "queen_present", "queen_missing", "other_issue", "no_issue"}

# not inspected -> not checked
# queen present -> queen seen
# queen missing -> queen not found
# other_issue -> other issue found
# no_issue -> no issue found

def parse_args(): # It defines which of the following options can be provided to the manifest validation script from the terminal
    parser = argparse.ArgumentParser()

    parser.add_argument("manifest", type = Path)

    parser.add_argument("--require-files", action = "store_true")

    parser.add_argument(
        "--personalized-readiness", action = "store_true",
        help = "Fail unless every hive has 14 confirmed healthy enrollment days "
             "with repeated morning, midday, and evening coverage ",
    )

    return parser.parse_args()

# This is a validator that validates the manifest CSV file from beginning to end; it doesn't just check if columns exist but also verifies whether the values ​​make sense, whether the WAV files truly match the manifest and if desired whether each hive has enough data for personalized model training

def main():
    args = parse_args()

    errors, warnings = [], []

    with args.manifest.open(newline = "", encoding = "utf-8") as stream:
        reader = csv.DictReader(stream)

        fields = set(reader.fieldnames or [])

        missing = sorted(REQUIRED - fields)

        if missing:
            raise SystemExit("Missing columns: " + ", ".join(missing))

        rows = list(reader)

    if not rows:
        raise SystemExit("Manifest contains no recording rows")

    seen_files, seen_sessions = set(), set()

    hive_states = {}

    enrollment = {}

    hive_hardware = {}

    missing_environment = {}

    manifest_dir = args.manifest.parent

# hive_states -> What are the queen's states
# enrollment -> When were the healthy training records taken
# hive_hardware -> Which hardware was used
# missing_environment -> Which temperature or humidity data is missing

    for line, row in enumerate(rows, start = 2):
        prefix = f"line {line}"

        for field in REQUIRED:
            if not row[field].strip():
                errors.append(f"{prefix}: empty {field}")

        if row["file"] in seen_files:
            errors.append(f"{prefix}: duplicate file {row['file']}")

        seen_files.add(row["file"])

        if row["session_id"] in seen_sessions:
            errors.append(f"{prefix}: duplicate session_id {row['session_id']}")

        seen_sessions.add(row["session_id"])

        state = row["queen_state"].strip().lower()

        if state not in VALID_STATES:
            errors.append(f"{prefix}: invalid queen_state {state!r}")

        hive_states.setdefault(row["hive_id"], set()).add(state)

        phase = row["collection_phase"].strip().lower() # strip deletes which has at the start and end of the blanks

        trigger = row["recording_trigger"].strip().lower()

        if phase not in VALID_PHASES:
            errors.append(f"{prefix}: invalid collection_phase {phase!r}")

        if trigger not in VALID_TRIGGERS:
            errors.append(f"{prefix}: invalid recording_trigger {trigger!r}")

        inspection = row["inspection_outcome"].strip().lower()

        if inspection not in VALID_INSPECTIONS:
            errors.append(f"{prefix}: invalid inspection_outcome {inspection!r}")

        if trigger == "model_alarm" and inspection == "not_inspected":
            warnings.append(f"{prefix}: model alarm has not yet been inspected")

        try:
            timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))

            if timestamp.tzinfo is None:
                errors.append(f"{prefix}: timestamp_utc lacks timezone")

            elif (phase == "enrollment" and state == "queenright" and
                  row["queen_confirmation"].strip()):

                try:
                    hour = int(row["local_hour"])

                    if not 0 <= hour <= 23:
                        raise ValueError

                except ValueError:
                    errors.append(f"{prefix}: local_hour must be an integer from 0 to 23")

                    hour = -1

                bucket = ("morning" if 5 <= hour <= 10 else
                          "midday" if 11 <= hour <= 16 else
                          "evening" if 17 <= hour <= 22 else "night")

                enrollment.setdefault(row["hive_id"], []).append((timestamp.date(), bucket))

        except ValueError:
            errors.append(f"{prefix}: invalid ISO timestamp_utc")

        try:
            duration = float(row["duration_seconds"])

            if duration < 300:
                warnings.append(f"{prefix}: duration below recommended 300 seconds")

        except ValueError:
            errors.append(f"{prefix}: invalid duration_seconds")

        try:
            int(row["sample_rate_hz"])
            float(row["hours_since_state_change"])

            if not 0 <= int(row["local_hour"]) <= 23:
                raise ValueError

        except ValueError:
            errors.append(f"{prefix}: invalid numeric field")

        hardware = (row["device_id"], row["microphone_model"], row["microphone_position"])

        hive_hardware.setdefault(row["hive_id"], set()).add(hardware)

        for environmental_field in ("temperature_c", "humidity_pct"):
            value = row.get(environmental_field, "").strip()

            if not value:
                missing_environment.setdefault(row["hive_id"], set()).add(environmental_field)

            else:
                try:
                    float(value)

                except ValueError:
                    errors.append(f"{prefix}: invalid {environmental_field}")

        path = manifest_dir / row["file"]

        if args.require_files and not path.is_file():
            errors.append(f"{prefix}: missing audio file {path}")

        elif path.is_file() and path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as audio:
                    actual_rate = audio.getframerate()

                    actual_duration = audio.getnframes() / actual_rate

                if actual_rate != int(row["sample_rate_hz"]):
                    errors.append(f"{prefix}: WAV sample rate disagrees with manifest")

                if abs(actual_duration - float(row["duration_seconds"])) > 1.0:
                    errors.append(f"{prefix}: WAV duration disagrees with manifest")

            except wave.Error as exc:
                errors.append(f"{prefix}: unreadable WAV: {exc}")

    unpaired = sorted(hive for hive, states in hive_states.items() if states != VALID_STATES)

    if unpaired:
        warnings.append("hives missing one queen state: " + ", ".join(unpaired))

    if args.personalized_readiness:
        for hive in sorted(hive_states):
            observations = enrollment.get(hive, [])

            days = {day for day, _ in observations}

            bucket_days = {
                bucket: {day for day, value in observations if value == bucket}
                for bucket in ("morning", "midday", "evening")
            }

            if len(days) < 14:
                errors.append(f"{hive}: only {len(days)}/14 healthy enrollment days")

            for bucket, covered in bucket_days.items():
                if len(covered) < 7:
                    errors.append(f"{hive}: only {len(covered)}/7 {bucket} enrollment days")

            if len(hive_hardware.get(hive, set())) != 1:
                errors.append(f"{hive}: device, microphone, or position changed during collection")

            if missing_environment.get(hive):
                errors.append(f"{hive}: missing environmental values: " +
                              ", ".join(sorted(missing_environment[hive])))

            print(f"READINESS {hive}: days={len(days)} "
                  f"morning = {len(bucket_days['morning'])} "
                  f"midday = {len(bucket_days['midday'])} "
                  f"evening = {len(bucket_days['evening'])}")

    print(f"rows={len(rows)} hives={len(hive_states)} paired_hives={len(hive_states)-len(unpaired)}")

    for warning in warnings:
        print("WARNING:", warning)

    if errors:
        for error in errors:
            print("ERROR:", error)

        raise SystemExit(f"Validation failed with {len(errors)} error(s)")

    print("Validation passed")

if __name__ == "__main__":
    main()