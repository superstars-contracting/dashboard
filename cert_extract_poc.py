#!/usr/bin/env python3
"""POC: extract structured cert data from one cert card JPEG using Claude Sonnet 4.6 vision.

Validates that vision-LLM extraction is viable before building the full intake
pipeline. ANTHROPIC_API_KEY comes from 1Password via `op run` — never plaintext.

  op run --env-file=".env.template" -- python cert_extract_poc.py <jpeg_path>

Saves the full response to intake/cert_extract_poc_output.json (gitignored).
Prints a redacted quality summary to stdout — no extracted values.
"""

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import anthropic

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
OUTPUT_PATH = SCRIPT_DIR / "intake" / "cert_extract_poc_output.json"

# Latest Sonnet 4.x — bare model ID per Anthropic SDK convention (no date suffix).
MODEL = "claude-sonnet-4-6"


def load_cert_types():
    """Return [(cert_type_id, name, is_cof_prereq), ...] from the seeded library."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT cert_type_id, name, is_cof_prerequisite FROM cert_types "
        "ORDER BY cert_type_id"
    ).fetchall()
    conn.close()
    return rows


def build_prompt(cert_types):
    library = "\n".join(
        f"  {cid:<18}  {name}{'  [CoF prereq]' if prereq else ''}"
        for cid, name, prereq in cert_types
    )
    return f"""You are extracting structured data from a photo of an NYC construction worker certification card.

Match the visible cert to ONE of these 47 known cert_type_id codes when possible:

{library}

Rules:
- Extract ONLY what you can clearly read from the image.
- Return null for any field you cannot confidently identify. Do NOT guess. Do NOT hallucinate.
- For cert_type_id_guess: pick the code from the list above whose name best matches the visible cert title. If nothing matches confidently, return null.
- For dates: use ISO YYYY-MM-DD. If the card shows a date in a different format, convert it. If you can't read the date confidently, return null.
- For card_number: copy the printed number exactly. Strip surrounding labels.
- For holder_name: include the worker's name as printed. Used for verification only — won't be stored long-term.
- If the image is blurry, glared, partial, or not a cert card at all, note that in extraction_notes and return nulls for the data fields."""


# Schema constrains the response to valid JSON with these exact fields.
# Nullable fields use union types — the JSON Schema convention supported by
# Anthropic's structured outputs.
SCHEMA = {
    "type": "object",
    "properties": {
        "cert_type_id_guess": {
            "type": ["string", "null"],
            "description": "Best-match cert_type_id from the 47-row library, or null."
        },
        "cert_type_name_visible": {
            "type": ["string", "null"],
            "description": "Raw cert name/title as printed on the card."
        },
        "card_number": {
            "type": ["string", "null"],
            "description": "Card number / serial number printed on the card."
        },
        "date_obtained": {
            "type": ["string", "null"],
            "description": "Issue / training date in ISO YYYY-MM-DD, or null."
        },
        "expiration_date": {
            "type": ["string", "null"],
            "description": "Expiration date in ISO YYYY-MM-DD, or null."
        },
        "issuing_body": {
            "type": ["string", "null"],
            "description": "Issuing authority (NYC DOB, FDNY, OSHA, NYCCT, etc.)."
        },
        "holder_name": {
            "type": ["string", "null"],
            "description": "Worker name on the card (verification only)."
        },
        "extraction_notes": {
            "type": "string",
            "description": "Caveats, uncertainties, or notes about extraction quality."
        }
    },
    "required": [
        "cert_type_id_guess", "cert_type_name_visible", "card_number",
        "date_obtained", "expiration_date", "issuing_body",
        "holder_name", "extraction_notes"
    ],
    "additionalProperties": False
}


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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY not set in environment.\n"
            'Run via:  op run --env-file=".env.template" -- '
            "python cert_extract_poc.py <jpeg_path>",
            file=sys.stderr,
        )
        return 1

    with jpeg_path.open("rb") as f:
        image_b64 = base64.standard_b64encode(f.read()).decode("ascii")

    cert_types = load_cert_types()
    valid_ids = {cid for cid, _, _ in cert_types}
    prompt = build_prompt(cert_types)

    client = anthropic.Anthropic()

    t0 = time.monotonic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            # Pure extraction task — no multi-step reasoning needed.
            thinking={"type": "disabled"},
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except anthropic.APIError as e:
        print(f"ERROR: Anthropic API call failed: {e}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - t0

    # output_config.format guarantees the first text block contains valid JSON.
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        extracted = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ERROR: response was not valid JSON: {e}", file=sys.stderr)
        print(f"First 300 chars: {text[:300]}", file=sys.stderr)
        return 1

    # Save full response locally (gitignored under intake/*).
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({
            "jpeg_path": str(jpeg_path),
            "model": MODEL,
            "elapsed_seconds": round(elapsed, 2),
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "stop_reason": response.stop_reason,
            "extracted": extracted,
        }, indent=2),
        encoding="utf-8",
    )

    # Redacted summary — no extracted values echoed.
    matched = extracted.get("cert_type_id_guess") in valid_ids
    cn = extracted.get("card_number") or ""

    print(f"Model:    {MODEL}")
    print(f"Elapsed:  {elapsed:.2f}s")
    print(f"Tokens:   input={response.usage.input_tokens}  output={response.usage.output_tokens}")
    print(f"Stop:     {response.stop_reason}")
    print()
    print("Extraction quality (✓ = field returned non-null and / or validated):")

    def row(field, ok, detail=""):
        mark = "✓" if ok else "✗"
        suffix = f"  {detail}" if detail else ""
        print(f"  {mark} {field}{suffix}")

    row("cert_type_id_guess matches known library", matched,
        detail=f"({extracted.get('cert_type_id_guess')!r})" if matched else "(no match)")
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
