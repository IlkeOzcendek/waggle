from pathlib import Path
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


DATASET_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "waggle_mels_cleaned.npz"
)

PREDICTIONS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "waggle_oof_predictions_nuhive_logistic.npz"
)

EXPERIMENT_HIVES = np.array(
    ["Hive1", "Hive3"],
    dtype = np.str_,
)

HEALTHY_ID = 0
QUEENLESS_ID = 1

RANDOM_SEED = 42


def load_dataset():
    """

    It loads only the NU-Hive spectrograms and metadata

    """

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Prepared dataset does not exist -- "
            f"{DATASET_PATH}"
        )

    with np.load(
        DATASET_PATH,
        allow_pickle = False,
    ) as dataset:
        X = dataset["X"].astype(
            np.float32,
            copy = False,
        )

        y = dataset["y"].astype(
            np.int64,
            copy = False,
        )

        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]

    original_count = len(y)

    experiment_mask = np.isin(
        hive_ids,
        EXPERIMENT_HIVES,
    )

    X = X[experiment_mask]
    y = y[experiment_mask]
    hive_ids = hive_ids[experiment_mask]
    session_ids = session_ids[experiment_mask]

    found_hives = set(
        np.unique(hive_ids).tolist()
    )

    expected_hives = set(
        EXPERIMENT_HIVES.tolist()
    )

    if found_hives != expected_hives:
        raise ValueError(
            f"Expected hives {expected_hives}, "
            f"but found {found_hives}"
        )

    expected_count = len(y)

    if X.shape[0] != expected_count:
        raise ValueError(
            f"Feature and label counts do not match: "
            f"{X.shape[0]} and {expected_count}"
        )

    if len(hive_ids) != expected_count:
        raise ValueError(
            "Hive ID and label counts do not match"
        )

    if len(session_ids) != expected_count:
        raise ValueError(
            "Session ID and label counts do not match"
        )

    valid_labels = set(
        np.unique(y).tolist()
    )

    expected_labels = {
        HEALTHY_ID,
        QUEENLESS_ID,
    }

    if valid_labels != expected_labels:
        raise ValueError(
            f"Expected labels {expected_labels}, "
            f"but found {valid_labels}"
        )

    return (
        X,
        y,
        hive_ids,
        session_ids,
        original_count,
    )


def extract_summary_features(X):
    """

    It converts every spectrogram into simple numerical summary features

    For each of the 128 mel frequency bands it calculates:
    - Mean energy across time
    - Standard deviation across time

    The final feature vector contains 256 numbers for every clip

    """

    if X.ndim != 3:
        raise ValueError(
            f"Expected X to have 3 dimensions, "
            f"but got shape {X.shape}"
        )

    frequency_means = np.mean(
        X,
        axis = 2,
    )

    frequency_standard_deviations = np.std(
        X,
        axis = 2,
    )

    features = np.concatenate(
        [
            frequency_means,
            frequency_standard_deviations,
        ],
        axis = 1,
    )

    features = features.astype(
        np.float32,
        copy = False,
    )

    if not np.all(
        np.isfinite(features)
    ):
        raise ValueError(
            "Summary features contain NaN "
            "or infinite values"
        )

    return features


def count_classes(y):
    """

    It returns healthy and queenless sample counts

    """

    healthy_count = int(
        np.sum(y == HEALTHY_ID)
    )

    queenless_count = int(
        np.sum(y == QUEENLESS_ID)
    )

    return (
        healthy_count,
        queenless_count,
    )


