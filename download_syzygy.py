"""
download_syzygy.py
Downloads 3-4-5 piece Syzygy WDL tablebase files (.rtbw) from Sesse's mirror.
Only WDL files are downloaded (~950 MB total) — sufficient for perfect endgame play.

Usage:
    python download_syzygy.py [output_dir]
    Default output: data/syzygy/
"""

import os
import sys
import ssl
import urllib.request

# Mirror has a hostname mismatch on its TLS cert — safe to skip for file downloads
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

MIRROR  = "https://tablebase.sesse.net/syzygy/3-4-5/"
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "data/syzygy"


def fetch_filenames_from_mirror():
    """Scrape .rtbw filenames directly from the mirror directory listing."""
    import re
    req = urllib.request.Request(MIRROR)
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=15) as r:
        html = r.read().decode()
    return sorted(re.findall(r'href="([A-Z]+v[A-Z]+\.rtbw)"', html))


def download_file(name, out_dir):
    fname   = name
    url     = MIRROR + fname
    outpath = os.path.join(out_dir, fname)

    if os.path.exists(outpath):
        return "skip"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=_SSL_CTX) as resp, open(outpath, "wb") as f:
            f.write(resp.read())
        size = os.path.getsize(outpath)
        return f"{size // 1024} KB"
    except Exception as e:
        if os.path.exists(outpath):
            os.remove(outpath)
        return f"FAIL ({e})"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Fetching file list from mirror...")
    names    = fetch_filenames_from_mirror()
    total    = len(names)
    ok, skip, fail = 0, 0, 0

    print(f"Downloading {total} Syzygy WDL files → {OUT_DIR}")
    print(f"Mirror: {MIRROR}\n")

    for i, name in enumerate(names, 1):
        result = download_file(name, OUT_DIR)
        status = "SKIP" if result == "skip" else ("FAIL" if result.startswith("FAIL") else "OK")
        if status == "OK":   ok   += 1
        elif status == "SKIP": skip += 1
        else:                fail += 1
        print(f"  [{i:3d}/{total}] {name+'.rtbw':<18} {result}")

    total_mb = sum(
        os.path.getsize(os.path.join(OUT_DIR, f))
        for f in os.listdir(OUT_DIR) if f.endswith(".rtbw")
    ) // (1024 * 1024)
    syzygy_abs = os.path.abspath(OUT_DIR)

    print(f"\nDone — {ok} downloaded, {skip} skipped, {fail} failed")
    print(f"Total size: {total_mb} MB  →  {syzygy_abs}")
    print(f"\nTo use in the C engine:")
    print(f'  setoption name SyzygyPath value {syzygy_abs}')
    print(f"\nTo use in Python engine:")
    print(f'  python main.py analyze --tablebase "{syzygy_abs}" --fen "..."')


if __name__ == "__main__":
    main()
