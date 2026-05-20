"""Headless Microsoft Edge PDF rendering for finalized DCRs.

Why Edge and not WeasyPrint:
  WeasyPrint requires GTK on Windows; GTK won't install on this workstation
  (Windows Home, no MSYS2 toolchain). Edge ships with Windows, supports
  --print-to-pdf in headless mode, and produces clean PDFs from
  self-contained HTML.

Usage:
  from pdf_export import render_html_to_pdf, PDFExportError
  result = render_html_to_pdf(html_path, pdf_path)
  if result["ok"]:
      ...
  else:
      log warning, surface result["error"] to UI

Caller policy:
  This module never raises on rendering failures — it returns
  {"ok": False, "error": ...} so the caller (DCR issuance) decides whether
  to fail the whole issue or just warn + continue. The only exception
  raised is PDFExportError when Edge itself is not installed (a setup-time
  problem, not a runtime one).
"""
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def _best_effort_rmtree(path, attempts=5, delay=0.2):
    """Edge holds file handles in its profile dir briefly after subprocess
    exits on Windows, racing tempfile.TemporaryDirectory's cleanup. Try
    several times with backoff, then give up — temp dir contents are tiny
    and Windows will reclaim %TEMP% eventually."""
    for i in range(attempts):
        try:
            shutil.rmtree(str(path))
            return True
        except (OSError, PermissionError):
            time.sleep(delay * (i + 1))
    # last-ditch: ignore_errors so we don't fail the whole render on cleanup
    shutil.rmtree(str(path), ignore_errors=True)
    return not Path(path).exists()

# Standard Edge install locations on Windows. The 32-bit-suffix path is the
# default for Stable, but Insider / per-user installs can land in the other.
EDGE_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


class PDFExportError(Exception):
    """Raised when Microsoft Edge is not installed at any expected path."""


def find_edge_executable():
    """Return the Path to msedge.exe, or raise PDFExportError if not found."""
    for p in EDGE_PATHS:
        if p.exists():
            return p
    raise PDFExportError(
        "Microsoft Edge not found. Checked: "
        + " | ".join(str(p) for p in EDGE_PATHS)
    )


def render_html_to_pdf(html_path, pdf_path, timeout_sec=60):
    """Render an HTML file to PDF using headless Edge.

    Args:
      html_path: Path or str — must exist on disk. Should be self-contained
                 (inline CSS, no external/network assets) so the render is
                 deterministic and doesn't depend on whether Edge can reach
                 the dashboard's static-file route.
      pdf_path:  Path or str — destination. Parent dirs are created.
      timeout_sec: hard cap on Edge process runtime (default 60s — generous
                   ceiling so a slow first-launch Edge doesn't hit the limit,
                   but well under any reasonable operator patience for the
                   finalize request to return). On timeout, subprocess.run
                   kills the Edge process via Popen.kill() (Python stdlib
                   contract) and we return ok=False so the caller WARNs and
                   finalize still returns 201 — the DCR is the source of
                   truth; the PDF is derivative and can be regenerated.

    Returns dict:
      {"ok": True,  "pdf_path": "<abs>", "edge_path": "<abs>", "size": int}
      {"ok": False, "edge_path": "<abs>", "error": "<reason>"}

    Raises PDFExportError if Edge isn't installed (setup problem).
    """
    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    if not html_path.exists():
        return {"ok": False, "error": f"HTML not found: {html_path}"}

    edge = find_edge_executable()

    # Fresh per-render profile dir. Without --user-data-dir Edge attaches to
    # any running edge.exe instance and silently skips --print-to-pdf. With a
    # FRESH temp dir each invocation, we get a guaranteed new browser process.
    # Not using `with TemporaryDirectory(...)` — Edge holds file handles in the
    # profile briefly after subprocess.run() returns, racing the auto-cleanup
    # and crashing with WinError 32. mkdtemp + best-effort cleanup avoids that.
    profile_dir = tempfile.mkdtemp(prefix="dcr_edge_")
    try:
        # --headless=old is required for reliable --print-to-pdf. The newer
        # --headless=new mode sometimes exits 0 without flushing the PDF in
        # recent Edge/Chromium versions. Tracked upstream as a long-standing
        # quirk; for a release surface like a DCR, we want determinism.
        cmd = [
            str(edge),
            "--headless=old",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile_dir}",
            "--virtual-time-budget=5000",  # let the page settle before printing
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),  # file:///C:/Users/...
        ]
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_sec
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "edge_path": str(edge),
                    "error": f"Edge timed out after {timeout_sec}s"}
        except Exception as e:
            return {"ok": False, "edge_path": str(edge),
                    "error": f"Edge subprocess failed: {e}"}

        stderr_tail = (result.stderr or "").strip()[-500:]
        stdout_tail = (result.stdout or "").strip()[-500:]
        if result.returncode != 0:
            return {
                "ok": False,
                "edge_path": str(edge),
                "error": f"Edge exited rc={result.returncode}: {stderr_tail or stdout_tail}",
            }
        # Edge sometimes writes the file just after subprocess.run() returns
        # on Windows (filesystem flush lag). Poll briefly before giving up.
        for _ in range(20):
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                break
            time.sleep(0.1)
        if not pdf_path.exists():
            return {"ok": False, "edge_path": str(edge),
                    "error": f"Edge exited 0 but no PDF written. stderr_tail: {stderr_tail}"}
        size = pdf_path.stat().st_size
        if size == 0:
            return {"ok": False, "edge_path": str(edge),
                    "error": f"PDF written but is 0 bytes. stderr_tail: {stderr_tail}"}
        return {"ok": True, "pdf_path": str(pdf_path),
                "edge_path": str(edge), "size": size}
    finally:
        _best_effort_rmtree(profile_dir)


def slugify_for_filename(s, fallback="unknown"):
    """Lightweight slugifier for filenames: keep alnum, replace spaces with
    hyphens, strip everything else. Not for URLs — for human-readable files."""
    if not s:
        return fallback
    import re
    out = re.sub(r"[^A-Za-z0-9 _-]", "", str(s))
    out = re.sub(r"\s+", "-", out).strip("-_")
    return out or fallback


if __name__ == "__main__":
    # Tiny CLI for ad-hoc verification:
    #   python pdf_export.py <html_in> <pdf_out>
    import sys
    if len(sys.argv) != 3:
        print("usage: pdf_export.py <html_in> <pdf_out>", file=sys.stderr)
        sys.exit(2)
    try:
        r = render_html_to_pdf(sys.argv[1], sys.argv[2])
    except PDFExportError as e:
        print(f"setup error: {e}", file=sys.stderr)
        sys.exit(3)
    if r["ok"]:
        print(f"ok: {r['pdf_path']} ({r['size']} bytes, edge={r['edge_path']})")
    else:
        print(f"failed: {r['error']}", file=sys.stderr)
        sys.exit(1)
