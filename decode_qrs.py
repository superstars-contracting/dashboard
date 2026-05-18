#!/usr/bin/env python3
"""Decode QR / barcode payloads from JPEGs in intake/raw_photos/.

Outputs:
- Redacted summary to stdout (safe to share)
- Full per-file mapping to intake/decode_qrs_output.txt (gitignored)

Does NOT fetch any decoded URL. Decoding only — inspection of what the URL
returns is a separate manual step. Idempotent: re-running overwrites the
local output file.

Uses zxing-cpp instead of pyzbar because pyzbar on Windows depends on a
system libiconv.dll that isn't always present; zxing-cpp ships a fully
self-contained C++ binary in the wheel.
"""

import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import zxingcpp
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
PHOTOS_DIR = SCRIPT_DIR / "intake" / "raw_photos"
OUTPUT_FILE = SCRIPT_DIR / "intake" / "decode_qrs_output.txt"

JPEG_EXTS = (".jpg", ".jpeg", ".JPG", ".JPEG")


def classify(payload):
    p = (payload or "").strip()
    if not p.lower().startswith(("http://", "https://")):
        return "non-URL"
    try:
        host = urlparse(p).netloc.lower()
    except Exception:
        return "non-URL"
    if "trainingconnect" in host:
        return "trainingconnect"
    if "nyc.gov" in host or "cityofnewyork" in host:
        return "nyc-other"
    if "osha" in host:
        return "osha"
    return "other-url"


def redact_to_pattern(payload):
    """Keep scheme + host + first path segment; redact later path segments,
    every query-value, and any fragment. Catches the case where a wallet-card
    URL puts the worker token in the path (e.g., /qr/<base64-id>) rather than
    the query string."""
    try:
        parsed = urlparse(payload)
    except Exception:
        return "<unparseable>"
    if not parsed.scheme:
        return "<non-URL payload>"
    segs = [s for s in parsed.path.split("/") if s]
    if len(segs) <= 1:
        redacted_path = parsed.path
    else:
        redacted_path = "/" + segs[0] + "/" + "/".join("<REDACTED>" for _ in segs[1:])
    base = f"{parsed.scheme}://{parsed.netloc}{redacted_path}"
    if parsed.query:
        keys = list(parse_qs(parsed.query, keep_blank_values=True).keys())
        base += "?" + "&".join(f"{k}=<REDACTED>" for k in keys)
    if parsed.fragment:
        base += "#<REDACTED>"
    return base


def decode_file(fp):
    """Return list of (symbol_format, payload) tuples. Empty list on no codes
    or open/decode failure."""
    try:
        img = Image.open(str(fp))
    except Exception:
        return []
    try:
        results = zxingcpp.read_barcodes(img)
    except Exception:
        return []
    out = []
    for r in results:
        fmt = r.format.name if hasattr(r.format, "name") else str(r.format)
        text = (r.text or "").strip()
        if text:
            out.append((fmt, text))
    return out


def main():
    if not PHOTOS_DIR.exists():
        print(f"ERROR: {PHOTOS_DIR} not found", file=sys.stderr)
        return 1

    files = sorted(p for p in PHOTOS_DIR.iterdir() if p.is_file() and p.suffix in JPEG_EXTS)
    if not files:
        print(f"No JPEGs found in {PHOTOS_DIR}")
        return 0

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    by_file = []                 # list of (idx, filename, [(fmt, payload), ...])
    by_category = defaultdict(list)  # category -> list of (idx, fmt, redacted_pattern)
    zero_code = []               # list of (idx, filename)

    for idx, fp in enumerate(files, start=1):
        payloads = decode_file(fp)
        by_file.append((idx, fp.name, payloads))
        if not payloads:
            zero_code.append((idx, fp.name))
            continue
        for fmt, text in payloads:
            cat = classify(text)
            pat = redact_to_pattern(text) if cat != "non-URL" else "<non-URL payload>"
            by_category[cat].append((idx, fmt, pat))

    # --- Local unredacted file (idempotent overwrite) ---
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        f.write(f"# decode_qrs.py — {len(files)} JPEG(s) scanned\n")
        f.write("# Format: idx | filename | symbol_format | full_payload\n")
        f.write("# Zero-code files listed at the bottom.\n\n")
        for idx, fname, payloads in by_file:
            for fmt, text in payloads:
                f.write(f"{idx} | {fname} | {fmt} | {text}\n")
        if zero_code:
            f.write("\n# Zero-code files (no QR/barcode detected):\n")
            for idx, fname in zero_code:
                f.write(f"{idx} | {fname} | (none) | -\n")

    # --- Redacted summary to stdout ---
    files_with_codes = sum(1 for _, _, p in by_file if p)
    total_codes = sum(len(p) for _, _, p in by_file)
    print(f"Scanned {len(files)} JPEG(s) in intake/raw_photos/")
    print(f"  JPEGs with >=1 decodable code: {files_with_codes}")
    print(f"  JPEGs with zero codes:         {len(zero_code)}")
    print(f"  Total codes decoded:           {total_codes}")
    print()
    if by_category:
        print("Codes grouped by URL pattern:")
        for cat in sorted(by_category.keys()):
            items = by_category[cat]
            distinct_files = len({i for i, _, _ in items})
            distinct_patterns = sorted({pat for _, _, pat in items})
            print(f"\n  [{cat}]  {len(items)} code(s) across {distinct_files} file(s)")
            for pat in distinct_patterns:
                n = sum(1 for _, _, p in items if p == pat)
                print(f"    pattern: {pat}   (x{n})")
    if zero_code:
        print()
        print("Zero-code JPEGs (likely too small/blurry/angled):")
        for idx, _ in zero_code:
            print(f"  - file #{idx}")
    print()
    print(f"Unredacted per-file mapping written to: {OUTPUT_FILE.relative_to(SCRIPT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
