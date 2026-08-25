from pathlib import Path
import random
import time

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import LeaveOneGroupOut
from torch import nn
from torch.utils.data import DataLoader, Dataset


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
    / "waggle_oof_predictions_nuhive_baseline.npz"
)

EXPERIMENT_HIVES = np.array(
    ["Hive1", "Hive3"],
    dtype = np.str_,
)

HEALTHY_ID = 0
QUEENLESS_ID = 1

RANDOM_SEED = 42
EPOCHS = 10
BATCH_SIZE = 64
LEARNING_RATE = 0.001
WEIGHT_DECAY = 0.0001


def set_random_seed():
    """

    It makes the model training more repeatable

    """

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(
            RANDOM_SEED
        )


def choose_device():
    """

    It chooses the fastest available training device

    """

    # MPS means the GPU in an Apple Silicon Mac
    if torch.backends.mps.is_available():
        return torch.device("mps")

    # CUDA is used by supported NVIDIA GPUs
    if torch.cuda.is_available():
        return torch.device("cuda")

    # CPU is used if no supported GPU is available
    return torch.device("cpu")


def format_duration(seconds):
    """

    It converts seconds into an easier to read duration

    """

    seconds = max(
        0,
        int(round(seconds)),
    )

    minutes, seconds = divmod(
        seconds,
        60,
    )

    hours, minutes = divmod(
        minutes,
        60,
    )

    if hours > 0:
        return (
            f"{hours}h "
            f"{minutes}m "
            f"{seconds}s"
        )

    if minutes > 0:
        return (
            f"{minutes}m "
            f"{seconds}s"
        )

    return f"{seconds}s"


def load_dataset():
    """

    It loads only the NU-Hive spectrograms and their metadata

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

    # Only Hive1 and Hive3 belong to the controlled NU-Hive experiment
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
            f"Expected NU-Hive hives "
            f"{expected_hives}, but found "
            f"{found_hives}"
        )

    feature_count = X.shape[0]

    if len(y) != feature_count:
        raise ValueError(
            f"Feature and label counts do not match -- "
            f"{feature_count} features, "
            f"{len(y)} labels"
        )

    if len(hive_ids) != len(y):
        raise ValueError(
            f"Hive ID and label counts do not match -- "
            f"{len(hive_ids)} hive IDs, "
            f"{len(y)} labels"
        )

    if len(session_ids) != len(y):
        raise ValueError(
            f"Session ID and label counts do not match -- "
            f"{len(session_ids)} session IDs, "
            f"{len(y)} labels"
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


def count_classes(y):
    """

    It returns the sample counts of being healthy and queenless

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


def inspect_hive_distribution(
    y,
    hive_ids,
):
    """

    It prints the clean clip distribution for every NU-Hive hive

    """

    print()
    print(
        "Clean clip distribution "
        "by NU-Hive physical hive:"
    )

    print(
        f"{'hive_id':<12} "
        f"{'healthy':>10} "
        f"{'queenless':>12} "
        f"{'total':>8}"
    )

    print("-" * 46)

    for hive_id in np.unique(hive_ids):
        mask = hive_ids == hive_id

        healthy, queenless = count_classes(
            y[mask]
        )

        print(
            f"{hive_id:<12} "
            f"{healthy:>10} "
            f"{queenless:>12} "
            f"{healthy + queenless:>8}"
        )


