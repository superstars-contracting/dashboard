#!/usr/bin/env python3
"""POC CLI: extract one cert card JPEG to JSON, save locally, print summary.

Thin wrapper around cert_extractor for command-line debugging. Production
code (the Flask /extract route) imports cert_extractor directly — this
script's value is reproducing a single API call against an arbitrary JPEG
on disk without spinning up the server.

  op run --env-file=".env.template" -- python cert_extract_poc.py <jpeg_path>
"""

import argparse
import json
import sys
from pathlib import Path

from cert_extractor import extract_cert_from_image, load_cert_types_from_db

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
OUTPUT_PATH = SCRIPT_DIR / "intake" / "cert_extract_poc_output.json"


def main():
    # Windows console defaults to cp1252 — force UTF-8 so the ✓/✗ marks render
    # instead of crashing the script after the API call has already succeeded.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("jpeg_path", help="Path to a JPEG of a cert card.")
    args = parser.parse_args()

    jpeg_path = Path(args.jpeg_path).resolve()
    if not jpeg_path.exists():
        print(f"ERROR: {jpeg_path} not found", file=sys.stderr)
        return 1
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    cert_types = load_cert_types_from_db(DB_PATH)
    valid_ids = {c["cert_type_id"] for c in cert_types}

    try:
        extracted = extract_cert_from_image(jpeg_path, cert_types)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    meta = extracted.pop("_meta", {})

    # Save full response locally (gitignored under intake/*).
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({
            "jpeg_path": str(jpeg_path),
            "meta": meta,
            "extracted": extracted,
        }, indent=2),
        encoding="utf-8",
    )

    matched = extracted.get("cert_type_id_guess") in valid_ids
    cn = extracted.get("card_number") or ""

    print(f"Model:    {meta.get('model')}")
    print(f"Elapsed:  {meta.get('elapsed_seconds')}s")
    print(f"Tokens:   input={meta.get('input_tokens')}  output={meta.get('output_tokens')}")
    print(f"Stop:     {meta.get('stop_reason')}")
    print()
    print("Extraction quality (✓ = field returned non-null and / or validated):")

    def row(field, ok, detail=""):
        mark = "✓" if ok else "✗"
        suffix = f"  {detail}" if detail else ""
        print(f"  {mark} {field}{suffix}")

    row(
        "cert_type_id_guess matches known library",
        matched,
        detail=f"({extracted.get('cert_type_id_guess')!r})" if matched else "(no match)",
    )
    row("cert_type_name_visible extracted", bool(extracted.get("cert_type_name_visible")))
    row("card_number extracted", bool(cn), detail=f"({len(cn)} chars)" if cn else "")
    row("date_obtained (ISO format)", bool(extracted.get("date_obtained")))
    row("expiration_date (ISO format)", bool(extracted.get("expiration_date")))
    row("issuing_body extracted", bool(extracted.get("issuing_body")))
    row("holder_name extracted", bool(extracted.get("holder_name")))
    row("extraction_notes populated", bool(extracted.get("extraction_notes")))

    print()
    print(f"Full response saved to: {OUTPUT_PATH.relative_to(SCRIPT_DIR)}")
    print("  (gitignored — keep local; contains full extracted PII)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