def create_splits(
    y,
    hive_ids,
):
    """

    It creates one test fold for Hive1 and one test fold for Hive3

    """

    logo = LeaveOneGroupOut()

    placeholder_X = np.zeros(
        len(y),
        dtype = np.uint8,
    )

    splits = list(
        logo.split(
            placeholder_X,
            y,
            groups = hive_ids,
        )
    )

    if len(splits) != 2:
        raise RuntimeError(
            f"Expected 2 folds, "
            f"but got {len(splits)}"
        )

    for fold_number, (
        train_indices,
        test_indices,
    ) in enumerate(
        splits,
        start = 1,
    ):
        train_hives = set(
            hive_ids[
                train_indices
            ].tolist()
        )

        test_hives = set(
            hive_ids[
                test_indices
            ].tolist()
        )

        overlap = (
            train_hives
            & test_hives
        )

        if overlap:
            raise RuntimeError(
                f"Hive leakage in fold "
                f"{fold_number}: {overlap}"
            )

        if len(train_hives) != 1:
            raise RuntimeError(
                f"Fold {fold_number} must have "
                f"exactly one training hive"
            )

        if len(test_hives) != 1:
            raise RuntimeError(
                f"Fold {fold_number} must have "
                f"exactly one testing hive"
            )

        train_labels = set(
            np.unique(
                y[train_indices]
            ).tolist()
        )

        test_labels = set(
            np.unique(
                y[test_indices]
            ).tolist()
        )

        expected_labels = {
            HEALTHY_ID,
            QUEENLESS_ID,
        }

        if train_labels != expected_labels:
            raise RuntimeError(
                f"Training fold {fold_number} "
                f"is missing a class"
            )

        if test_labels != expected_labels:
            raise RuntimeError(
                f"Testing fold {fold_number} "
                f"is missing a class"
            )

    return splits


def create_model():
    """

    It creates a standard scaler and logistic regression pipeline

    The scaler is fitted using only the training hive inside every fold

    """

    return Pipeline(
        steps = [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight = "balanced",
                    max_iter = 2000,
                    random_state = RANDOM_SEED,
                    solver = "liblinear",
                ),
            ),
        ]
    )


def run_leave_one_hive_out(
    features,
    y,
    hive_ids,
    splits,
):
    """

    It trains the baseline model on one hive and tests it on the other hive

    """

    predictions = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    probabilities = np.full(
        len(y),
        fill_value = np.nan,
        dtype = np.float32,
    )

    majority_predictions = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    fold_ids = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    print()
    print(
        "NU-Hive Logistic Regression folds:"
    )

    for fold_number, (
        train_indices,
        test_indices,
    ) in enumerate(
        splits,
        start = 1,
    ):
        train_hive = np.unique(
            hive_ids[train_indices]
        )[0]

        test_hive = np.unique(
            hive_ids[test_indices]
        )[0]

        print()
        print(
            f"Fold {fold_number}/{len(splits)}"
        )

        print(
            f"  Training hive: {train_hive}"
        )

        print(
            f"  Unseen test hive: {test_hive}"
        )

        model = create_model()

        fold_start_time = (
            time.perf_counter()
        )

        model.fit(
            features[train_indices],
            y[train_indices],
        )

        fold_predictions = model.predict(
            features[test_indices]
        )

        fold_probabilities = (
            model.predict_proba(
                features[test_indices]
            )[
                :,
                QUEENLESS_ID,
            ]
        )

        train_healthy, train_queenless = (
            count_classes(
                y[train_indices]
            )
        )

        if train_queenless > train_healthy:
            majority_label = QUEENLESS_ID
        else:
            majority_label = HEALTHY_ID

        fold_majority_predictions = np.full(
            len(test_indices),
            fill_value = majority_label,
            dtype = np.int64,
        )

        predictions[
            test_indices
        ] = fold_predictions

        probabilities[
            test_indices
        ] = fold_probabilities

        majority_predictions[
            test_indices
        ] = fold_majority_predictions

        fold_ids[
            test_indices
        ] = fold_number

        fold_accuracy = accuracy_score(
            y[test_indices],
            fold_predictions,
        )

        fold_balanced_accuracy = (
            balanced_accuracy_score(
                y[test_indices],
                fold_predictions,
            )
        )

        majority_accuracy = accuracy_score(
            y[test_indices],
            fold_majority_predictions,
        )

        majority_balanced_accuracy = (
            balanced_accuracy_score(
                y[test_indices],
                fold_majority_predictions,
            )
        )

        fold_seconds = (
            time.perf_counter()
            - fold_start_time
        )

        print(
            f"  Logistic accuracy: "
            f"{fold_accuracy:.4f}"
        )

        print(
            f"  Logistic balanced accuracy: "
            f"{fold_balanced_accuracy:.4f}"
        )

        print(
            f"  Training-majority accuracy: "
            f"{majority_accuracy:.4f}"
        )

        print(
            f"  Training-majority balanced accuracy: "
            f"{majority_balanced_accuracy:.4f}"
        )

        print(
            f"  Fold time: "
            f"{fold_seconds:.2f} seconds"
        )

    if np.any(
        predictions == -1
    ):
        raise RuntimeError(
            "Some clips did not receive "
            "a logistic prediction"
        )

    if np.any(
        np.isnan(probabilities)
    ):
        raise RuntimeError(
            "Some clips did not receive "
            "a probability"
        )

    if np.any(
        majority_predictions == -1
    ):
        raise RuntimeError(
            "Some clips did not receive "
            "a majority baseline prediction"
        )

    return (
        predictions,
        probabilities,
        majority_predictions,
        fold_ids,
    )


