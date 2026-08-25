from pathlib import Path
import argparse
import copy
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
from torch import nn
from torch.utils.data import DataLoader, Dataset


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

DATASET_PATHS = {
    "tobee": PROCESSED_DIR
    / "waggle_mels_cleaned.npz",
    "sbcm": PROCESSED_DIR
    / "waggle_mels_sbcm.npz",
}

DATASET_CHOICES = (
    "tobee",
    "sbcm",
    "both",
)

# The NU-Hive subset is the controlled experiment with two hives.
# The full set adds the OSBH hives, which have one recording each
NUHIVE_HIVES = (
    "Hive1",
    "Hive3",
)

HIVE_SETS = (
    "all",
    "nuhive",
)

# A recording with only a handful of clips cannot carry a decision, and
# it would still count as a full sample in the session level metric
MINIMUM_SESSION_CLIPS = 10

# Validating on a tiny recording gives a meaningless early stopping signal
MINIMUM_VALIDATION_CLIPS = 50

HEALTHY_ID = 0
QUEENLESS_ID = 1

CLASS_NAMES = {
    HEALTHY_ID: "healthy",
    QUEENLESS_ID: "queenless",
}

RANDOM_SEED = 42

# Model selection needs a validation split that contains both classes.
# When the fold cannot provide one the run falls back to a fixed epoch
# count so that the result stays comparable with train_nuhive.py
MAX_EPOCHS = 30
FALLBACK_EPOCHS = 10
EARLY_STOPPING_PATIENCE = 8

BATCH_SIZE = 64
LEARNING_RATE = 0.001
WEIGHT_DECAY = 0.0001

GROUP_MODES = (
    "session",
    "hive",
)

NORMALIZATION_MODES = (
    "fixed",
    "clip",
    "cmvn",
)

DEFAULT_GROUP_MODE = "session"
DEFAULT_NORMALIZATION = "cmvn"

# SpecAugment style masking plus a random spectral tilt.
# The tilt imitates a different microphone frequency response, which is
# exactly the recording fingerprint the model must stop relying on
FREQUENCY_MASK_COUNT = 2
FREQUENCY_MASK_WIDTH = 16
TIME_MASK_COUNT = 2
TIME_MASK_WIDTH = 24
SPECTRAL_TILT_LIMIT = 0.25
TIME_SHIFT_ENABLED = True