def create_leave_one_hive_out_splits(
    y,
    hive_ids,
):
    """

    It creates one fold per NU-Hive hive and verifies that no hive leaks
    between training and testing

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

    expected_fold_count = len(
        EXPERIMENT_HIVES
    )

    if len(splits) != expected_fold_count:
        raise RuntimeError(
            f"Expected {expected_fold_count} folds "
            f"but got {len(splits)}"
        )

    print()
    print(
        "NU-Hive Leave One Hive Out folds:"
    )

    print(
        f"{'fold':>4} "
        f"{'test hive':<12} "
        f"{'train H':>8} "
        f"{'train Q':>8} "
        f"{'test H':>8} "
        f"{'test Q':>8}"
    )

    print("-" * 62)

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

        overlap = train_hives & test_hives

        if overlap:
            raise RuntimeError(
                f"Hive leakage in fold "
                f"{fold_number}: {overlap}"
            )

        if len(test_hives) != 1:
            raise RuntimeError(
                f"Fold {fold_number} must contain "
                f"exactly one test hive, "
                f"got {test_hives}"
            )

        if len(train_hives) != 1:
            raise RuntimeError(
                f"Fold {fold_number} must contain "
                f"exactly one training hive, "
                f"got {train_hives}"
            )

        train_healthy, train_queenless = (
            count_classes(
                y[train_indices]
            )
        )

        test_healthy, test_queenless = (
            count_classes(
                y[test_indices]
            )
        )

        if (
            train_healthy == 0
            or train_queenless == 0
        ):
            raise RuntimeError(
                f"Training fold {fold_number} "
                f"is missing a class"
            )

        if (
            test_healthy == 0
            or test_queenless == 0
        ):
            raise RuntimeError(
                f"Testing fold {fold_number} "
                f"is missing a class"
            )

        test_hive = next(
            iter(test_hives)
        )

        print(
            f"{fold_number:>4} "
            f"{test_hive:<12} "
            f"{train_healthy:>8} "
            f"{train_queenless:>8} "
            f"{test_healthy:>8} "
            f"{test_queenless:>8}"
        )

    return splits


class SpectrogramDataset(Dataset):
    """

    It gives the CNN one normalized spectrogram and its label at a time

    """

    def __init__(
        self,
        X,
        y,
        indices,
    ):
        self.X = X
        self.y = y
        self.indices = np.asarray(
            indices
        )

    def __len__(self):
        return len(
            self.indices
        )

    def __getitem__(
        self,
        item,
    ):
        dataset_index = self.indices[
            item
        ]

        spectrogram = self.X[
            dataset_index
        ]

        # Log mel values are expected to be approximately between -80 dB and 0 dB
        spectrogram = np.clip(
            spectrogram,
            -80.0,
            0.0,
        )

        spectrogram = (
            spectrogram + 80.0
        ) / 80.0

        spectrogram = spectrogram.astype(
            np.float32,
            copy = False,
        )

        spectrogram_tensor = (
            torch.from_numpy(
                spectrogram
            ).unsqueeze(0)
        )

        label_tensor = torch.tensor(
            int(
                self.y[
                    dataset_index
                ]
            ),
            dtype = torch.long,
        )

        return (
            spectrogram_tensor,
            label_tensor,
        )


class SmallCNN(nn.Module):
    """

    It learns visual patterns from the mel spectrograms

    """

    def __init__(self):
        super().__init__()

        self.features = nn.Sequential(
            nn.Conv2d(
                in_channels = 1,
                out_channels = 16,
                kernel_size = 3,
                padding = 1,
            ),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.Conv2d(
                in_channels = 16,
                out_channels = 32,
                kernel_size = 3,
                padding = 1,
            ),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.Conv2d(
                in_channels = 32,
                out_channels = 64,
                kernel_size = 3,
                padding = 1,
            ),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.AdaptiveAvgPool2d(
                (1, 1)
            ),
        )

        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(
                in_features = 64,
                out_features = 2,
            ),
        )

    def forward(self, X):
        X = self.features(X)

        return self.classifier(X)


def calculate_class_weights(
    y,
    train_indices,
    device,
):
    """

    It gives more importance to the class with fewer training samples

    """

    train_labels = y[
        train_indices
    ]

    healthy_count, queenless_count = (
        count_classes(
            train_labels
        )
    )

    total_count = (
        healthy_count
        + queenless_count
    )

    healthy_weight = (
        total_count
        / (2 * healthy_count)
    )

    queenless_weight = (
        total_count
        / (2 * queenless_count)
    )

    weights = torch.tensor(
        [
            healthy_weight,
            queenless_weight,
        ],
        dtype = torch.float32,
        device = device,
    )

    return weights


def train_one_fold(
    X,
    y,
    train_indices,
    device,
):
    """

    It creates and trains a new CNN for one fold

    """

    training_dataset = SpectrogramDataset(
        X,
        y,
        train_indices,
    )

    training_loader = DataLoader(
        training_dataset,
        batch_size = BATCH_SIZE,
        shuffle = True,
        num_workers = 0,
    )

    model = SmallCNN().to(
        device
    )

    class_weights = calculate_class_weights(
        y,
        train_indices,
        device,
    )

    loss_function = nn.CrossEntropyLoss(
        weight = class_weights
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr = LEARNING_RATE,
        weight_decay = WEIGHT_DECAY,
    )

    training_start_time = (
        time.perf_counter()
    )

    for epoch_number in range(
        1,
        EPOCHS + 1,
    ):
        epoch_start_time = (
            time.perf_counter()
        )

        model.train()

        total_loss = 0.0
        correct_predictions = 0
        sample_count = 0

        for (
            spectrograms,
            labels,
        ) in training_loader:
            spectrograms = (
                spectrograms.to(
                    device
                )
            )

            labels = labels.to(
                device
            )

            optimizer.zero_grad()

            outputs = model(
                spectrograms
            )

            loss = loss_function(
                outputs,
                labels,
            )

            loss.backward()
            optimizer.step()

            total_loss += (
                loss.item()
                * labels.size(0)
            )

            predictions = outputs.argmax(
                dim = 1
            )

            correct_predictions += (
                predictions == labels
            ).sum().item()

            sample_count += labels.size(0)

        epoch_loss = (
            total_loss
            / sample_count
        )

        epoch_accuracy = (
            correct_predictions
            / sample_count
        )

        epoch_seconds = (
            time.perf_counter()
            - epoch_start_time
        )

        elapsed_seconds = (
            time.perf_counter()
            - training_start_time
        )

        average_epoch_seconds = (
            elapsed_seconds
            / epoch_number
        )

        remaining_seconds = (
            average_epoch_seconds
            * (
                EPOCHS
                - epoch_number
            )
        )

        formatted_epoch_time = (
            format_duration(
                epoch_seconds
            )
        )

        formatted_remaining_time = (
            format_duration(
                remaining_seconds
            )
        )

        print(
            f"    Epoch "
            f"{epoch_number:>2}/{EPOCHS} "
            f"| loss: {epoch_loss:.4f} "
            f"| train accuracy: "
            f"{epoch_accuracy:.4f} "
            f"| time: "
            f"{formatted_epoch_time} "
            f"| fold remaining: "
            f"{formatted_remaining_time}"
        )

    fold_training_seconds = (
        time.perf_counter()
        - training_start_time
    )

    formatted_fold_training_time = (
        format_duration(
            fold_training_seconds
        )
    )

    print(
        f"    Fold training time: "
        f"{formatted_fold_training_time}"
    )

    return model


def predict_test_hive(
    model,
    X,
    y,
    test_indices,
    device,
):
    """

    It predicts the clips belonging to the NU-Hive hive
    that the model has not seen

    """

    testing_dataset = SpectrogramDataset(
        X,
        y,
        test_indices,
    )

    testing_loader = DataLoader(
        testing_dataset,
        batch_size = BATCH_SIZE,
        shuffle = False,
        num_workers = 0,
    )

    predictions = []
    queenless_probabilities = []

    model.eval()

    with torch.no_grad():
        for (
            spectrograms,
            _,
        ) in testing_loader:
            spectrograms = (
                spectrograms.to(
                    device
                )
            )

            outputs = model(
                spectrograms
            )

            probabilities = torch.softmax(
                outputs,
                dim = 1,
            )

            batch_predictions = (
                outputs.argmax(
                    dim = 1
                )
            )

            predictions.extend(
                batch_predictions
                .cpu()
                .numpy()
                .tolist()
            )

            queenless_probabilities.extend(
                probabilities[
                    :,
                    QUEENLESS_ID,
                ]
                .cpu()
                .numpy()
                .tolist()
            )

    predictions = np.asarray(
        predictions,
        dtype = np.int64,
    )

    queenless_probabilities = np.asarray(
        queenless_probabilities,
        dtype = np.float32,
    )

    return (
        predictions,
        queenless_probabilities,
    )


def run_leave_one_hive_out(
    X,
    y,
    hive_ids,
    splits,
    device,
):
    """

    It trains one new model for each NU-Hive hive
    and collects out of fold predictions

    """

    out_of_fold_predictions = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    out_of_fold_probabilities = np.full(
        len(y),
        fill_value = np.nan,
        dtype = np.float32,
    )

    fold_ids = np.full(
        len(y),
        fill_value = -1,
        dtype = np.int64,
    )

    complete_training_start = (
        time.perf_counter()
    )

    completed_fold_times = []

    print()
    print(f"Training device: {device}")

    if device.type == "mps":
        print(
            "Apple Silicon GPU "
            "acceleration is active."
        )

    elif device.type == "cuda":
        print(
            "NVIDIA GPU acceleration "
            "is active."
        )

    else:
        print(
            "GPU acceleration is not available. "
            "CPU will be used."
        )

    print()

    for fold_number, (
        train_indices,
        test_indices,
    ) in enumerate(
        splits,
        start = 1,
    ):
        fold_start_time = (
            time.perf_counter()
        )

        test_hives = set(
            hive_ids[
                test_indices
            ].tolist()
        )

        test_hive = next(
            iter(test_hives)
        )

        print(
            f"Fold {fold_number}/{len(splits)} "
            f"-- test hive: {test_hive}"
        )

        set_random_seed()

        model = train_one_fold(
            X,
            y,
            train_indices,
            device,
        )

        (
            predictions,
            probabilities,
        ) = predict_test_hive(
            model,
            X,
            y,
            test_indices,
            device,
        )

        out_of_fold_predictions[
            test_indices
        ] = predictions

        out_of_fold_probabilities[
            test_indices
        ] = probabilities

        fold_ids[
            test_indices
        ] = fold_number

        fold_accuracy = accuracy_score(
            y[test_indices],
            predictions,
        )

        fold_balanced_accuracy = (
            balanced_accuracy_score(
                y[test_indices],
                predictions,
            )
        )

        fold_seconds = (
            time.perf_counter()
            - fold_start_time
        )

        completed_fold_times.append(
            fold_seconds
        )

        average_fold_seconds = np.mean(
            completed_fold_times
        )

        remaining_fold_count = (
            len(splits)
            - fold_number
        )

        estimated_remaining_seconds = (
            average_fold_seconds
            * remaining_fold_count
        )

        formatted_fold_time = (
            format_duration(
                fold_seconds
            )
        )

        formatted_remaining_time = (
            format_duration(
                estimated_remaining_seconds
            )
        )

        print(
            f"    Unseen hive accuracy: "
            f"{fold_accuracy:.4f}"
        )

        print(
            f"    Unseen hive balanced accuracy: "
            f"{fold_balanced_accuracy:.4f}"
        )

        print(
            f"    Complete fold time: "
            f"{formatted_fold_time}"
        )

        print(
            f"    Estimated total remaining time: "
            f"{formatted_remaining_time}"
        )

        print()

        del model

        if device.type == "mps":
            torch.mps.empty_cache()

        if device.type == "cuda":
            torch.cuda.empty_cache()

    if np.any(
        out_of_fold_predictions == -1
    ):
        raise RuntimeError(
            "Some clips did not receive "
            "an out of fold prediction"
        )

    if np.any(
        np.isnan(
            out_of_fold_probabilities
        )
    ):
        raise RuntimeError(
            "Some clips did not receive "
            "an out of fold probability"
        )

    complete_training_seconds = (
        time.perf_counter()
        - complete_training_start
    )

    formatted_training_time = (
        format_duration(
            complete_training_seconds
        )
    )

    print(
        "Complete NU-Hive Leave One Hive Out "
        f"training time: "
        f"{formatted_training_time}"
    )

    return (
        out_of_fold_predictions,
        out_of_fold_probabilities,
        fold_ids,
    )


def print_results(
    y,
    predictions,
    hive_ids,
):
    """

    It reports the combined results from both unseen NU-Hive predictions

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

    print()
    print(
        "Combined NU-Hive "
        "out of fold results:"
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
    print("Confusion matrix:")
    print(result_confusion_matrix)

    print()
    print("Confusion matrix order:")

    print(
        "[[healthy predicted healthy, "
        "healthy predicted queenless],"
    )

    print(
        " [queenless predicted healthy, "
        "queenless predicted queenless]]"
    )

    print()
    print("Classification report:")

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
        "Results by unseen NU-Hive hive:"
    )

    print(
        f"{'hive_id':<12} "
        f"{'accuracy':>10} "
        f"{'balanced':>10} "
        f"{'clips':>8}"
    )

    print("-" * 44)

    for hive_id in np.unique(hive_ids):
        mask = hive_ids == hive_id

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


