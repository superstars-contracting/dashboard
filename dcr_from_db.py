#!/usr/bin/env python3
"""DCR JSON generator backed by SQLite — replaces the Excel-driven
generate_dcr.py. Calls dcr_aggregator.aggregate_dcr() in-process and
serializes the result to JSON.

Usage:
  dcr_from_db.py --project_code SC-2601 [--report_date YYYY-MM-DD]
                 [--audience internal|client] [--output_json PATH]

Output goes to --output_json if supplied, else stdout. Pipe the JSON
into render_dcr_html.py to produce the HTML."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dcr_aggregator import aggregate_dcr


def main():
    parser = argparse.ArgumentParser(description="Generate DCR JSON from SQLite")
    parser.add_argument("--project_code", required=True, help="Project code (e.g. SC-2601)")
    parser.add_argument("--report_date", default=date.today().isoformat(),
                        help="Report date YYYY-MM-DD (default: today)")
    parser.add_argument("--audience", choices=["internal", "client"], default="internal",
                        help="Audience for redaction policy (default: internal)")
    parser.add_argument("--output_json", default=None,
                        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    try:
        dcr = aggregate_dcr(args.project_code, args.report_date, args.audience)
    except (ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(2)

    payload = json.dumps(dcr, indent=2, default=str)
    if args.output_json:
        Path(args.output_json).write_text(payload, encoding="utf-8")
        print(f"DCR JSON written to {args.output_json}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