def parse_arguments():
    """

    It reads the experiment settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "Grouped cross validation for the NU-Hive queenless "
            "detector with recording aware normalization"
        )
    )

    parser.add_argument(
        "--dataset",
        choices = DATASET_CHOICES,
        default = "tobee",
        help = (
            "'tobee' is the To bee or not to bee collection, "
            "'sbcm' is the Smart Bee Colony Monitor controlled "
            "experiment, 'both' concatenates them"
        ),
    )

    parser.add_argument(
        "--hives",
        choices = HIVE_SETS,
        default = "all",
        help = (
            "'all' uses every hive in the prepared dataset, "
            "'nuhive' keeps only the controlled Hive1 and Hive3 "
            "experiment"
        ),
    )

    parser.add_argument(
        "--min-clips",
        type = int,
        default = MINIMUM_SESSION_CLIPS,
        help = (
            "Recordings with fewer clips than this are dropped"
        ),
    )

    parser.add_argument(
        "--group",
        choices = GROUP_MODES,
        default = DEFAULT_GROUP_MODE,
        help = (
            "Unit that is held out in every fold. "
            "'session' leaves one recording session out, "
            "'hive' leaves one physical hive out"
        ),
    )

    parser.add_argument(
        "--normalization",
        choices = NORMALIZATION_MODES,
        default = DEFAULT_NORMALIZATION,
        help = (
            "'fixed' rescales -80 dB to 0 dB into 0 to 1, "
            "'clip' standardizes every spectrogram on its own, "
            "'cmvn' removes the per recording mean and standard "
            "deviation of every mel band"
        ),
    )

    parser.add_argument(
        "--no-augmentation",
        action = "store_true",
        help = (
            "It turns off masking, tilting and time shifting"
        ),
    )

    return parser.parse_args()


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


def build_predictions_path(
    dataset_name,
    hive_set,
    group_mode,
    normalization,
):
    """

    It gives every experiment variant its own prediction file so that
    compare_experiments.py can read all of them side by side

    """

    return (
        PROCESSED_DIR
        / (
            f"waggle_oof_predictions_"
            f"{dataset_name}_"
            f"{hive_set}_"
            f"{group_mode}_"
            f"{normalization}.npz"
        )
    )


def load_one_dataset(name):
    """

    It loads one prepared collection

    """

    path = DATASET_PATHS[name]

    if not path.exists():
        raise FileNotFoundError(
            f"Prepared dataset does not exist -- "
            f"{path}"
        )

    with np.load(
        path,
        allow_pickle = False,
    ) as dataset:
        return (
            dataset["X"].astype(
                np.float32,
                copy = False,
            ),
            dataset["y"].astype(
                np.int64,
                copy = False,
            ),
            dataset["hive_ids"],
            dataset["session_ids"],
        )


def load_dataset(
    dataset_name,
    hive_set,
    minimum_session_clips,
):
    """

    It loads the spectrograms and drops the recordings that are too
    short to carry a decision

    """

    names = (
        list(DATASET_PATHS)
        if dataset_name == "both"
        else [dataset_name]
    )

    parts = [
        load_one_dataset(name)
        for name in names
    ]

    X = np.concatenate(
        [part[0] for part in parts],
        axis = 0,
    )

    y = np.concatenate(
        [part[1] for part in parts]
    )

    hive_ids = np.concatenate(
        [part[2] for part in parts]
    ).astype(np.str_)

    session_ids = np.concatenate(
        [part[3] for part in parts]
    ).astype(np.str_)

    original_count = len(y)

    if hive_set == "nuhive":
        # Only Hive1 and Hive3 belong to the controlled NU-Hive experiment
        keep = np.isin(
            hive_ids,
            np.asarray(NUHIVE_HIVES),
        )

        X = X[keep]
        y = y[keep]
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

        X = X[keep]
        y = y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    if (
        len(y) != X.shape[0]
        or len(hive_ids) != len(y)
        or len(session_ids) != len(y)
    ):
        raise ValueError(
            "Feature, label, hive and session "
            "counts do not match"
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
        dropped_sessions,
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


def normalize_spectrograms(
    X,
    session_ids,
    normalization,
):
    """

    It rescales the log mel values before training

    'cmvn' subtracts the mean of every mel band inside one recording
    session and divides by its standard deviation. A constant microphone
    response, a mains hum or a steady background noise is identical in
    every clip of that recording, so this removes the recording
    fingerprint while keeping how the sound changes over time

    Only the audio of a session is used, never its label, so the same
    step can run on the device using the first minutes of its own
    recording

    """

    X = X.astype(
        np.float32,
        copy = True,
    )

    if normalization == "fixed":
        # Log mel values are expected to be approximately between -80 dB and 0 dB
        np.clip(
            X,
            -80.0,
            0.0,
            out = X,
        )

        X += 80.0
        X /= 80.0

        return X

    if normalization == "clip":
        clip_means = X.mean(
            axis = (1, 2),
            keepdims = True,
        )

        clip_deviations = X.std(
            axis = (1, 2),
            keepdims = True,
        )

        X -= clip_means
        X /= clip_deviations + 1e-6

        return X

    if normalization == "cmvn":
        for session_id in np.unique(
            session_ids
        ):
            mask = session_ids == session_id

            # One mean and one standard deviation per mel band,
            # shared by every clip of this recording
            band_means = X[mask].mean(
                axis = (0, 2),
                keepdims = True,
            )

            band_deviations = X[mask].std(
                axis = (0, 2),
                keepdims = True,
            )

            X[mask] = (
                X[mask] - band_means
            ) / (band_deviations + 1e-6)

        return X

    raise ValueError(
        f"Unknown normalization mode -- "
        f"{normalization}"
    )


def describe_sessions(
    y,
    hive_ids,
    session_ids,
):
    """

    It prints one row per recording session and warns when the label is
    perfectly explained by the session

    """

    print()
    print(
        "Recording sessions:"
    )

    print(
        f"{'session_id':<34} "
        f"{'hive':<8} "
        f"{'label':<11} "
        f"{'clips':>7}"
    )

    print("-" * 62)

    session_labels = {}

    for session_id in np.unique(
        session_ids
    ):
        mask = session_ids == session_id

        session_label_values = np.unique(
            y[mask]
        )

        if len(session_label_values) != 1:
            raise RuntimeError(
                f"Session {session_id} contains "
                f"more than one label"
            )

        label = int(
            session_label_values[0]
        )

        session_labels[
            session_id
        ] = label

        hive_id = np.unique(
            hive_ids[mask]
        )[0]

        print(
            f"{session_id:<34} "
            f"{hive_id:<8} "
            f"{CLASS_NAMES[label]:<11} "
            f"{int(np.sum(mask)):>7}"
        )

    session_count = len(session_labels)

    healthy_sessions = sum(
        1
        for label in session_labels.values()
        if label == HEALTHY_ID
    )

    print()

    print(
        f"Independent recordings: "
        f"{session_count} "
        f"({healthy_sessions} healthy, "
        f"{session_count - healthy_sessions} queenless)"
    )

    print(
        "Every session carries exactly one label, so the effective "
        f"sample size is {session_count}, not {len(y)}."
    )

    return session_labels


def create_group_splits(
    y,
    groups,
    group_mode,
):
    """

    It builds one fold per group and keeps every fold whose training
    part contains both classes

    The held out part is allowed to contain a single class. A recording
    of a hive that was always queenless is still a valid question: did
    the model call this recording queenless or not. Only the pooled
    balanced accuracy of such a fold is undefined, not its decision

    """

    splits = []
    skipped_groups = []

    for group in np.unique(groups):
        test_indices = np.flatnonzero(
            groups == group
        )

        train_indices = np.flatnonzero(
            groups != group
        )

        train_healthy, train_queenless = (
            count_classes(
                y[train_indices]
            )
        )

        if (
            train_healthy == 0
            or train_queenless == 0
        ):
            skipped_groups.append(
                str(group)
            )

            continue

        splits.append(
            (
                train_indices,
                test_indices,
                str(group),
            )
        )

    if not splits:
        raise RuntimeError(
            f"No leave one {group_mode} out fold "
            f"has both classes in its training part"
        )

    return (
        splits,
        skipped_groups,
    )


def print_split_table(
    y,
    hive_ids,
    splits,
    skipped_groups,
    group_mode,
):
    """

    It prints the accepted folds and marks the folds where the held out
    recording comes from a hive that is also present in training

    """

    print()

    print(
        f"Leave one {group_mode} out folds:"
    )

    print(
        f"{'fold':>4} "
        f"{'held out':<34} "
        f"{'train H':>8} "
        f"{'train Q':>8} "
        f"{'test':>7} "
        f"{'test cls':>9} "
        f"{'hive leak':>10}"
    )

    print("-" * 88)

    for fold_number, (
        train_indices,
        test_indices,
        group,
    ) in enumerate(
        splits,
        start = 1,
    ):
        train_healthy, train_queenless = (
            count_classes(
                y[train_indices]
            )
        )

        test_hives = set(
            hive_ids[test_indices].tolist()
        )

        train_hives = set(
            hive_ids[train_indices].tolist()
        )

        leaks = bool(
            test_hives & train_hives
        )

        print(
            f"{fold_number:>4} "
            f"{group:<34} "
            f"{train_healthy:>8} "
            f"{train_queenless:>8} "
            f"{len(test_indices):>7} "
            f"{len(np.unique(y[test_indices])):>9} "
            f"{('yes' if leaks else 'no'):>10}"
        )

    for group in skipped_groups:
        print(
            f"{'--':>4} "
            f"{group:<34} "
            f"{'--':>8} "
            f"{'--':>8} "
            f"{'--':>7} "
            f"{'--':>9} "
            f"{'skipped':>10}"
        )

    print()

    print(
        "hive leak = the held out recording belongs to a hive that is "
        "also in the training part, so its result is optimistic."
    )

    print(
        "test cls = number of true classes in the held out part. One "
        "class is fine, its decision still counts."
    )

    if skipped_groups:
        print(
            "skipped = holding this group out would leave the "
            "training part with a single class."
        )


def choose_validation_sessions(
    y,
    session_ids,
    train_indices,
):
    """

    It picks one healthy and one queenless training session for early
    stopping

    A single session only contains one class, so balanced accuracy needs
    at least two validation sessions. It returns an empty list when the
    remaining training part would lose a class, which means that this
    fold cannot select a model honestly

    """

    train_sessions = np.unique(
        session_ids[train_indices]
    )

    sessions_by_class = {
        HEALTHY_ID: [],
        QUEENLESS_ID: [],
    }

    for session_id in train_sessions:
        mask = (
            session_ids == session_id
        )

        label = int(
            np.unique(y[mask])[0]
        )

        clip_count = int(
            np.sum(
                session_ids[train_indices]
                == session_id
            )
        )

        sessions_by_class[label].append(
            (
                clip_count,
                str(session_id),
            )
        )

    validation_sessions = []

    for label in (
        HEALTHY_ID,
        QUEENLESS_ID,
    ):
        candidates = sessions_by_class[
            label
        ]

        # Removing a session from a class that only has one session
        # would empty that class in the remaining training part
        if len(candidates) < 2:
            return []

        # A tiny recording gives a meaningless early stopping signal,
        # so it is only used when nothing larger is available
        large_enough = [
            candidate
            for candidate in candidates
            if candidate[0]
            >= MINIMUM_VALIDATION_CLIPS
        ]

        if not large_enough:
            return []

        # The smallest usable session is chosen so that training keeps
        # most of its clips
        validation_sessions.append(
            min(large_enough)[1]
        )

    return validation_sessions


def apply_augmentation(
    spectrogram,
    generator,
):
    """

    It randomly hides parts of the spectrogram and changes its spectral
    slope so that the model cannot memorize one recording

    """

    band_count, frame_count = (
        spectrogram.shape
    )

    if TIME_SHIFT_ENABLED:
        shift = int(
            generator.integers(
                0,
                frame_count,
            )
        )

        spectrogram = np.roll(
            spectrogram,
            shift,
            axis = 1,
        )

    # The tilt is scaled by the spread of this clip so that the same
    # setting works for every normalization mode
    tilt_scale = float(
        spectrogram.std()
    )

    tilt = float(
        generator.uniform(
            -SPECTRAL_TILT_LIMIT,
            SPECTRAL_TILT_LIMIT,
        )
    )

    ramp = np.linspace(
        -1.0,
        1.0,
        band_count,
        dtype = np.float32,
    )

    spectrogram = spectrogram + (
        ramp[:, None]
        * tilt
        * tilt_scale
    )

    for _ in range(
        FREQUENCY_MASK_COUNT
    ):
        width = int(
            generator.integers(
                0,
                FREQUENCY_MASK_WIDTH + 1,
            )
        )

        if width == 0:
            continue

        start = int(
            generator.integers(
                0,
                band_count - width + 1,
            )
        )

        spectrogram[
            start : start + width,
            :,
        ] = 0.0

    for _ in range(TIME_MASK_COUNT):
        width = int(
            generator.integers(
                0,
                TIME_MASK_WIDTH + 1,
            )
        )

        if width == 0:
            continue

        start = int(
            generator.integers(
                0,
                frame_count - width + 1,
            )
        )

        spectrogram[
            :,
            start : start + width,
        ] = 0.0

    return spectrogram


class SpectrogramDataset(Dataset):
    """

    It gives the CNN one already normalized spectrogram and its label

    """

    def __init__(
        self,
        X,
        y,
        indices,
        augment = False,
    ):
        self.X = X
        self.y = y

        self.indices = np.asarray(
            indices
        )

        self.augment = augment

        self.generator = (
            np.random.default_rng(
                RANDOM_SEED
            )
        )

    def __len__(self):
        return len(self.indices)

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

        if self.augment:
            spectrogram = (
                apply_augmentation(
                    spectrogram.copy(),
                    self.generator,
                )
            )

        spectrogram = np.ascontiguousarray(
            spectrogram,
            dtype = np.float32,
        )

        spectrogram_tensor = (
            torch.from_numpy(
                spectrogram
            ).unsqueeze(0)
        )

        label_tensor = torch.tensor(
            int(
                self.y[dataset_index]
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

    healthy_count, queenless_count = (
        count_classes(
            y[train_indices]
        )
    )

    total_count = (
        healthy_count
        + queenless_count
    )

    weights = torch.tensor(
        [
            total_count
            / (2 * healthy_count),
            total_count
            / (2 * queenless_count),
        ],
        dtype = torch.float32,
        device = device,
    )

    return weights


def evaluate_model(
    model,
    X,
    y,
    indices,
    device,
):
    """

    It returns the predictions and the queenless probabilities of the
    given clips

    """

    dataset = SpectrogramDataset(
        X,
        y,
        indices,
        augment = False,
    )

    loader = DataLoader(
        dataset,
        batch_size = BATCH_SIZE,
        shuffle = False,
        num_workers = 0,
    )

    predictions = []
    probabilities = []

    model.eval()

    with torch.no_grad():
        for (
            spectrograms,
            _,
        ) in loader:
            spectrograms = spectrograms.to(
                device
            )

            outputs = model(spectrograms)

            batch_probabilities = (
                torch.softmax(
                    outputs,
                    dim = 1,
                )
            )

            predictions.extend(
                outputs.argmax(dim = 1)
                .cpu()
                .numpy()
                .tolist()
            )

            probabilities.extend(
                batch_probabilities[
                    :,
                    QUEENLESS_ID,
                ]
                .cpu()
                .numpy()
                .tolist()
            )

    return (
        np.asarray(
            predictions,
            dtype = np.int64,
        ),
        np.asarray(
            probabilities,
            dtype = np.float32,
        ),
    )


def train_one_fold(
    X,
    y,
    inner_train_indices,
    validation_indices,
    device,
    augment,
):
    """

    It trains one CNN and keeps the epoch with the best validation
    balanced accuracy

    When there is no usable validation split it trains for a fixed
    number of epochs and keeps the last one

    """

    training_dataset = SpectrogramDataset(
        X,
        y,
        inner_train_indices,
        augment = augment,
    )

    training_loader = DataLoader(
        training_dataset,
        batch_size = BATCH_SIZE,
        shuffle = True,
        num_workers = 0,
    )

    model = SmallCNN().to(device)

    loss_function = nn.CrossEntropyLoss(
        weight = calculate_class_weights(
            y,
            inner_train_indices,
            device,
        )
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr = LEARNING_RATE,
        weight_decay = WEIGHT_DECAY,
    )

    has_validation = (
        len(validation_indices) > 0
    )

    epoch_limit = (
        MAX_EPOCHS
        if has_validation
        else FALLBACK_EPOCHS
    )

    best_score = -1.0
    best_epoch = 0
    best_state = None
    epochs_without_progress = 0

    training_start_time = (
        time.perf_counter()
    )

    for epoch_number in range(
        1,
        epoch_limit + 1,
    ):
        model.train()

        total_loss = 0.0
        sample_count = 0

        for (
            spectrograms,
            labels,
        ) in training_loader:
            spectrograms = spectrograms.to(
                device
            )

            labels = labels.to(device)

            optimizer.zero_grad()

            outputs = model(spectrograms)

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

            sample_count += labels.size(0)

        epoch_loss = (
            total_loss
            / sample_count
        )

        if not has_validation:
            print(
                f"    Epoch "
                f"{epoch_number:>2}/{epoch_limit} "
                f"| loss: {epoch_loss:.4f}"
            )

            continue

        validation_predictions, _ = (
            evaluate_model(
                model,
                X,
                y,
                validation_indices,
                device,
            )
        )

        validation_score = (
            balanced_accuracy_score(
                y[validation_indices],
                validation_predictions,
            )
        )

        improved = (
            validation_score > best_score
        )

        if improved:
            best_score = validation_score
            best_epoch = epoch_number

            best_state = copy.deepcopy(
                model.state_dict()
            )

            epochs_without_progress = 0

        else:
            epochs_without_progress += 1

        print(
            f"    Epoch "
            f"{epoch_number:>2}/{epoch_limit} "
            f"| loss: {epoch_loss:.4f} "
            f"| validation balanced: "
            f"{validation_score:.4f}"
            f"{'  <- best' if improved else ''}"
        )

        if (
            epochs_without_progress
            >= EARLY_STOPPING_PATIENCE
        ):
            print(
                f"    Early stopping after "
                f"{epoch_number} epochs"
            )

            break

    if best_state is not None:
        model.load_state_dict(best_state)

    training_seconds = (
        time.perf_counter()
        - training_start_time
    )

    print(
        f"    Fold training time: "
        f"{format_duration(training_seconds)}"
    )

    if has_validation:
        print(
            f"    Selected epoch: "
            f"{best_epoch} "
            f"(validation balanced "
            f"{best_score:.4f})"
        )

    return model


def run_cross_validation(
    X,
    y,
    session_ids,
    splits,
    device,
    augment,
):
    """

    It trains one model per fold and collects the out of fold
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

    folds_without_validation = []

    print()
    print(f"Training device: {device}")
    print()

    start_time = time.perf_counter()

    for fold_number, (
        train_indices,
        test_indices,
        group,
    ) in enumerate(
        splits,
        start = 1,
    ):
        print(
            f"Fold {fold_number}/{len(splits)} "
            f"-- held out: {group}"
        )

        validation_sessions = (
            choose_validation_sessions(
                y,
                session_ids,
                train_indices,
            )
        )

        if validation_sessions:
            validation_mask = np.isin(
                session_ids[train_indices],
                validation_sessions,
            )

            validation_indices = (
                train_indices[
                    validation_mask
                ]
            )

            inner_train_indices = (
                train_indices[
                    ~validation_mask
                ]
            )

            print(
                f"    Validation sessions: "
                f"{', '.join(validation_sessions)}"
            )

        else:
            validation_indices = np.array(
                [],
                dtype = np.int64,
            )

            inner_train_indices = (
                train_indices
            )

            folds_without_validation.append(
                group
            )

            print(
                "    No two class validation "
                "split is possible, training for "
                f"{FALLBACK_EPOCHS} fixed epochs"
            )

        set_random_seed()

        model = train_one_fold(
            X,
            y,
            inner_train_indices,
            validation_indices,
            device,
            augment,
        )

        (
            fold_predictions,
            fold_probabilities,
        ) = evaluate_model(
            model,
            X,
            y,
            test_indices,
            device,
        )

        predictions[
            test_indices
        ] = fold_predictions

        probabilities[
            test_indices
        ] = fold_probabilities

        fold_ids[
            test_indices
        ] = fold_number

        print(
            f"    Held out accuracy: "
            f"{accuracy_score(y[test_indices], fold_predictions):.4f}"
        )

        if len(
            np.unique(y[test_indices])
        ) > 1:
            print(
                f"    Held out balanced accuracy: "
                f"{balanced_accuracy_score(y[test_indices], fold_predictions):.4f}"
            )

        print(
            f"    Held out mean queenless "
            f"probability: "
            f"{float(np.mean(fold_probabilities)):.4f}"
        )

        print()

        del model

        if device.type == "mps":
            torch.mps.empty_cache()

        if device.type == "cuda":
            torch.cuda.empty_cache()

    print(
        f"Complete training time: "
        f"{format_duration(time.perf_counter() - start_time)}"
    )

    return (
        predictions,
        probabilities,
        fold_ids,
        folds_without_validation,
    )


