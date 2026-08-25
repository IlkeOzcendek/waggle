"""

It fits a small classifier on top of the frozen pretrained audio
embeddings and evaluates it the honest way: one decision per recording,
never on a recording the classifier has seen

"""

from pathlib import Path
import argparse
import re
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

EMBEDDING_PATH = (
    PROCESSED_DIR
    / "waggle_embeddings_ast.npz"
)

NUHIVE_HIVES = (
    "Hive1",
    "Hive3",
)

HIVE_SETS = (
    "all",
    "nuhive",
)

# 'dataset' asks the hardest question the current data can pose: train
# on one published collection and test on the other one
GROUP_MODES = (
    "session",
    "hive",
    "dataset",
)

MINIMUM_SESSION_CLIPS = 10

HEALTHY_ID = 0
QUEENLESS_ID = 1

CLASS_NAMES = {
    HEALTHY_ID: "healthy",
    QUEENLESS_ID: "queenless",
}

RANDOM_SEED = 42

# The OSBH hive codes look like CF001, the NU-Hive ones like Hive1
OSBH_HIVE_PATTERN = re.compile(
    r"^[A-Za-z]{2}\d{3}$"
)


def parse_arguments():
    """

    It reads the experiment settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "Linear probe on frozen pretrained audio embeddings, "
            "evaluated one recording at a time"
        )
    )

    parser.add_argument(
        "--hives",
        choices = HIVE_SETS,
        default = "all",
    )

    parser.add_argument(
        "--group",
        choices = GROUP_MODES,
        default = "session",
        help = (
            "Unit that is held out in every fold"
        ),
    )

    parser.add_argument(
        "--min-clips",
        type = int,
        default = MINIMUM_SESSION_CLIPS,
    )

    return parser.parse_args()


def build_predictions_path(
    hive_set,
    group_mode,
):
    """

    It gives every variant its own file for compare_experiments.py

    """

    return (
        PROCESSED_DIR
        / (
            f"waggle_oof_predictions_"
            f"{hive_set}_{group_mode}_ast.npz"
        )
    )


def derive_dataset_ids(hive_ids):
    """

    It labels every clip with the published collection it comes from

    """

    return np.asarray(
        [
            "OSBH"
            if OSBH_HIVE_PATTERN.match(
                str(hive_id)
            )
            else "NU-Hive"
            for hive_id in hive_ids
        ],
        dtype = np.str_,
    )


def load_embeddings(
    hive_set,
    minimum_session_clips,
):
    """

    It loads the encoder output and drops the recordings that are too
    short to carry a decision

    """

    if not EMBEDDING_PATH.exists():
        raise FileNotFoundError(
            f"Embeddings do not exist -- "
            f"{EMBEDDING_PATH}. Run "
            f"ear/extract_embeddings.py first"
        )

    with np.load(
        EMBEDDING_PATH,
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

    if hive_set == "nuhive":
        keep = np.isin(
            hive_ids,
            np.asarray(NUHIVE_HIVES),
        )

        X, y = X[keep], y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    dropped_sessions = []

    for session_id in np.unique(
        session_ids
    ):
        clip_count = int(
            np.sum(
                session_ids == session_id
            )
        )

        if (
            clip_count
            < minimum_session_clips
        ):
            dropped_sessions.append(
                (
                    str(session_id),
                    clip_count,
                )
            )

    if dropped_sessions:
        keep = ~np.isin(
            session_ids,
            np.asarray(
                [
                    name
                    for name, _ in dropped_sessions
                ]
            ),
        )

        X, y = X[keep], y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    return (
        X,
        y,
        hive_ids,
        session_ids,
        dropped_sessions,
    )


def create_model():
    """

    It creates the linear probe that sits on the frozen encoder

    The encoder stays untouched, so only a few hundred weights are
    fitted. That is what keeps a model this large usable with a handful
    of recordings

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
                    max_iter = 5000,
                    random_state = RANDOM_SEED,
                ),
            ),
        ]
    )