def save_predictions(
    y,
    predictions,
    probabilities,
    hive_ids,
    session_ids,
    fold_ids,
):
    """

    It saves every unseen NU-Hive prediction for later error analysis

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
        hive_ids = hive_ids,
        session_ids = session_ids,
        fold_ids = fold_ids,
    )

    print()

    print(
        f"NU-Hive predictions saved to: "
        f"{PREDICTIONS_PATH}"
    )


def main():
    program_start_time = (
        time.perf_counter()
    )

    set_random_seed()

    (
        X,
        y,
        hive_ids,
        session_ids,
        original_count,
    ) = load_dataset()

    healthy_count, queenless_count = (
        count_classes(y)
    )

    selected_count = len(y)

    excluded_count = (
        original_count
        - selected_count
    )

    physical_hive_count = len(
        np.unique(hive_ids)
    )

    recording_session_count = len(
        np.unique(session_ids)
    )

    print(f"Dataset: {DATASET_PATH}")
    print("Experiment: NU-Hive only")
    print("Included hives: Hive1 and Hive3")

    print(
        "Normalization: "
        "fixed -80 dB to 0 dB"
    )

    print(
        f"Original clean clips: "
        f"{original_count}"
    )

    print(
        f"Selected NU-Hive clips: "
        f"{selected_count}"
    )

    print(
        f"Excluded OSBH clips: "
        f"{excluded_count}"
    )

    print(
        f"Spectrogram shape: "
        f"{X.shape}"
    )

    print(
        f"Healthy clips: "
        f"{healthy_count}"
    )

    print(
        f"Queenless clips: "
        f"{queenless_count}"
    )

    print(
        f"Physical hives: "
        f"{physical_hive_count}"
    )

    print(
        f"Recording sessions: "
        f"{recording_session_count}"
    )

    inspect_hive_distribution(
        y,
        hive_ids,
    )

    splits = (
        create_leave_one_hive_out_splits(
            y,
            hive_ids,
        )
    )

    device = choose_device()

    (
        predictions,
        probabilities,
        fold_ids,
    ) = run_leave_one_hive_out(
        X,
        y,
        hive_ids,
        splits,
        device,
    )

    print_results(
        y,
        predictions,
        hive_ids,
    )

    save_predictions(
        y,
        predictions,
        probabilities,
        hive_ids,
        session_ids,
        fold_ids,
    )

    total_program_seconds = (
        time.perf_counter()
        - program_start_time
    )

    formatted_program_time = (
        format_duration(
            total_program_seconds
        )
    )

    print(
        f"Total program time: "
        f"{formatted_program_time}"
    )


if __name__ == "__main__":
    main()