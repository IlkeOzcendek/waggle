"""

It extracts the published 21 features from WAV and runs the saved hive monitor

"""

from pathlib import Path

import argparse # taking value using the terminal
import json
import os
import sys
import numpy as np

from scipy.io import wavfile
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
LOCAL_PYAUDIO = ROOT / ".tools" / "pyaudioanalysis"

sys.path.insert(0, str(LOCAL_PYAUDIO))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/waggle_matplotlib")

from pyAudioAnalysis import ShortTermFeatures  # noqa: E402
try:  # supports both `python ear/...` and package imports in tests
    from .model_runtime import anomaly_flags, load_monitor  # type: ignore
except ImportError:
    from model_runtime import anomaly_flags, load_monitor  # noqa: E402

def arguments(): # It retrieves the necessary information from the terminal to analyze a single WAV file using the trained model
    parser = argparse.ArgumentParser(description = __doc__)
    parser.add_argument("model", type = Path)
    parser.add_argument("wav", type = Path)

    parser.add_argument(
        "--state", type = Path,
        help = "Be persistant on the consecutive anomaly counter among the WAV files")

    return parser.parse_args()

def wav_features(path, target_rate = 16000): # It takes the WAV file and converts it into 21 numerical features that the model can understand ** important!!
    rate, signal = wavfile.read(path)

    if signal.ndim == 2:
        signal = signal.mean(axis = 1)

    if signal.dtype != np.int16:
        raise ValueError("! * WAV must use 16 bit PCM * !")
    if rate != target_rate:
        divisor = np.gcd(rate, target_rate)
        signal = resample_poly(
            signal.astype(np.float64), target_rate // divisor, rate // divisor
        )

        signal = np.clip(np.rint(signal), -32768, 32767).astype(np.int16)

        rate = target_rate

    short_window = round(0.050 * rate)
    short_step = round(0.025 * rate)

    short, names = ShortTermFeatures.feature_extraction(
        signal, rate, short_window, short_step
    )

    mid_window_ratio = round((rate - (short_window - short_step)) / short_step)
    mid_step_ratio = round(rate / short_step)

    mid = []

    for feature in short[:21]:
        mid.append([
            np.mean(feature[start:min(start + mid_window_ratio, len(feature))])
            for start in range(0, len(feature), mid_step_ratio)
        ])

    shortest = min(map(len, mid))
    mid = np.asarray([row[:shortest] for row in mid])

    # The published CSV retains the first 21 mid term means as 3 time domain, 5 spectral and 13 MFCC features; standard deviation and chroma rows are intentionally excluded on here

    values = mid[:21].T.astype(np.float64)
    base_names = names[:21]

    if values.shape[1] != 21 or not np.isfinite(values).all():
        raise ValueError(" ! * Feature extraction did not produce finite 21 column output * !")

    return values, base_names

def first_completion(flags, required):
    run = 0

    for index, flag in enumerate(flags, start = 1):
        run = run + 1 if flag else 0

        if run >= required:
            return index

    return None

def update_run(flags, initial_run = 0):
    run = initial_run

    maximum = run

    for flag in flags:
        run = run + 1 if flag else 0

        maximum = max(maximum, run)

    return run, maximum

def load_state(path, artifact): # remain anomalies
    if path is None or not path.exists():
        return {"hive_id": artifact.get("hive_id"), "consecutive_anomalies": 0}

    state = json.loads(path.read_text(encoding = "utf-8"))

    if state.get("hive_id") != artifact.get("hive_id"):
        raise SystemExit(" !* State file belongs to a different hive profile *! ")

    return state

def save_state(path, state):
    if path is None:
        return

    path.parent.mkdir(parents = True, exist_ok = True)

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent = 2) + "\n", encoding = "utf-8")
    temporary.replace(path)

def main():
    args = arguments()

    artifact = load_monitor(args.model)

    values, names = wav_features(args.wav)

    if names != artifact["feature_columns"]: # features not same then
        raise SystemExit(f" !* Feature schema mismatch:\nextracted={names}\nmodel={artifact['feature_columns']} *! ")

    flags = anomaly_flags(artifact, values)

    state = load_state(args.state, artifact)

    initial_run = int(state.get("consecutive_anomalies", 0))

    combined = np.concatenate((np.ones(initial_run, dtype = bool), flags))

    watch_combined = first_completion(combined, artifact["watch_windows"])

    alarm_combined = first_completion(combined, artifact["alarm_windows"])

    watch_at = None if watch_combined is None else max(0, watch_combined - initial_run)

    alarm_at = None if alarm_combined is None else max(0, alarm_combined - initial_run)

    final_run, maximum_run = update_run(flags, initial_run)

    status = (
        "alarm" if final_run >= artifact["alarm_windows"] else
        "watch" if final_run >= artifact["watch_windows"] else "normal"
    )

    # Once alarm is reached a larger number carries no extra information and would only make the next state load unnecessarily large

    state["consecutive_anomalies"] = min(final_run, artifact["alarm_windows"])
    state["last_status"] = status
    state["last_wav"] = str(args.wav)

    save_state(args.state, state)

    print(f"windows = {len(flags)}")
    print(f"anomaly_fraction = {float(flags.mean()):.4f}")
    print(f"initial_consecutive_anomalies = {initial_run}")
    print(f"final_consecutive_anomalies = {final_run}")
    print(f"maximum_consecutive_anomalies = {maximum_run}")
    print(f"watch_completion_second = {watch_at}")
    print(f"alarm_completion_second = {alarm_at}")
    print(f"status = {status}")
    print("WARNING !* a different microphone/hive requires its own healthy enrollment model *! ")

if __name__ == "__main__":
    main()
