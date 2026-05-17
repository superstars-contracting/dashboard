#!/usr/bin/env python3
"""
SendGrid RFI Email Sender
Sends email drafts from rfi_workflow_run with dev mode safety override.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
import base64

# Configuration — paths resolve relative to this script's location
# so it works on both the sandbox and the user's local Windows machine.
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR
CONFIG_FILE = OUTPUT_DIR / "api-keys.txt"
EMAIL_DRAFTS_DIR = OUTPUT_DIR / "rfi_workflow_run" / "email_drafts"
LOG_FILE = OUTPUT_DIR / "rfi_workflow_run" / "sendgrid_send_log.json"

# Recipient email mapping for live mode
RECIPIENT_MAP = {
    "Architect": "arch@nyparkdesigns.com",
    "Project_Manager": "susan.park@superstars.nyc",
    "Owner_Rep": "owner@example.com",
    "Structural_Engineer": "engineer@example.com",
    "Superintendent": "super@example.com",
}


def load_config(path):
    """Load config from api-keys.txt with # comment support."""
    cfg = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line or '=' not in line:
                continue
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip()
    return cfg


def extract_subject_from_html(html_content):
    """Extract subject from <title> tag or return fallback."""
    match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "RFI Communication"


def extract_recipient_from_filename(filename):
    """Extract recipient name from RFI-XXX-to-{Name}.html."""
    match = re.search(r'-to-(.+)\.html$', filename)
    if match:
        return match.group(1)
    return None


def send_emails():
    """Main email sending logic."""
    # Load config
    try:
        config = load_config(CONFIG_FILE)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found")
        return 1

    # Validate required keys
    required = ["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL", "DEV_EMAIL_OVERRIDE"]
    missing = [k for k in required if k not in config]
    if missing:
        print(f"ERROR: Missing config keys: {', '.join(missing)}")
        return 1

    api_key = config["SENDGRID_API_KEY"]
    from_email = config["SENDGRID_FROM_EMAIL"]
    dev_override = config["DEV_EMAIL_OVERRIDE"]
    live_mode = config.get("LIVE_MODE", "false").lower() == "true"

    # Confirm key loaded (masked)
    print(f"[Config] Key loaded ({len(api_key)} chars, prefix {api_key[:5]}...)")
    print(f"[Config] From: {from_email}")
    print(f"[Config] Dev override: {dev_override}")
    print(f"[Config] Live mode: {live_mode}")
    print()

    # Initialize SendGrid client
    sg = SendGridAPIClient(api_key)

    # Find and process email drafts
    if not EMAIL_DRAFTS_DIR.exists():
        print(f"ERROR: Email drafts directory not found: {EMAIL_DRAFTS_DIR}")
        return 1

    html_files = sorted(EMAIL_DRAFTS_DIR.glob("*.html"))
    if not html_files:
        print(f"WARNING: No HTML email drafts found in {EMAIL_DRAFTS_DIR}")
        return 1

    print(f"Found {len(html_files)} email drafts\n")

    send_log = []
    success_count = 0

    for html_file in html_files:
        filename = html_file.name
        with open(html_file, encoding='utf-8') as f:
            html_content = f.read()

        # Extract metadata
        subject = extract_subject_from_html(html_content)
        recipient_name = extract_recipient_from_filename(filename)

        # Determine target email and adjust subject
        if live_mode:
            if recipient_name and recipient_name in RECIPIENT_MAP:
                to_email = RECIPIENT_MAP[recipient_name]
            else:
                print(f"  WARNING: {filename} - recipient '{recipient_name}' not in map, skipping")
                continue
        else:
            # Dev mode: route to override, prefix subject
            to_email = dev_override
            if recipient_name:
                subject = f"[TEST → {recipient_name}] {subject}"

        # Build and send mail
        try:
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content
            )

            # Attach PDF if it exists
            rfi_num_match = re.search(r'(RFI-\d+)', filename)
            if rfi_num_match:
                rfi_num = rfi_num_match.group(1)
                pdf_path = (SCRIPT_DIR / "rfi_workflow_run" / "pdf" / f"{rfi_num}.pdf")
                if pdf_path.exists():
                    try:
                        with open(pdf_path, 'rb') as pdf_file:
                            pdf_data = pdf_file.read()
                        encoded_pdf = base64.b64encode(pdf_data).decode()
                        attachment = Attachment(
                            FileContent(encoded_pdf),
                            FileName(f"{rfi_num}.pdf"),
                            FileType('application/pdf'),
                            Disposition('attachment')
                        )
                        mail.attachment = attachment
                    except Exception as e:
                        print(f"  WARNING: Could not attach PDF for {rfi_num}: {str(e)}")
                else:
                    print(f"  WARNING: PDF not found at {pdf_path}")

            response = sg.send(mail)
            status_code = response.status_code

            status_text = "OK" if status_code == 202 else f"FAIL ({status_code})"
            if status_code == 202:
                success_count += 1

            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "filename": filename,
                "original_recipient": recipient_name,
                "sent_to": to_email,
                "subject": subject,
                "status_code": status_code,
            }
            send_log.append(log_entry)

            print(f"  {filename:<40} → {to_email:<35} {status_text}")

        except Exception as e:
            print(f"  {filename:<40} → ERROR: {str(e)}")
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "filename": filename,
                "original_recipient": recipient_name,
                "error": str(e),
            }
            send_log.append(log_entry)

    # Write log file
    log_file_dir = LOG_FILE.parent
    log_file_dir.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(send_log, f, indent=2)

    print()
    print(f"✓ Sent {success_count}/{len(html_files)} emails")
    if live_mode:
        print("  (LIVE MODE — emails sent to actual recipients)")
    else:
        print(f"  (dev mode → all routed to {dev_override})")
    print(f"  Log saved to: {LOG_FILE}")

    return 0 if success_count == len(html_files) else 1


if __name__ == "__main__":
    exit(send_emails())
