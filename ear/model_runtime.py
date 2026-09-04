"""

It loads Waggle joblib or ONNX monitor artifacts through one interface

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import joblib
import numpy as np

ONNX_LABEL_OUTPUT = "label"
ONNX_SCORE_OUTPUT = "scores"


def _validated_metadata(session) -> dict[str, Any]:
    metadata = session.get_modelmeta().custom_metadata_map
    required = ("feature_columns", "watch_windows", "alarm_windows")
    missing = [key for key in required if f"waggle.{key}" not in metadata]
    if missing:
        raise ValueError(f" -- ONNX artifact is missing Waggle metadata: {', '.join(missing)} -- ")

    try:
        feature_columns = json.loads(metadata["waggle.feature_columns"])
        watch_windows = int(metadata["waggle.watch_windows"])
        alarm_windows = int(metadata["waggle.alarm_windows"])
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("ONNX artifact has invalid Waggle metadata") from error

    if (not isinstance(feature_columns, list) or not feature_columns or
            any(not isinstance(name, str) or not name for name in feature_columns) or
            len(set(feature_columns)) != len(feature_columns)):
        raise ValueError("ONNX feature_columns must be a non-empty list of unique names")
    if watch_windows <= 0 or alarm_windows < watch_windows:
        raise ValueError("ONNX thresholds must satisfy 0 < watch_windows <= alarm_windows")

    inputs = session.get_inputs()
    if len(inputs) != 1 or inputs[0].type != "tensor(float)" or len(inputs[0].shape) != 2:
        raise ValueError("ONNX monitor must have one rank-2 float input")
    width = inputs[0].shape[1]
    if isinstance(width, int) and width != len(feature_columns):
        raise ValueError("ONNX input width does not match feature_columns")

    outputs = {output.name: output for output in session.get_outputs()}
    if ONNX_LABEL_OUTPUT not in outputs or ONNX_SCORE_OUTPUT not in outputs:
        raise ValueError("ONNX monitor must expose label and scores outputs")
    if outputs[ONNX_LABEL_OUTPUT].type != "tensor(int64)" or outputs[ONNX_SCORE_OUTPUT].type != "tensor(float)":
        raise ValueError("ONNX label or scores output has an unexpected type")

    raw_offset = metadata.get("waggle.score_offset")
    score_offset = _parsed_offset(raw_offset)
    if raw_offset and (score_offset is None or not np.isfinite(score_offset) or score_offset <= -1):
        raise ValueError("ONNX score_offset metadata is invalid")

    return {
        "feature_columns": feature_columns,
        "watch_windows": watch_windows,
        "alarm_windows": alarm_windows,
        "hive_id": metadata.get("waggle.hive_id") or None,
        "source_doi": metadata.get("waggle.source_doi") or None,
        "score_offset": score_offset,
    }

def load_monitor(path: str | Path) -> dict[str, Any]: # It examines the file and if it's Joblib therefore loads it directly. If it's ONNX it opens it with the ONNX Runtime, checks for necessary metadata, retrieves feature, watch, alarm, hive information and then returns the model ready to run
    path = Path(path)

    if path.suffix.lower() != ".onnx":
        artifact = joblib.load(path)
        # The artifact carries the file it came from, so whatever consumes it can record
        # which model decided an event instead of the caller having to thread the path through.
        if isinstance(artifact, dict):
            artifact.setdefault("model_file", path.name)
        return artifact

    import onnxruntime as ort

    options = ort.SessionOptions()
    # Measured on this graph at 60, 300, 600 and 2000 windows: a single intra-op thread is
    # 7% to 25% faster than the default pool, because a tree ensemble this size spends more
    # on coordinating threads than it saves by splitting the work. CoreML was measured too
    # and is 48% slower — it accepts the graph and falls back to CPU node by node.
    options.intra_op_num_threads = 1

    session = ort.InferenceSession(str(path), options, providers = ["CPUExecutionProvider"])

    contract = _validated_metadata(session)

    return {
        **contract,
        # Optional, because a profile exported before the panel reported severity carries
        # no offset. Its windows are still classified; they simply have no depth to report.
        "model_file": path.name,
        "_onnx_session": session,
    }

def _parsed_offset(value: str | None) -> float | None: # It reads the stored decision offset and treats an absent or unreadable one as "this artifact cannot report severity"
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None

def _score_offset(artifact: dict[str, Any]) -> float | None: # It finds the offset in the metadata of an ONNX artifact or on the estimator itself in a joblib one
    offset = artifact.get("score_offset")

    if offset is None:
        offset = getattr(artifact.get("model"), "offset_", None)

    return None if offset is None else float(offset)

def window_decisions(artifact: dict[str, Any], values: np.ndarray) -> tuple[np.ndarray, np.ndarray]: # If the model is ONNX it runs both graph outputs otherwise it scores through the scaler and the Joblib estimator. Either way it returns one decision and one score per row
    """

    It returns the anomaly decision and the raw decision score for every feature row

    The flag says a window fell outside the learned profile; the score says how far
    outside it fell. The graph has always produced both and only the first was ever read,
    which left two hives at the same anomaly ratio indistinguishable no matter how much
    deeper one of them had drifted.

    """

    values = np.asarray(values)
    expected_width = len(artifact["feature_columns"])
    if values.ndim != 2 or values.shape[1] != expected_width:
        raise ValueError(f"Feature matrix must have shape (rows, {expected_width})")
    if not np.issubdtype(values.dtype, np.number) or not np.isfinite(values).all():
        raise ValueError("Feature matrix must contain only finite numbers")

    session = artifact.get("_onnx_session")

    if session is not None:
        input_name = session.get_inputs()[0].name

        labels, scores = session.run([ONNX_LABEL_OUTPUT, ONNX_SCORE_OUTPUT], {
            input_name: np.asarray(values, dtype = np.float32)
        })

        labels = np.asarray(labels).reshape(-1)

        scores = np.asarray(scores, dtype = np.float64).reshape(-1)

        return labels == -1, scores

    scaled = artifact["scaler"].transform(values)

    # IsolationForest.predict is decision_function() < 0, so deriving the flag from the
    # score keeps one model pass and the identical decision.
    scores = np.asarray(artifact["model"].decision_function(scaled), dtype = np.float64)

    return scores < 0, scores

def anomaly_flags(artifact: dict[str, Any], values: np.ndarray) -> np.ndarray: # The decision only, for the callers that never needed the score
    """

    It returns one Boolean anomaly decision per feature row

    """

    return window_decisions(artifact, values)[0]

def severity_profile(artifact: dict[str, Any], scores: np.ndarray) -> dict[str, float | None]: # It converts raw decision scores into how deep the deviation was, on a scale the model defines for itself
    """

    It reports how far the anomalous windows fell past the boundary, from 0 to 1

    A raw score is only comparable within one model, so it is divided by the deepest value
    that model could ever produce: the decision score is the isolation score minus the
    offset, and the isolation score never goes below -1, so -1 - offset is the floor.
    A severity of 1 therefore means "as far outside this hive's profile as this model can
    express", and the number stays comparable between two hives with different profiles.

    """

    offset = _score_offset(artifact)

    limit = None if offset is None else 1.0 + offset

    if limit is None or limit <= 0: # A profile exported before this was recorded, or a degenerate offset
        return {"anomaly_severity": None, "peak_severity": None}

    depths = np.clip(np.asarray(scores, dtype = np.float64) / -limit, 0.0, 1.0)

    anomalous = depths > 0

    return {
        # The mean over anomalous windows only: averaging in the normal ones would report a
        # milder period simply because it was mostly quiet, which anomaly_fraction already says.
        "anomaly_severity": float(depths[anomalous].mean()) if anomalous.any() else 0.0,
        "peak_severity": float(depths.max(initial = 0.0)),
    }
