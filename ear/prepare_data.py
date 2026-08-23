# ** -- Unknown formats must never be silently skipped because that could introduce incorrect labels or unnoticed data loss ** -- 

from pathlib import Path
import warnings
import librosa
import re # regex
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tobee"

SUPPORTED_EXTENSIONS = {".wav", ".mp3"}

ANNOTATION_ROUNDING_TOLERANCE = 0.05

SAMPLE_RATE = 22050
CLIP_SECONDS = 5
CLIP_SAMPLES = SAMPLE_RATE * CLIP_SECONDS

NUM_OF_FFT = 2048 # Number of Fast Fourier Transforms
HOP_LENGTH = 512 # How much to investigate the audio signal in each step
NUM_OF_MELS = 128 
FMAX = 2000
EXPECTED_MEL_SHAPE = (128, 216) # row, column

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent # file is which currently running, resolve() gets the absolute path, parent.parent gets the grandparent directory
    / "data"
    / "processed"
    / "waggle_mels_cleaned.npz"
)

LABEL_TO_ID = {
    "healthy": 0,
    "queenless": 1,
}

ID_TO_LABEL = np.array(
    ["healthy", "queenless"],
    dtype = np.str_,
)

def parse_filename(path):
    """

    It extracts the queen state label, physical hive ID and recording session ID from a supported audio filename

    It returns:
        tuple: (label, hive_id, session_id)

    """

    filename = path.name
    stem = path.stem # It retrieves the filename from a file path without it extension
    # suffix would get the extension like ".wav" or ".mp3", but we don't need it here

    # According to the documentation of the "To Bee or Not To Bee":
  # ********************************       *********************************
    
    # NU-Hive filename example: Hive1_31_05_2018_NO_QueenBee_H1_audio___15_20_00.wav

    # Captured components:
    # hive_id: Hive1
    # date: 31_05_2018
    # state: NO_QueenBee
  
    # Sensor and recording time are intentionally excluded from session_id

  # ********************************       *********************************

    hive_match = re.match(
        r"^(?P<hive_id>Hive\d+)_" # r = raw string, ^ = start from the string, ?P = named group, /d = digit, + = one or more digits in our case, then an underscore should come and give it the name of hive_id
        r"(?P<date>\d{2}_\d{2}_\d{4})_" # { ..} represents the num of digits, so 2 digits for day, 2 digits for month and 4 digits for year then an underscore should come
        r"(?P<state>NO_QueenBee|QueenBee)_", # | or op
        stem, # file name without extension
        flags= re.IGNORECASE,
    )

    if hive_match: # parse the components that are retrieved from there regex match to variables
        hive_id = hive_match.group("hive_id")
        date = hive_match.group("date")
        state = hive_match.group("state")

        if state.lower() == "no_queenbee": # lower to lowercase
            label = "queenless"
        elif state.lower() == "queenbee":
            label = "healthy"
        else:
            raise ValueError(
                f"Unknown queen state in filename: {filename}"
            )

        session_id = f"{hive_id}_{date}_{state}"

        return label, hive_id, session_id

    # OSBH filename examples according to the documentation of the "To Bee or Not To Bee":

    # CF003 - Active - Day - (217).wav
    # CJ001 - Missing Queen - Day - (100).wav

    coded_match = re.match(
        r"^(?P<hive_id>[A-Za-z]{2}\d{3})" # [A-Za-z] means any letter capital or lowercase
        r"\s*-\s*" # \s* = zero or more whitespace characters
        r"(?P<state>Active|Missing Queen)"
        r"\s*-",
        stem,
        flags= re.IGNORECASE,
    )

    if coded_match:
        hive_id = coded_match.group("hive_id").upper()
        state = coded_match.group("state").lower()

        if state == "missing queen":
            label = "queenless"
        elif state == "active":
            # TODO: ** -- IMPORTANT -- ** Verify this mapping using the original OSBH metadata in the future ** -- IMPORTANT -- **
            label = "healthy"
        else:
            raise ValueError(
                f"Unknown queen state in filename: {filename}"
            )
        session_id = hive_id # According to the documentation each coded hive in the current local subset represents one session

        return label, hive_id, session_id

    raise ValueError(f"Unknown filename format: {filename}")

