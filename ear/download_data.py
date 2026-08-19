"""
download_data.py — fetches the "To bee or not to bee" dataset that is from Zenodo
Files are landed under ../data/tobee/ that is git ignored
"""
import os, sys, json, urllib.request

ZENODO_API = "https://zenodo.org/api/records/1321278"
DEST = os.path.join(os.path.dirname(__file__), "..", "data", "tobee")

def human(n): # Since zenodo has really large amount of data this method converts into humanized version
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"

        n /= 1024

    return f"{n:.1f} TB"

# block_num: Number of blocks that are installed

def progress(block_num, block_size, total_size): # It shows the progression percentage 
    downloaded = block_num * block_size # Downloaded yet

    if total_size > 0:
        pct = min(100, (downloaded / total_size) * 100) # percentage

        sys.stdout.write(f"\r    {pct:5.1f}%  ({human(downloaded)} / {human(total_size)})")
        sys.stdout.flush() # Do not wair on buffer

def main():
    os.makedirs(DEST, exist_ok = True) # Make directorieS

    print("Fetching file list from Zenodo record 1321278 ...") # 1321278 is the ID for To Bee or Not to Bee in Zenodo

    with urllib.request.urlopen(ZENODO_API) as resp:
        record = json.loads(resp.read().decode())
        # Once it was in bytes like b'{"id": 1321278}' when it is read but then gets decoded to string in Python
        # json.loads() takes the string and creates it as an object in Python since it can be used

    files = record.get("files", []) # files name is coming from Zenodo API, may return void []

    if not files:
        print("No files found. Check https://zenodo.org/records/1321278");

        return
    
    print(f"Found {len(files)} file(s). Saving to: {os.path.abspath(DEST)}\n")

    for f in files:
        name, url, size = f["key"], f["links"]["self"], f.get("size", 0)

        out_path = os.path.join(DEST, name)

        if os.path.exists(out_path) and os.path.getsize(out_path) == size:
            print(f"  OK {name} — already downloaded, skipping");

            continue

        print(f"  downloading {name} ({human(size)})")

        try:
            urllib.request.urlretrieve(url, out_path, reporthook = progress);print()
        except Exception as e:
            print(f"\n    ERROR downloading {name}: {e}")
            
    print("\nDone. Next: unzip any .zip files here, then the spectrogram step")

if __name__ == "__main__":
    main()