def print_combined_results(
    y,
    predictions,
    majority_predictions,
    hive_ids,
):
    """

    It prints the combined unseen-hive baseline results

    """

    accuracy = accuracy_score(
        y,
        predictions,
    )

    balanced_accuracy = (
        balanced_accuracy_score(
            y,
            predictions,
        )
    )

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            y,
            predictions,
            labels = [
                QUEENLESS_ID
            ],
            average = None,
            zero_division = 0,
        )
    )

    majority_accuracy = accuracy_score(
        y,
        majority_predictions,
    )

    majority_balanced_accuracy = (
        balanced_accuracy_score(
            y,
            majority_predictions,
        )
    )

    print()
    print(
        "Combined Logistic Regression results:"
    )

    print(
        f"Accuracy: "
        f"{accuracy:.4f}"
    )

    print(
        f"Balanced accuracy: "
        f"{balanced_accuracy:.4f}"
    )

    print(
        f"Queenless precision: "
        f"{precision[0]:.4f}"
    )

    print(
        f"Queenless recall: "
        f"{recall[0]:.4f}"
    )

    print(
        f"Queenless F1: "
        f"{f1[0]:.4f}"
    )

    print()
    print(
        "Training-majority reference:"
    )

    print(
        f"Accuracy: "
        f"{majority_accuracy:.4f}"
    )

    print(
        f"Balanced accuracy: "
        f"{majority_balanced_accuracy:.4f}"
    )

    result_confusion_matrix = (
        confusion_matrix(
            y,
            predictions,
            labels = [
                HEALTHY_ID,
                QUEENLESS_ID,
            ],
        )
    )

    print()
    print(
        "Logistic Regression confusion matrix:"
    )

    print(
        result_confusion_matrix
    )

    print()
    print(
        "Classification report:"
    )

    print(
        classification_report(
            y,
            predictions,
            labels = [
                HEALTHY_ID,
                QUEENLESS_ID,
            ],
            target_names = [
                "healthy",
                "queenless",
            ],
            zero_division = 0,
        )
    )

    print(
        "Results by unseen hive:"
    )

    print(
        f"{'hive_id':<12} "
        f"{'accuracy':>10} "
        f"{'balanced':>10} "
        f"{'clips':>8}"
    )

    print("-" * 44)

    for hive_id in np.unique(hive_ids):
        mask = (
            hive_ids == hive_id
        )

        hive_accuracy = accuracy_score(
            y[mask],
            predictions[mask],
        )

        hive_balanced_accuracy = (
            balanced_accuracy_score(
                y[mask],
                predictions[mask],
            )
        )

        hive_clip_count = int(
            np.sum(mask)
        )

        print(
            f"{hive_id:<12} "
            f"{hive_accuracy:>10.4f} "
            f"{hive_balanced_accuracy:>10.4f} "
            f"{hive_clip_count:>8}"
        )