def find_audio_files():
    """

    It finds the supported audio files recursively under data/tobee

    """

    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"The data directory does not exist that {DATA_DIR}"
        )

    audio_files = sorted(
        path
        for path in DATA_DIR.rglob("*") # rglob() method is used to recursively search for files in a directory and its subdirectories that match a specified pattern. In this case the pattern is "*" which means it will match all files and directories
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not audio_files:
        raise FileNotFoundError(
            f"No supported audio files found in {DATA_DIR}"
        )

    return audio_files

def validate_session_labels(parsed_files):
    """

    It verifies that one recording session never receives conflicting labels like it cannot be both healthy and queenless at the same time

    """

    labels_by_session = {}

    for _, label, _, session_id in parsed_files: # filename, label, hive_id, session_id
        previous_label = labels_by_session.get(session_id)

        if previous_label is not None and previous_label != label:
            raise ValueError(
                f"Conflicting labels for session {session_id}: "
                f"{previous_label} and {label}"
            )

        labels_by_session[session_id] = label

def validate_audio_filenames():
    """

    It parses every audio filename, validates session labels and prints an inventory

    """

    audio_files = find_audio_files()

    parsed_files = []

    for path in audio_files:
        label, hive_id, session_id = parse_filename(path)
        parsed_files.append((path, label, hive_id, session_id))

    validate_session_labels(parsed_files)

    hive_ids = {
        hive_id
        for _, _, hive_id, _ in parsed_files
    }

    session_ids = {
        session_id
        for _, _, _, session_id in parsed_files
    }

    print(
        f"{'filename':<65} " # :<65 means the filename will be left aligned and take up 65 characters of space
        f"{'label':<12} "
        f"{'hive_id':<10} "
        f"{'session_id'}"
    )
    print("-" * 125) # 125 dashes to match the total width of the columns

    for path, label, hive_id, session_id in parsed_files:
        print(
            f"{path.name:<65} "
            f"{label:<12} "
            f"{hive_id:<10} "
            f"{session_id}"
        )

    print()
    print(f"Total files: {len(parsed_files)}")
    print(f"Unique hives: {len(hive_ids)}")
    print(f"Unique sessions: {len(session_ids)}")

def load_audio(path):
    """

    It loads one audio recording as mono audio at a fixed sample rate

    """

    try:
        y, sr = librosa.load(
            path, # The sound file path that is going to get loaded
            sr = SAMPLE_RATE,
            mono= True, # Converts the audio to one channel that is mono in case if it is stereo or multi channeled
        )

    except Exception as error:
        raise RuntimeError(
            f"Could not load audio file: {path.name}"
        ) from error # The source

    if len(y) == 0:
        raise ValueError(f"Audio file is empty: {path.name}")

    if sr != SAMPLE_RATE:
        raise ValueError(
            f"Unexpected sample rate for {path.name}: {sr}"
        )

    return y, sr

def split_into_clips(y):
    """

    It yields full 5 second clips from an audio array The incomplete remainder at the end is intentionally discarded

    """

    for start in range( # start, finish, step
        0,
        len(y) - CLIP_SAMPLES + 1,
        CLIP_SAMPLES
    ):

        end = start + CLIP_SAMPLES
        yield y[start:end] # Gives the audio clip from the start index to the end index that is 5 seconds long

def read_lab_intervals(audio_path):
    """

    It reads the bee / noBee time intervals that are linked with one audio file

    It returns a list of tuples as (start_seconds, end_seconds, label)

    """

    lab_path = audio_path.with_suffix(".lab")

    if not lab_path.exists():
        raise FileNotFoundError(
            f"Missing .lab file for {audio_path.name}"
        )

    lines = lab_path.read_text(
        encoding = "utf-8-sig" # Gets rid of BOM in case if exists at the beginning of the file for using UTF 8 encoding
    ).splitlines()

    if len(lines) < 2:
        raise ValueError(
            f"Invalid or empty .lab file: {lab_path.name}"
        )

    intervals = []

    # The first line identifies the audio file, so interval parsing is going to start from the second line

    for line_number, line in enumerate(lines[1:], start = 2): # start gives each line number starting from 2 because the first line is skipped
        line = line.strip() # It cleans the unnecessary whitespace characters from the beginning and end of the line

        if not line or line == ".":
            continue

        parts = line.split()

        if len(parts) != 3:
            raise ValueError(
                f"Invalid line in {lab_path.name} "
                f"at line {line_number}: {line}"
            )

        start_text, end_text, interval_label = parts

        try:
            start_seconds = float(start_text)
            end_seconds = float(end_text)

        except ValueError as error:
            raise ValueError(
                f"Invalid time value in {lab_path.name} "
                f"at line {line_number}: {line}"
            ) from error

        interval_label = interval_label.lower()

        if interval_label not in {"bee", "nobee"}:
            raise ValueError(
                f"Unknown interval label in {lab_path.name} "
                f"at line {line_number}: {interval_label}"
            )

        if start_seconds < 0:

            raise ValueError(
                f"Negative start time in {lab_path.name} "
                f"at line {line_number}: {line}"
            )

        if end_seconds < start_seconds:
            difference = start_seconds - end_seconds

            if difference <= ANNOTATION_ROUNDING_TOLERANCE:
                warnings.warn(
                    f"Correcting a small annotation rounding error "
                    f"in {lab_path.name} at line {line_number}: "
                    f"{start_seconds} -> {end_seconds}"
                )

                end_seconds = start_seconds
            else:
                raise ValueError(
                    f"Invalid interval in {lab_path.name} "
                    f"at line {line_number}: {line}"
                )

        intervals.append(
            (start_seconds, end_seconds, interval_label)
        )

    if not intervals:
        raise ValueError(
            f"No annotation intervals found in: {lab_path.name}"
        )

    return intervals

def clip_overlaps_nobee(
    clip_start,
    clip_end,
    intervals,
):
    
    """

    It returns "True" when a clip overlaps any noBee interval

    """

    for interval_start, interval_end, interval_label in intervals:
        if interval_label != "nobee":
            continue

        overlaps = (
            clip_start < interval_end
            and interval_start < clip_end
        )

        if overlaps:
            return True

    return False

def inspect_audio_clips():
    """

    It loads every recording and count clean clips and clips that overlap noBee

    """

    audio_files = find_audio_files()

    total_duration_seconds = 0.0
    total_clips = 0
    clean_clips = 0
    nobee_clips = 0

    total_by_label = {
        "healthy": 0,
        "queenless": 0,
    }

    clean_by_label = {
        "healthy": 0,
        "queenless": 0,
    }

    nobee_by_label = {
        "healthy": 0,
        "queenless": 0,
    }

    print(
        f"{'filename':<65} " # :<65 means the filename will be left aligned and take up 65 characters of space
        f"{'label':<12} "
        f"{'duration':>10} "
        f"{'total':>7} "
        f"{'clean':>7} "
        f"{'nobee':>7}"
    )

    print("-" * 120)

    for path in audio_files:
        label, hive_id, session_id = parse_filename(path)

        y, sr = load_audio(path)
        
        intervals = read_lab_intervals(path)

        duration_seconds = len(y) / sr

        file_total = 0
        file_clean = 0
        file_nobee = 0

        for clip_index, _ in enumerate(split_into_clips(y)):
            clip_start = clip_index * CLIP_SECONDS
            clip_end = clip_start + CLIP_SECONDS

            file_total += 1

            if clip_overlaps_nobee(clip_start, clip_end, intervals):
                file_nobee += 1
            else:
                file_clean += 1

        if file_clean + file_nobee != file_total:
            raise RuntimeError(
                f"Clip counting mismatch for: {path.name}"
            )

        total_duration_seconds += duration_seconds
        total_clips += file_total
        clean_clips += file_clean
        nobee_clips += file_nobee

        total_by_label[label] += file_total
        clean_by_label[label] += file_clean
        nobee_by_label[label] += file_nobee

        print(
            f"{path.name:<65} "
            f"{label:<12} "
            f"{duration_seconds:>9.1f}s "
            f"{file_total:>7} "
            f"{file_clean:>7} "
            f"{file_nobee:>7}"
        )

    if clean_clips + nobee_clips != total_clips:
        raise RuntimeError(
            "Total clean and noBee counts do not match."
        )

    print()
    print(f"Clip size: {CLIP_SAMPLES} samples")
    print(
        f"Total duration: "
        f"{total_duration_seconds / 3600:.2f} hours"
    )
    print(f"Total full clips: {total_clips}")
    print(f"Clean bee clips: {clean_clips}")
    print(f"Clips overlapping noBee: {nobee_clips}")

    print()
    print("By queen-state label:")
    print(
        f"Healthy: total={total_by_label['healthy']}, "
        f"clean={clean_by_label['healthy']}, "
        f"nobee={nobee_by_label['healthy']}"
    )
    print(
        f"Queenless: total={total_by_label['queenless']}, "
        f"clean={clean_by_label['queenless']}, "
        f"nobee={nobee_by_label['queenless']}"
    )

    return clean_clips

def clip_to_log_mel(clip):
    """
    
    It converts one 5 second audio clip into a float32 log mel spectrogram

    """

    if len(clip) != CLIP_SAMPLES:
        raise ValueError(
            f"Expected {CLIP_SAMPLES} samples, got {len(clip)}"
        )

    mel = librosa.feature.melspectrogram(
        y = clip,
        sr = SAMPLE_RATE,
        n_fft = NUM_OF_FFT,
        hop_length = HOP_LENGTH,
        n_mels = NUM_OF_MELS,
        fmax = FMAX,
        power = 2.0, # Use power instead of amplitude as power = (amplitude)^2
    )

    mel_db = librosa.power_to_db(
        mel,
        ref = np.max, # Get the reference value from the maximum value of the power from the spectrogram (below negative and upper positive)
    ).astype(np.float32) # It consumes less memory. Machine learning models often expect float32 and ensure all inputs are of the same data type

    if mel_db.shape != EXPECTED_MEL_SHAPE:
        raise ValueError(
            f"Unexpected spectrogram shape: {mel_db.shape} "
            f"Expected: {EXPECTED_MEL_SHAPE}"
        )

    if not np.isfinite(mel_db).all(): # isfinite() if normal than true, not makes it false
        raise ValueError(
            "Spectrogram contains NaN or infinite values"
        )

    return mel_db

def test_first_clean_spectrogram():
    """

    It finds the first clean clip and verifies its log mel spectrogram

    """

    audio_files = find_audio_files()

    for path in audio_files:
        label, hive_id, session_id = parse_filename(path)
        y, sr = load_audio(path)
        intervals = read_lab_intervals(path)

        for clip_index, clip in enumerate(split_into_clips(y)):
            clip_start = clip_index * CLIP_SECONDS
            clip_end = clip_start + CLIP_SECONDS

            if clip_overlaps_nobee( # check the overcollapse
                clip_start,
                clip_end,
                intervals,
            ):
                continue # if yes then pass and get to the next clip

            mel_db = clip_to_log_mel(clip)

            print()
            print("First clean spectrogram test passed:")
            print(f"  source file : {path.name}")
            print(f"  label       : {label}")
            print(f"  hive_id     : {hive_id}")
            print(f"  session_id  : {session_id}")
            print(f"  clip index  : {clip_index}")
            print(f"  clip start  : {clip_start:.1f}s") # : formatting settings
            print(f"  audio shape : {clip.shape}")
            print(f"  mel shape   : {mel_db.shape}")
            print(f"  dtype       : {mel_db.dtype}") # data type
            print(f"  min dB      : {mel_db.min():.2f}")
            print(f"  max dB      : {mel_db.max():.2f}")

            return

    raise RuntimeError(
        "No clean 5 second clip was found in the dataset"
    )

def build_and_save_clean_dataset(expected_clean_count):
    """

    It generates log <> mel spectrograms for all clean clips and save them together with their metadata

    """

    if expected_clean_count <= 0:
        raise ValueError(
            "Expected clean clip count must be positive! "
        )

    OUTPUT_PATH.parent.mkdir(
        parents = True, # If missing then create also
        exist_ok = True, # If already exists do not error
    )

    # *** In order to prevent the creation of a second larger copy a set of attributes is reserved on here beforehand ***

    features = np.empty( # allocate space in the memory
        (
            expected_clean_count, # Total clean audio clip count

            EXPECTED_MEL_SHAPE[0], # Number of Mel bands for each clip
            EXPECTED_MEL_SHAPE[1], # Number of time frames for each clip
        ),

        dtype = np.float32,
    ) # features.shape = (expected_clean_count, 128, 216)

    labels = np.empty(
        expected_clean_count,
        dtype = np.int64,
    )

    clip_indices = np.empty(
        expected_clean_count,
        dtype = np.int32,
    )

    clip_starts = np.empty(
        expected_clean_count,
        dtype = np.float32,
    )

    hive_ids = []
    session_ids = []
    source_files = []

    write_index = 0
    audio_files = find_audio_files()

    print()
    print("Generating clean log - mel spectrograms here ...")

    for file_number, path in enumerate(audio_files, start = 1):
        label, hive_id, session_id = parse_filename(path)

        y, sr = load_audio(path)

        intervals = read_lab_intervals(path)

        file_clean_count = 0

        for clip_index, clip in enumerate(split_into_clips(y)):
            clip_start = clip_index * CLIP_SECONDS
            clip_end = clip_start + CLIP_SECONDS

            if clip_overlaps_nobee(clip_start, clip_end, intervals):
                continue

            if write_index >= expected_clean_count:
                raise RuntimeError(
                    "*** !Generated more clean clips than expected! ***"
                )

            features[write_index] = clip_to_log_mel(clip)
            labels[write_index] = LABEL_TO_ID[label]

            clip_indices[write_index] = clip_index
            clip_starts[write_index] = clip_start

            hive_ids.append(hive_id)
            session_ids.append(session_id)

            source_files.append(path.name)

            write_index += 1
            file_clean_count += 1

        print(
            f"[{file_number:>2}/{len(audio_files)}] " # >2 means right aligned and take up 2 characters of space
            f"{path.name}: {file_clean_count} clean clips counted"
        )

    if write_index != expected_clean_count:
        raise RuntimeError(
            f" ! *** Clean clip count mismatch: generated {write_index}, "
            f"expected {expected_clean_count} *** !"
        )

    hive_ids = np.asarray(
        hive_ids,
        dtype = np.str_,
    )

    session_ids = np.asarray(
        session_ids,
        dtype = np.str_,
    )

    source_files = np.asarray(
        source_files,
        dtype = np.str_,
    )

    print()
    print(f"Saving dataset to: {OUTPUT_PATH}")

    np.savez_compressed( # save the data in a compressed format to save disk space as more than one numpy arrays are going to be saved in a single file
        OUTPUT_PATH,
        X = features, # mel spectrograms that are generated from the clean audio clips
        y = labels, # numerical labels, 0 or 1 indicating healthy or queenless

        label_names = ID_TO_LABEL,

        hive_ids = hive_ids,
        session_ids = session_ids,
        source_files = source_files,
        clip_indices = clip_indices,
        clip_starts = clip_starts,

        sample_rate = np.int32(SAMPLE_RATE), 
        clip_seconds = np.int32(CLIP_SECONDS),
        n_fft = np.int32(NUM_OF_FFT),
        hop_length = np.int32(HOP_LENGTH), # Window progress step
        n_mels = np.int32(NUM_OF_MELS),  # Count of the Mel bands
        fmax = np.int32(FMAX),
    )

    print("Dataset saved successfully ! ")

    return OUTPUT_PATH

def validate_saved_dataset(dataset_path, expected_count):
    """

    It reopens and validates the saved dataset

    """

    if not dataset_path.exists():
        raise FileNotFoundError(
            f" ** ! Saved dataset does not exist: {dataset_path} ! ***"
        )

    with np.load( # with statement ensures that the file is properly closed after its suite finishes even if an exception is raised at some point and np.load() is used to load the .npz file that is saved in a compressed format
        dataset_path,
        allow_pickle = False, # Disables loading of pickled objects for security reasons
    ) as dataset:
        required_keys = {
            "X",
            "y",
            "label_names",
            "hive_ids",
            "session_ids",
            "source_files",
            "clip_indices",
            "clip_starts",
            "sample_rate",
            "clip_seconds",
            "n_fft",
            "hop_length",
            "n_mels",
            "fmax",
        }

        missing_keys = required_keys - set(dataset.files) # set creates "küme"

        if missing_keys:
            raise ValueError(
                f" ** ! Missing dataset keys: {sorted(missing_keys)} ! ***"
            )

        X = dataset["X"]
        y = dataset["y"]
        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]

        expected_shape = (
            expected_count,
            EXPECTED_MEL_SHAPE[0],
            EXPECTED_MEL_SHAPE[1],
        )

        if X.shape != expected_shape:
            raise ValueError(
                f" ** ! Unexpected X shape: {X.shape}. "
                f"Expected: {expected_shape} ! ***"
            )

        if X.dtype != np.float32:
            raise ValueError(
                f" ** ! Unexpected X dtype: {X.dtype} ! ***"
            )

        metadata_arrays = {
            "y": y,
            "hive_ids": hive_ids,
            "session_ids": session_ids,
            "source_files": dataset["source_files"],
            "clip_indices": dataset["clip_indices"],
            "clip_starts": dataset["clip_starts"],
        }

        for name, array in metadata_arrays.items():
            if len(array) != expected_count:
                raise ValueError(
                    f" ** ! Unexpected {name} length: {len(array)} ! ***"
                )

        if not np.isfinite(X).all():
            raise ValueError(
                " ** ! Saved features contain NaN or infinite values ! ***"
            )

        unique_labels = set(np.unique(y).tolist()) # unique gets the unique values

        if not unique_labels.issubset({0, 1}):
            raise ValueError(
                f" ** ! Unexpected label IDs: {unique_labels} ! ***"
            )

        healthy_count = int(np.sum(y == 0))
        queenless_count = int(np.sum(y == 1))

        file_size_mib = (
            dataset_path.stat().st_size / (1024 * 1024)
        )

        print()
        print("Saved dataset validation passed:")
        print(f"  X shape         : {X.shape}")
        print(f"  X dtype         : {X.dtype}")
        print(f"  y shape         : {y.shape}")
        print(f"  healthy         : {healthy_count}")
        print(f"  queenless       : {queenless_count}")
        print(
            f"  unique hives    : "
            f"{len(np.unique(hive_ids))}"
        )
        print(
            f"  unique sessions : "
            f"{len(np.unique(session_ids))}"
        )
        print(f"  file size       : {file_size_mib:.1f} MiB")

def main():
    validate_audio_filenames()

    print()
    print("Checking the audio durations and 5 second clips --")
    print()

    expected_clean_count = inspect_audio_clips()

    print()
    print("Testing one clean log-mel spectrogram --")

    test_first_clean_spectrogram()

    dataset_path = build_and_save_clean_dataset(
        expected_clean_count
    )

    validate_saved_dataset(
        dataset_path,
        expected_clean_count,
    )

if __name__ == "__main__":
    main()