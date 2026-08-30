import tempfile
import unittest
from pathlib import Path

import numpy as np

from ear.model_runtime import anomaly_flags, load_monitor
from ear.profile_training import train_verified_profile


class ProfileTrainingTest(unittest.TestCase): # The model is being trained for H4, Joblib and ONNX are being created, it is checked whether their decisions are the same and ONNX is reloaded to verify that it can provide results for all 180 data points
    def test_profile_is_exported_and_verified(self):
        rng = np.random.default_rng(42)

        values = rng.normal(size = (180, 21))

        names = [f"feature_{index}" for index in range(21)]

        with tempfile.TemporaryDirectory() as directory:
            joblib_path = Path(directory) / "H4.joblib"

            onnx_path = Path(directory) / "H4.onnx"

            report = train_verified_profile(
                values, names, "H4", joblib_path, onnx_path, n_estimators = 25
            )

            self.assertTrue(joblib_path.exists())
            self.assertTrue(onnx_path.exists())
            self.assertEqual(report["different_decisions"], 0)

            artifact = load_monitor(onnx_path)

            self.assertEqual(artifact["hive_id"], "H4")
            self.assertEqual(len(anomaly_flags(artifact, values)), len(values))

    def test_invalid_feature_matrix_is_rejected(self): # The data has 20 columns but the system expects 21 feature names and tests that training should not start and should return a ValueError because the dimensions do not match
        with tempfile.TemporaryDirectory() as directory:

            with self.assertRaises(ValueError):
                train_verified_profile(
                    np.zeros((10, 20)), [f"f{i}" for i in range(21)], "H4",
                    Path(directory) / "H4.joblib", Path(directory) / "H4.onnx",

                    n_estimators = 5,
                )

if __name__ == "__main__":
    unittest.main()