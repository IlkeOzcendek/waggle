# %% [markdown]
# # Waggle - Data Exploration Part Load
# Read audio, derive labels from filenames, visualise spectrograms

# %%
import os, glob # glob for patterns
import numpy as np
import librosa, librosa.display # for the analysis of the voice and visualization
import matplotlib.pyplot as plt # graphics library, drawing graphics

DATA_DIR = os.path.join("..", "data", "tobee")
print("Looking in:", os.path.abspath(DATA_DIR))

# %%
def label_from_name(fname): # fname = file name
    low = fname.lower() # gets everything on lower case

    if "no_queenbee" in low or "missing queen" in low: # in = does it contain or not
        return "queenless"
    
    if "queenbee" in low or "active" in low:
        return "healthy"
    
    return "unknown"

audio_files = sorted ( # all in one place, global pattern matching
    glob.glob(os.path.join(DATA_DIR, "*.wav"))
                     +
    glob.glob(os.path.join(DATA_DIR, "*.mp3"))
)

labeled = [ # audio files and their label, side by side
    (f, label_from_name(os.path.basename(f))) for f in audio_files # f as in file, basename just to leave the file name without the file path
]

labeled = [ # l for label and f for file, delete unknown ones
    (f, l) for f, l in labeled if l != "unknown"
]

print("Total labeled:", len(labeled))
print("  healthy  :", sum(1 for _, l in labeled if l == "healthy")) # _ as I am not interested in coming name, just get the label
print("  queenless:", sum(1 for _, l in labeled if l == "queenless"))

# %%
def first_of(label): # next() gets the first of the group
    return next(f for f, l in labeled if l == label)

healthy_file = first_of("healthy")
queenless_file = first_of("queenless")

print("Healthy  :", os.path.basename(healthy_file))
print("Queenless:", os.path.basename(queenless_file))

SR = 22050 # Sample rate

# "offset" says do not read the first given that much seconds
# "duration" says read that much seconds; offset 30 and duration 10 being read among 30 - 40

y_healthy, _ = librosa.load(healthy_file, sr = SR, offset = 0, duration = 10) # Reads the sound files and then converts them into mathematical values
y_queenless, _ = librosa.load(queenless_file, sr = SR, offset = 0, duration = 10) # Returns 2 values as the mathematical values of the sound and the sr, since I gave them 22050 it is already known so no need to return again and again "_"

print("Loaded:", y_healthy.shape, y_queenless.shape)

# %%
def melspec_decibel(y, sr = SR):
    mel_spectrogram = librosa.feature.melspectrogram( # At this time that much power / energy is available in this Mel frequency band
        y = y, #y = sound data
        sr = sr, # horizontal division for 1 sec
        n_mels = 128, # number of mels to represent the frequency, vertical divition
        fmax = 2000 # max freq to look
    )

    return librosa.power_to_db(mel_spectrogram, ref = np.max) # ref is to consider the strongest point as the 0 dB reference point as np for numpy and max for maximum value

fig, axes = plt.subplots(1, 2, figsize = (14, 4)) # 1 row, 2 columns; 14 x 4; figure with 2 axes as [0, 1] meaning 2 areas
# fig is figure as a whole and axes are the two parts, 14 x 4 for whole image

for ax, y, title in [(axes[0], y_healthy, "HEALTHY -- the queen is present"), # ax = axes, y as which sound, title as healthy or not
                     (axes[1], y_queenless, "QUEENLESS -- the queen is missing")]:
    S = melspec_decibel(y)

    img = librosa.display.specshow(
        S, # The spectogram that is going to get visualized
        sr = SR, # sample rate
        x_axis = "time", # show x axis as time
        y_axis = "mel", # as mel frequency
        fmax = 2000, ax = ax # write that spectogram on that area of the graph
    )

    ax.set_title(title)
    fig.colorbar(img, ax = ax, format = "%+2.0f dB")
    
plt.tight_layout() # prepare the layout
plt.savefig("spectrograms.png", dpi = 120)
plt.show()

# %%
print("Exploration complete, data is ready for the modeling-- ")