def run_cross_validation(
    X,
    y,
    groups,
):
    """

    It trains one probe per fold and collects the out of fold
    predictions of every clip

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

    fold_ids = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    skipped_groups = []
    fold_number = 0

    for group in np.unique(groups):
        test_mask = groups == group
        train_mask = ~test_mask

        if len(
            np.unique(y[train_mask])
        ) < 2:
            skipped_groups.append(
                str(group)
            )

            continue

        fold_number += 1

        model = create_model()

        model.fit(
            X[train_mask],
            y[train_mask],
        )

        queenless_column = list(
            model.classes_
        ).index(QUEENLESS_ID)

        fold_probabilities = (
            model.predict_proba(
                X[test_mask]
            )[:, queenless_column]
        )

        predictions[test_mask] = np.where(
            fold_probabilities > 0.5,
            QUEENLESS_ID,
            HEALTHY_ID,
        )

        probabilities[
            test_mask
        ] = fold_probabilities

        fold_ids[test_mask] = fold_number

    return (
        predictions,
        probabilities,
        fold_ids,
        skipped_groups,
    )


def print_session_results(
    y,
    predictions,
    probabilities,
    hive_ids,
    session_ids,
):
    """

    It aggregates the clip predictions into one decision per recording

    """

    print()

    print(
        "Session level results (primary):"
    )

    print(
        f"{'session_id':<34} "
        f"{'hive':<8} "
        f"{'true':<11} "
        f"{'clips':>7} "
        f"{'clip acc':>9} "
        f"{'median Q':>9} "
        f"{'decision':<11} "
        f"{'ok':>3}"
    )

    print("-" * 98)

    truth = []
    decisions = []

    for session_id in np.unique(
        session_ids
    ):
        mask = session_ids == session_id

        true_label = int(
            np.unique(y[mask])[0]
        )

        median_probability = float(
            np.median(probabilities[mask])
        )

        decision = (
            QUEENLESS_ID
            if median_probability > 0.5
            else HEALTHY_ID
        )

        truth.append(true_label)
        decisions.append(decision)

        print(
            f"{session_id:<34} "
            f"{np.unique(hive_ids[mask])[0]:<8} "
            f"{CLASS_NAMES[true_label]:<11} "
            f"{int(np.sum(mask)):>7} "
            f"{accuracy_score(y[mask], predictions[mask]):>9.4f} "
            f"{median_probability:>9.4f} "
            f"{CLASS_NAMES[decision]:<11} "
            f"{('yes' if decision == true_label else 'no'):>3}"
        )

    truth = np.asarray(truth)
    decisions = np.asarray(decisions)

    correct = int(
        np.sum(truth == decisions)
    )

    print()

    print(
        f"Recordings correct: "
        f"{correct}/{len(truth)}"
    )

    if len(np.unique(truth)) > 1:
        print(
            f"Session level balanced accuracy: "
            f"{balanced_accuracy_score(truth, decisions):.4f}"
        )

    print()

    print(
        f"Warning: this metric has only "
        f"{len(truth)} independent samples."
    )

    return correct


def main():
    program_start_time = time.perf_counter()

    arguments = parse_arguments()

    (
        X,
        y,
        hive_ids,
        session_ids,
        dropped_sessions,
    ) = load_embeddings(
        arguments.hives,
        arguments.min_clips,
    )

    dataset_ids = derive_dataset_ids(
        hive_ids
    )

    groups = {
        "session": session_ids,
        "hive": hive_ids,
        "dataset": dataset_ids,
    }[arguments.group]

    print(f"Embeddings: {EMBEDDING_PATH}")

    print(
        f"Experiment: leave one "
        f"{arguments.group} out (AST linear probe)"
    )

    print(
        f"Hive set: {arguments.hives} "
        f"({len(np.unique(hive_ids))} hives)"
    )

    print(f"Clips: {len(y)}")

    print(
        f"Embedding size: {X.shape[1]}"
    )

    print(
        f"Recordings: "
        f"{len(np.unique(session_ids))}"
    )

    for name, clip_count in (
        dropped_sessions
    ):
        print(
            f"Dropped recording {name} -- "
            f"only {clip_count} clips"
        )

    (
        predictions,
        probabilities,
        fold_ids,
        skipped_groups,
    ) = run_cross_validation(
        X,
        y,
        groups,
    )

    for group in skipped_groups:
        print(
            f"Skipped fold {group} -- holding it "
            f"out leaves a single class in training"
        )

    covered = fold_ids != -1

    y = y[covered]
    predictions = predictions[covered]
    probabilities = probabilities[covered]
    hive_ids = hive_ids[covered]
    session_ids = session_ids[covered]
    fold_ids = fold_ids[covered]

    print()
    print("Clip level results (secondary):")

    print(
        f"Accuracy: "
        f"{accuracy_score(y, predictions):.4f}"
    )

    print(
        f"Balanced accuracy: "
        f"{balanced_accuracy_score(y, predictions):.4f}"
    )

    print()
    print("Confusion matrix:")

    print(
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

    print_session_results(
        y,
        predictions,
        probabilities,
        hive_ids,
        session_ids,
    )

    predictions_path = (
        build_predictions_path(
            arguments.hives,
            arguments.group,
        )
    )

    np.savez_compressed(
        predictions_path,
        y_true = y,
        y_pred = predictions,
        queenless_probability = probabilities,
        hive_ids = hive_ids,
        session_ids = session_ids,
        fold_ids = fold_ids,
    )

    print(
        f"Predictions saved to: "
        f"{predictions_path}"
    )

    print(
        f"Total program time: "
        f"{time.perf_counter() - program_start_time:.2f} seconds"
    )


if __name__ == "__main__":
    main()
