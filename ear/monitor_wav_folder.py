"""

It is a process of new WAV files for one hive and append an auditable event log

"""

from pathlib import Path

import argparse # taking value using the terminal
import csv

from datetime import datetime, timezone

import hashlib
import json
import os
import sys
import time

import numpy as np

from wav_isolation_monitor import update_run, wav_features
from model_runtime import load_monitor, severity_profile, window_decisions

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.send_event import deliver_event  # noqa: E402

LOG_FIELDS = [
    "processed_at_utc", "hive_id", "wav", "sha256", "windows",
    # How far the anomalous windows fell outside the profile, beside how many of them did.
    "anomaly_fraction", "anomaly_severity", "peak_severity",
    "initial_run", "final_run", "maximum_run", "status",
]

def arguments(): # follow the WAV files using the trained model
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("model", type = Path)
    parser.add_argument("folder", type = Path)
    parser.add_argument("--state", type = Path, required = True)
    parser.add_argument("--log", type = Path, required = True)
    parser.add_argument("--watch", action = "store_true", help = "Keep polling for new WAV files")

    parser.add_argument("--poll-seconds", type = float, default = 5.0)
    parser.add_argument("--panel-url", help="Panel /api/events address")
    parser.add_argument("--panel-hive", help="Panel hive id, for example H3")
    parser.add_argument(
        "--device-key",
        default = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"),
    )
    parser.add_argument(
        "--panel-queue",
        type = Path,
        default = Path(".waggle_pending_events.jsonl"),
    )

    return parser.parse_args()

def digest(path): # calc SHA 256 that is a digital fingerprint
    value = hashlib.sha256()

    with path.open("rb") as stream:

        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)

    return value.hexdigest()

def load_state(path, hive_id): # It loads the hive's previous monitoring state from a file
    if not path.exists():
        return {"hive_id": hive_id, "consecutive_anomalies": 0, "processed_files": []}

    state = json.loads(path.read_text(encoding = "utf-8"))

    if state.get("hive_id") != hive_id:
        raise SystemExit("!* State file belongs to a different hive profile *!")

    state.setdefault("processed_files", [])

    return state

def save_json_atomic(path, value): # It saves the Python data to a JSON file in an atomic, safe way
    path.parent.mkdir(parents = True, exist_ok = True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(json.dumps(value, indent = 2) + "\n", encoding = "utf-8")

    temporary.replace(path)

def existing_fields(path): # It reads back the header a log was started with so a new column cannot shift every later row out of line
    if not path.exists():
        return None

    with path.open("r", newline = "", encoding = "utf-8") as stream:
        header = next(csv.reader(stream), None)

    return header or None

def append_log(path, row): # It adds the result of an operation as a new line to a CSV log file
    path.parent.mkdir(parents = True, exist_ok = True)

    # A log written before severity existed keeps its own columns. Appending today's wider
    # row under yesterday's header would silently misalign the file for whoever reads it.
    fields = existing_fields(path)

    with path.open("a", newline = "", encoding = "utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames = fields or LOG_FIELDS, extrasaction = "ignore")

        if fields is None:
            writer.writeheader()

        writer.writerow(row)

def scan(
    artifact,
    folder,
    state_path,
    log_path,
    panel_url=None,
    panel_hive=None,
    device_key="waggle-device-demo",
    panel_queue=Path(".waggle_pending_events.jsonl"),
): # It scans .wav files in a folder, performs anomaly checks using the trained model and records the results in a state file and a CSV log

    # artifact -> the model package we saved earlier
    # folder -> the folder containing the WAV files
    # state_path -> the JSON file that holds the system's current state
    # log_path -> the CSV file where the results are written

    hive_id = artifact.get("hive_id")
    state = load_state(state_path, hive_id)
    processed = set(state["processed_files"])

    count = 0

    for path in sorted(folder.glob("*.wav"), key = lambda item: (item.stat().st_mtime_ns, item.name)):

        checksum = digest(path)

        file_key = f"{path.name}:{checksum}"

        if file_key in processed:
            continue

        values, names = wav_features(path)

        if names != artifact["feature_columns"]:
            raise SystemExit(f"Feature schema mismatch for {path}")

        flags, scores = window_decisions(artifact, values)

        severity = severity_profile(artifact, scores)

        initial = int(state["consecutive_anomalies"])

        final, maximum = update_run(flags, initial)

        status = (
            "ALARM" if final >= artifact["alarm_windows"] else
            "WATCH" if final >= artifact["watch_windows"] else "NORMAL"
        )

        state["consecutive_anomalies"] = min(final, artifact["alarm_windows"])

        state["last_status"] = status
        state["last_wav"] = str(path.resolve())
        state["processed_files"].append(file_key)

        save_json_atomic(state_path, state)

        processed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = {
            "processed_at_utc": processed_at,
            "hive_id": hive_id, "wav": path.name, "sha256": checksum,
            "windows": len(flags), "anomaly_fraction": f"{flags.mean():.6f}",
            "anomaly_severity": "" if severity["anomaly_severity"] is None else f"{severity['anomaly_severity']:.6f}",
            "peak_severity": "" if severity["peak_severity"] is None else f"{severity['peak_severity']:.6f}",
            "initial_run": initial, "final_run": final, "maximum_run": maximum,
            "status": status,
        }
        append_log(log_path, row)

        if panel_url:
            event = {
                "hive_id": panel_hive or hive_id,
                "timestamp": processed_at,
                "status": status,
                "anomaly_fraction": float(flags.mean()),
                "anomaly_severity": severity["anomaly_severity"],
                "consecutive_anomalies": final,
                "source_file": path.name,
                "model": artifact.get("model_file"),
            }
            delivered = deliver_event(event, panel_url, device_key, panel_queue)
            print(
                "panel=" + ("sent" if delivered else f"queued:{panel_queue}"),
                flush=True,
            )

        processed.add(file_key)

        count += 1

        print(f"{path.name}: {status} anomaly_fraction={flags.mean():.4f} final_run={final}", flush = True)

    return count

def main():
    args = arguments()
    if not args.folder.is_dir():
        raise SystemExit(f"Not a directory: {args.folder}")

    if args.poll_seconds <= 0:
        raise SystemExit("--poll seconds must be positive !!")

    artifact = load_monitor(args.model)

    while True:
        count = scan(
            artifact,
            args.folder,
            args.state,
            args.log,
            args.panel_url,
            args.panel_hive,
            args.device_key,
            args.panel_queue,
        )

        if not args.watch:
            print(f"new_files = {count}")

            return

        if count == 0:
            time.sleep(args.poll_seconds)

if __name__ == "__main__":
    main()