def print_clip_results(
    y,
    predictions,
):
    """

    It reports the pooled clip level result

    Clips of one recording are strongly correlated, so this number looks
    far more precise than it really is. It is kept only for comparison
    with the earlier experiments

    """

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

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            y,
            predictions,
            labels = [QUEENLESS_ID],
            average = None,
            zero_division = 0,
        )
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


def print_session_results(
    y,
    predictions,
    probabilities,
    hive_ids,
    session_ids,
):
    """

    It aggregates the clip predictions into one decision per recording
    and reports the primary metric

    The product decides once per hive per day, not once per five second
    clip, so this is the number that matters

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

    session_truth = []
    session_decisions = []

    for session_id in np.unique(
        session_ids
    ):
        mask = session_ids == session_id

        true_label = int(
            np.unique(y[mask])[0]
        )

        # The median is robust against a few very loud or very quiet clips
        median_probability = float(
            np.median(
                probabilities[mask]
            )
        )

        decision = (
            QUEENLESS_ID
            if median_probability > 0.5
            else HEALTHY_ID
        )

        session_truth.append(true_label)
        session_decisions.append(decision)

        correct = decision == true_label

        print(
            f"{session_id:<34} "
            f"{np.unique(hive_ids[mask])[0]:<8} "
            f"{CLASS_NAMES[true_label]:<11} "
            f"{int(np.sum(mask)):>7} "
            f"{accuracy_score(y[mask], predictions[mask]):>9.4f} "
            f"{median_probability:>9.4f} "
            f"{CLASS_NAMES[decision]:<11} "
            f"{('yes' if correct else 'no'):>3}"
        )

    session_truth = np.asarray(
        session_truth
    )

    session_decisions = np.asarray(
        session_decisions
    )

    correct_count = int(
        np.sum(
            session_truth
            == session_decisions
        )
    )

    print()

    print(
        f"Sessions correct: "
        f"{correct_count}/{len(session_truth)}"
    )

    print(
        f"Session level accuracy: "
        f"{accuracy_score(session_truth, session_decisions):.4f}"
    )

    if len(
        np.unique(session_truth)
    ) > 1:
        print(
            f"Session level balanced accuracy: "
            f"{balanced_accuracy_score(session_truth, session_decisions):.4f}"
        )

    print()

    print(
        f"Warning: this metric has only "
        f"{len(session_truth)} independent samples. "
        f"One flipped session changes it by "
        f"{1 / len(session_truth):.2f}. "
        f"Do not read it as a percentage."
    )


def save_predictions(
    predictions_path,
    y,
    predictions,
    probabilities,
    hive_ids,
    session_ids,
    fold_ids,
):
    """

    It saves the out of fold predictions in the format that
    compare_experiments.py reads

    """

    predictions_path.parent.mkdir(
        parents = True,
        exist_ok = True,
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

    print()

    print(
        f"Predictions saved to: "
        f"{predictions_path}"
    )


def main():
    program_start_time = (
        time.perf_counter()
    )

    arguments = parse_arguments()

    augment = not arguments.no_augmentation

    predictions_path = (
        build_predictions_path(
            arguments.dataset,
            arguments.hives,
            arguments.group,
            arguments.normalization,
        )
    )

    set_random_seed()

    (
        X,
        y,
        hive_ids,
        session_ids,
        original_count,
        dropped_sessions,
    ) = load_dataset(
        arguments.dataset,
        arguments.hives,
        arguments.min_clips,
    )

    healthy_count, queenless_count = (
        count_classes(y)
    )

    print(f"Dataset: {arguments.dataset}")

    print(
        f"Experiment: leave one "
        f"{arguments.group} out"
    )

    print(
        f"Hive set: {arguments.hives} "
        f"({len(np.unique(hive_ids))} hives)"
    )

    print(
        f"Normalization: "
        f"{arguments.normalization}"
    )

    print(
        f"Augmentation: "
        f"{'on' if augment else 'off'}"
    )

    print(
        f"Original clean clips: "
        f"{original_count}"
    )

    print(
        f"Selected clips: {len(y)}"
    )

    for name, clip_count in (
        dropped_sessions
    ):
        print(
            f"Dropped recording {name} -- "
            f"only {clip_count} clips "
            f"(minimum {arguments.min_clips})"
        )

    print(
        f"Spectrogram shape: {X.shape}"
    )

    print(
        f"Healthy clips: {healthy_count}"
    )

    print(
        f"Queenless clips: "
        f"{queenless_count}"
    )

    describe_sessions(
        y,
        hive_ids,
        session_ids,
    )

    X = normalize_spectrograms(
        X,
        session_ids,
        arguments.normalization,
    )

    groups = (
        session_ids
        if arguments.group == "session"
        else hive_ids
    )

    (
        splits,
        skipped_groups,
    ) = create_group_splits(
        y,
        groups,
        arguments.group,
    )

    print_split_table(
        y,
        hive_ids,
        splits,
        skipped_groups,
        arguments.group,
    )

    device = choose_device()

    (
        predictions,
        probabilities,
        fold_ids,
        folds_without_validation,
    ) = run_cross_validation(
        X,
        y,
        session_ids,
        splits,
        device,
        augment,
    )

    # A skipped group never becomes a test set, so its clips have no out
    # of fold prediction and must stay out of the reported numbers
    covered = fold_ids != -1

    if not np.all(covered):
        print()

        print(
            f"Clips without an out of fold "
            f"prediction: "
            f"{int(np.sum(~covered))} "
            f"(their group was skipped)"
        )

    y = y[covered]
    predictions = predictions[covered]
    probabilities = probabilities[covered]
    hive_ids = hive_ids[covered]
    session_ids = session_ids[covered]
    fold_ids = fold_ids[covered]

    print_clip_results(
        y,
        predictions,
    )

    print_session_results(
        y,
        predictions,
        probabilities,
        hive_ids,
        session_ids,
    )

    if folds_without_validation:
        print()

        print(
            "Folds without an honest model "
            "selection split: "
            f"{', '.join(folds_without_validation)}"
        )

        print(
            "These folds used a fixed epoch count because the "
            "training part had only one recording of a class."
        )

    save_predictions(
        predictions_path,
        y,
        predictions,
        probabilities,
        hive_ids,
        session_ids,
        fold_ids,
    )

    print(
        f"Total program time: "
        f"{format_duration(time.perf_counter() - program_start_time)}"
    )


if __name__ == "__main__":
    main()
