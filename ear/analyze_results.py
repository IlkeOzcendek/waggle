from pathlib import Path

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
)


PREDICTIONS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "waggle_oof_predictions.npz"
)

HEALTHY_ID = 0
QUEENLESS_ID = 1

LABEL_NAMES = {
    HEALTHY_ID: "healthy",
    QUEENLESS_ID: "queenless",
}


def load_predictions():
    """

    It loads the predictions produced when each hive was unseen

    """

    if not PREDICTIONS_PATH.exists():
        raise FileNotFoundError(
            f"Prediction file does not exist -- "
            f"{PREDICTIONS_PATH}"
        )

    with np.load(
        PREDICTIONS_PATH,
        allow_pickle = False,
    ) as dataset:
        y_true = dataset["y_true"]
        y_pred = dataset["y_pred"]

        probabilities = dataset[
            "queenless_probability"
        ]

        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]
        fold_ids = dataset["fold_ids"]

    expected_count = len(y_true)

    arrays = {
        "y_pred": y_pred,
        "queenless_probability": probabilities,
        "hive_ids": hive_ids,
        "session_ids": session_ids,
        "fold_ids": fold_ids,
    }

    for name, values in arrays.items():
        if len(values) != expected_count:
            raise ValueError(
                f"{name} contains {len(values)} values, "
                f"expected {expected_count}"
            )

    valid_labels = {
        HEALTHY_ID,
        QUEENLESS_ID,
    }

    if not set(np.unique(y_true)).issubset(
        valid_labels
    ):
        raise ValueError(
            f"Unexpected true labels: "
            f"{np.unique(y_true)}"
        )

    if not set(np.unique(y_pred)).issubset(
        valid_labels
    ):
        raise ValueError(
            f"Unexpected predicted labels: "
            f"{np.unique(y_pred)}"
        )

    if np.any(
        (probabilities < 0.0)
        | (probabilities > 1.0)
    ):
        raise ValueError(
            "Prediction probabilities must be "
            "between 0 and 1"
        )

    return (
        y_true,
        y_pred,
        probabilities,
        hive_ids,
        session_ids,
        fold_ids,
    )


def inspect_sessions(
    y_true,
    y_pred,
    probabilities,
    hive_ids,
    session_ids,
):
    """

    It shows whether the model behaves differently in each recording session

    """

    print()
    print("Results by recording session:")

    print(
        f"{'session_id':<32} "
        f"{'hive':<8} "
        f"{'true label':<12} "
        f"{'clips':>7} "
        f"{'accuracy':>10} "
        f"{'pred Q %':>10} "
        f"{'mean Q prob':>12}"
    )

    print("-" * 98)

    session_accuracies = []
    session_true_labels = []
    session_predictions = []

    for session_id in np.unique(session_ids):
        mask = session_ids == session_id

        session_labels = np.unique(
            y_true[mask]
        )

        if len(session_labels) != 1:
            raise ValueError(
                f"Session {session_id} contains "
                f"conflicting labels: {session_labels}"
            )

        session_hives = np.unique(
            hive_ids[mask]
        )

        if len(session_hives) != 1:
            raise ValueError(
                f"Session {session_id} contains "
                f"multiple hives: {session_hives}"
            )

        true_label = int(
            session_labels[0]
        )

        hive_id = session_hives[0]

        clip_accuracy = accuracy_score(
            y_true[mask],
            y_pred[mask],
        )

        queenless_prediction_rate = np.mean(
            y_pred[mask] == QUEENLESS_ID
        )

        mean_queenless_probability = np.mean(
            probabilities[mask]
        )

        # The recording session receives one final prediction
        # by averaging all clip probabilities
        session_prediction = (
            QUEENLESS_ID
            if mean_queenless_probability >= 0.5
            else HEALTHY_ID
        )

        session_accuracies.append(
            clip_accuracy
        )

        session_true_labels.append(
            true_label
        )

        session_predictions.append(
            session_prediction
        )

        print(
            f"{session_id:<32} "
            f"{hive_id:<8} "
            f"{LABEL_NAMES[true_label]:<12} "
            f"{int(np.sum(mask)):>7} "
            f"{clip_accuracy:>10.4f} "
            f"{queenless_prediction_rate * 100:>9.1f}% "
            f"{mean_queenless_probability:>12.4f}"
        )

    session_true_labels = np.asarray(
        session_true_labels
    )

    session_predictions = np.asarray(
        session_predictions
    )

    mean_clip_accuracy = np.mean(
        session_accuracies
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

    session_confusion_matrix = confusion_matrix(
        session_true_labels,
        session_predictions,
        labels = [
            HEALTHY_ID,
            QUEENLESS_ID,
        ],
    )

    print()

    print(
        "Mean clip accuracy across sessions: "
        f"{mean_clip_accuracy:.4f}"
    )

    print(
        "Session-level accuracy: "
        f"{session_accuracy:.4f}"
    )

    print(
        "Session-level balanced accuracy: "
        f"{session_balanced_accuracy:.4f}"
    )

    print()
    print("Session-level confusion matrix:")
    print(session_confusion_matrix)


def inspect_confidence(
    y_true,
    y_pred,
    probabilities,
):
    """

    It checks whether wrong predictions are made with high confidence

    """

    correct_mask = y_true == y_pred
    incorrect_mask = ~correct_mask

    predicted_confidence = np.where(
        y_pred == QUEENLESS_ID,
        probabilities,
        1.0 - probabilities,
    )

    mean_correct_confidence = np.mean(
        predicted_confidence[correct_mask]
    )

    mean_incorrect_confidence = np.mean(
        predicted_confidence[incorrect_mask]
    )

    high_confidence_errors = np.sum(
        incorrect_mask
        & (predicted_confidence >= 0.90)
    )

    print()
    print("Prediction confidence:")

    print(
        "Mean confidence when correct: "
        f"{mean_correct_confidence:.4f}"
    )

    print(
        "Mean confidence when incorrect: "
        f"{mean_incorrect_confidence:.4f}"
    )

    print(
        f"Incorrect predictions with at least "
        f"90% confidence: {high_confidence_errors}"
    )


def main():
    (
        y_true,
        y_pred,
        probabilities,
        hive_ids,
        session_ids,
        fold_ids,
    ) = load_predictions()

    print(f"Predictions: {PREDICTIONS_PATH}")
    print(f"Total clips: {len(y_true)}")

    print(
        f"Physical hives: "
        f"{len(np.unique(hive_ids))}"
    )

    print(
        f"Recording sessions: "
        f"{len(np.unique(session_ids))}"
    )

    print(
        f"Completed folds: "
        f"{len(np.unique(fold_ids))}"
    )

    inspect_sessions(
        y_true,
        y_pred,
        probabilities,
        hive_ids,
        session_ids,
    )

    inspect_confidence(
        y_true,
        y_pred,
        probabilities,
    )


if __name__ == "__main__":
    main()