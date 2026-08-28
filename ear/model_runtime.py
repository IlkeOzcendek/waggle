"""

It loads Waggle joblib or ONNX monitor artifacts through one interface

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import joblib
import numpy as np

def load_monitor(path: str | Path) -> dict[str, Any]:
    path = Path(path)

    if path.suffix.lower() != ".onnx":
        return joblib.load(path)

    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers = ["CPUExecutionProvider"])

    metadata = session.get_modelmeta().custom_metadata_map
    required = ("feature_columns", "watch_windows", "alarm_windows")

    missing = [key for key in required if f"waggle.{key}" not in metadata]

    if missing:
        raise ValueError(f" -- ONNX artifact is missing Waggle metadata: {', '.join(missing)} -- ")

    return {
        "feature_columns": json.loads(metadata["waggle.feature_columns"]),
        "watch_windows": int(metadata["waggle.watch_windows"]),
        "alarm_windows": int(metadata["waggle.alarm_windows"]),
        "hive_id": metadata.get("waggle.hive_id") or None,
        "source_doi": metadata.get("waggle.source_doi") or None,
        "_onnx_session": session,
    }

def anomaly_flags(artifact: dict[str, Any], values: np.ndarray) -> np.ndarray:
    """
    
    It returns one Boolean anomaly decision per feature row
    
    """

    session = artifact.get("_onnx_session")

    if session is not None:
        input_name = session.get_inputs()[0].name

        labels = session.run([session.get_outputs()[0].name], {
            input_name: np.asarray(values, dtype = np.float32)
        })[0]

        return np.asarray(labels).reshape(-1) == -1

    scaled = artifact["scaler"].transform(values)

    return artifact["model"].predict(scaled) == -1