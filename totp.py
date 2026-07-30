"""#289 — RFC 6238 TOTP + recovery codes, standard library only (no pyotp/qrcode
on this workstation, and none needed).

  * secret: 20 random bytes, base32 (Google Authenticator / Authy / 1Password all
    accept it). generate_secret() emits the base32 string; provisioning_uri()
    emits the otpauth:// URI the authenticator app scans (the enrollment page
    renders it as a QR client-side, or the operator types the base32 by hand).
  * verify(secret, code): TOTP-SHA1, 6 digits, 30s step, with a +/-1 step window
    (clock skew tolerance). Constant-time digit compare.
  * recovery codes: 10 single-use codes; stored bcrypt-HASHED (never plaintext),
    shown once at enrollment. consume_recovery() checks + returns the remaining
    hashed set so the caller persists the burn.

The secret is a shared secret (comp-data class, CLAUDE.md): BitLocker at rest is
today's protection, SQLCipher is the roadmap; it is never logged or emitted after
the one-time enrollment display.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

import bcrypt

DIGITS = 6
STEP = 30
SKEW_STEPS = 1              # accept the code from the previous/next 30s window


def generate_secret() -> str:
    """A fresh base32 TOTP secret (20 bytes -> 32 base32 chars, no padding)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_at(secret_b32: str, counter: int) -> str:
    # base32 decode (tolerant of missing padding + lowercase)
    s = secret_b32.strip().replace(" ", "").upper()
    s += "=" * ((8 - len(s) % 8) % 8)
    key = base64.b32decode(s, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret_b32: str, code: str, at: float | None = None) -> bool:
    """True iff `code` matches the TOTP for `secret` within the skew window."""
    if not secret_b32 or not code:
        return False
    code = str(code).strip()
    if len(code) != DIGITS or not code.isdigit():
        return False
    now = int((at if at is not None else time.time()) // STEP)
    for delta in range(-SKEW_STEPS, SKEW_STEPS + 1):
        if hmac.compare_digest(_code_at(secret_b32, now + delta), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account_name: str, issuer: str = "Superstars Contracting") -> str:
    """otpauth://totp/<issuer>:<account>?secret=...&issuer=... — the QR payload."""
    from urllib.parse import quote
    label = quote(f"{issuer}:{account_name}")
    return (f"otpauth://totp/{label}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}")


# ---- recovery codes (single-use, bcrypt-hashed) ----

def generate_recovery_codes(n: int = 10) -> list[str]:
    """n human-friendly codes like 'a1b2-c3d4' (shown ONCE, then only hashes kept)."""
    alph = "abcdefghijkmnpqrstuvwxyz23456789"   # no ambiguous 0/o/1/l
    out = []
    for _ in range(n):
        raw = "".join(secrets.choice(alph) for _ in range(8))
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [bcrypt.hashpw(c.encode("utf-8"), bcrypt.gensalt()).decode("ascii") for c in codes]


def consume_recovery(code: str, hashed_codes: list[str]):
    """Return (ok, remaining_hashes). Burns exactly the ONE matching hash."""
    code = (code or "").strip().lower()
    if not code or not hashed_codes:
        return False, hashed_codes
    remaining = []
    hit = False
    for h in hashed_codes:
        if not hit and bcrypt.checkpw(code.encode("utf-8"), h.encode("utf-8")):
            hit = True
            continue          # burn this one
        remaining.append(h)
    return hit, remaining
