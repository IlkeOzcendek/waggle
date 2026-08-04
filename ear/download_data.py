"""
download_data.py — fetch the "To bee or not to bee" dataset from Zenodo.
Files land under ../data/tobee/ (git-ignored).
"""
import os, sys, json, urllib.request

ZENODO_API = "https://zenodo.org/api/records/1321278"
DEST = os.path.join(os.path.dirname(__file__), "..", "data", "tobee")

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 / total_size)
        sys.stdout.write(f"\r    {pct:5.1f}%  ({human(downloaded)} / {human(total_size)})")
        sys.stdout.flush()

def main():
    os.makedirs(DEST, exist_ok=True)
    print("Fetching file list from Zenodo record 1321278 ...")
    with urllib.request.urlopen(ZENODO_API) as resp:
        record = json.loads(resp.read().decode())
    files = record.get("files", [])
    if not files:
        print("No files found. Check https://zenodo.org/records/1321278"); return
    print(f"Found {len(files)} file(s). Saving to: {os.path.abspath(DEST)}\n")
    for f in files:
        name, url, size = f["key"], f["links"]["self"], f.get("size", 0)
        out_path = os.path.join(DEST, name)
        if os.path.exists(out_path) and os.path.getsize(out_path) == size:
            print(f"  OK {name} — already downloaded, skipping"); continue
        print(f"  downloading {name} ({human(size)})")
        try:
            urllib.request.urlretrieve(url, out_path, reporthook=progress); print()
        except Exception as e:
            print(f"\n    ERROR downloading {name}: {e}")
    print("\nDone. Next: unzip any .zip files here, then the spectrogram step.")

if __name__ == "__main__":
    main()