def inspect_sessions(
    y,
    predictions,
    probabilities,
    hive_ids,
    session_ids,
):
    """

    It prints the Logistic Regression results for every recording session

    """

    print()
    print(
        "Results by recording session:"
    )

    print(
        f"{'session_id':<34} "
        f"{'hive':<8} "
        f"{'true':<10} "
        f"{'clips':>7} "
        f"{'accuracy':>10} "
        f"{'pred Q %':>10} "
        f"{'mean Q':>10}"
    )

    print("-" * 96)

    session_true_labels = []
    session_predictions = []

    for session_id in np.unique(
        session_ids
    ):
        mask = (
            session_ids == session_id
        )

        unique_labels = np.unique(
            y[mask]
        )

        if len(unique_labels) != 1:
            raise ValueError(
                f"Session {session_id} "
                f"contains conflicting labels"
            )

        unique_hives = np.unique(
            hive_ids[mask]
        )

        if len(unique_hives) != 1:
            raise ValueError(
                f"Session {session_id} "
                f"contains multiple hives"
            )

        true_label = int(
            unique_labels[0]
        )

        hive_id = unique_hives[0]

        clip_accuracy = accuracy_score(
            y[mask],
            predictions[mask],
        )

        queenless_rate = np.mean(
            predictions[mask]
            == QUEENLESS_ID
        )

        mean_probability = np.mean(
            probabilities[mask]
        )

        if mean_probability >= 0.5:
            session_prediction = (
                QUEENLESS_ID
            )
        else:
            session_prediction = (
                HEALTHY_ID
            )

        session_true_labels.append(
            true_label
        )

        session_predictions.append(
            session_prediction
        )

        true_name = (
            "queenless"
            if true_label == QUEENLESS_ID
            else "healthy"
        )

        print(
            f"{session_id:<34} "
            f"{hive_id:<8} "
            f"{true_name:<10} "
            f"{int(np.sum(mask)):>7} "
            f"{clip_accuracy:>10.4f} "
            f"{queenless_rate * 100:>9.1f}% "
            f"{mean_probability:>10.4f}"
        )

    session_true_labels = np.asarray(
        session_true_labels,
        dtype = np.int64,
    )

    session_predictions = np.asarray(
        session_predictions,
        dtype = np.int64,
    )

    session_accuracy = accuracy_score(
        session_true_labels,
        session_predictions,
    )

    session_balanced_accuracy = (
        balanced_accuracy_score(
            session_true_labels,
            session_predictions,
        )
    )

    print()
    print(
        f"Session-level accuracy: "
        f"{session_accuracy:.4f}"
    )

    print(
        f"Session-level balanced accuracy: "
        f"{session_balanced_accuracy:.4f}"
    )


def save_predictions(
    y,
    predictions,
    probabilities,
    majority_predictions,
    hive_ids,
    session_ids,
    fold_ids,
):
    """

    It saves the unseen-hive Logistic Regression predictions

    """

    PREDICTIONS_PATH.parent.mkdir(
        parents = True,
        exist_ok = True,
    )

    np.savez_compressed(
        PREDICTIONS_PATH,
        y_true = y,
        y_pred = predictions,
        queenless_probability = probabilities,
        majority_prediction = majority_predictions,
        hive_ids = hive_ids,
        session_ids = session_ids,
        fold_ids = fold_ids,
    )

    print()
    print(
        f"Baseline predictions saved to: "
        f"{PREDICTIONS_PATH}"
    )


def main():
    program_start_time = (
        time.perf_counter()
    )

    (
        X,
        y,
        hive_ids,
        session_ids,
        original_count,
    ) = load_dataset()

    print(f"Dataset: {DATASET_PATH}")
    print(
        "Experiment: NU-Hive "
        "Logistic Regression baseline"
    )
    print(
        "Included hives: Hive1 and Hive3"
    )
    print(
        f"Original clean clips: "
        f"{original_count}"
    )
    print(
        f"Selected NU-Hive clips: "
        f"{len(y)}"
    )
    print(
        f"Spectrogram shape: "
        f"{X.shape}"
    )

    print()
    print(
        "Extracting summary features..."
    )

    features = extract_summary_features(
        X
    )

    print(
        f"Summary feature shape: "
        f"{features.shape}"
    )

    splits = create_splits(
        y,
        hive_ids,
    )

    (
        predictions,
        probabilities,
        majority_predictions,
        fold_ids,
    ) = run_leave_one_hive_out(
        features,
        y,
        hive_ids,
        splits,
    )

    print_combined_results(
        y,
        predictions,
        majority_predictions,
        hive_ids,
    )

    inspect_sessions(
        y,
        predictions,
        probabilities,
        hive_ids,
        session_ids,
    )

    save_predictions(
        y,
        predictions,
        probabilities,
        majority_predictions,
        hive_ids,
        session_ids,
        fold_ids,
    )

    total_seconds = (
        time.perf_counter()
        - program_start_time
    )

    print(
        f"Total program time: "
        f"{total_seconds:.2f} seconds"
    )


if __name__ == "__main__":
    main()