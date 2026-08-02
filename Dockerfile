# =====================================================================
# Dockerfile — SSC dashboard cloud image (#290, Cloud M4)
#
# Built by Render from the GitHub repo (see render.yaml). One image runs
# the whole app: waitress + Flask (server:app), chromium for PDF export
# (#288 SSC_PDF_ENGINE=chromium), tzdata for SSC_TZ enforcement (#290).
#
# BIND CONTRACT NOTE (deliberate exception to the CLAUDE.md loopback
# policy): this container binds 0.0.0.0:$PORT. The loopback-only rule
# exists because the WORKSTATION sits on a shared coworking-space LAN;
# a Render container has no LAN — its network namespace is private and
# the ONLY ingress is Render's TLS-terminating proxy, which routes to
# $PORT. Binding loopback here would make the service unreachable.
# The workstation deployment keeps 127.0.0.1:5050, unchanged.
# =====================================================================

FROM python:3.12-slim

# System deps:
#   chromium          — the #288 PDF engine (SSC_CHROMIUM_PATH=/usr/bin/chromium)
#   fonts-inter       — the brand typeface the DCR/report renders name first
#   fonts-liberation  — metric-compatible Arial/Helvetica fallbacks
#   fonts-dejavu-core — broad glyph coverage backstop
#   tzdata            — IANA zone db; load-bearing for SSC_TZ (#290) — without
#                       it TZ=America/New_York cannot resolve and glibc would
#                       silently run UTC
#   ca-certificates   — outbound TLS (Anthropic, SendGrid, Google JWKS)
#   rsync, gzip       — media-tree transfer target for the M4 rehearsal /
#                       M5 final sync (tar/scp/rsync over Render SSH)
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-inter \
        fonts-liberation \
        fonts-dejavu-core \
        tzdata \
        ca-certificates \
        rsync \
        gzip \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Layer-cache the dependency install: requirements change far less often
# than code. WeasyPrint installs from pip but its GTK/pango system libs are
# deliberately NOT installed — render_pdf.py is the legacy WeasyPrint CLI,
# never imported by the server (pdf_export.py + chromium is the production
# path, #288).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render routes to $PORT (default 10000). EXPOSE is documentation only.
EXPOSE 10000

# exec so waitress is PID 1 and receives Render's stop signals directly.
# WAITRESS_THREADS (render.yaml, default 16): the workload is I/O-heavy —
# photo bursts + per-request PG round trips park threads on sockets, so
# 16 threads on 1 vCPU is headroom, not oversubscription (#290 hotfix:
# a 20-thumb burst queued 20-deep on 8 threads). Tune in the dashboard
# without an image rebuild.
CMD ["sh", "-c", "exec python -m waitress --host=0.0.0.0 --port=${PORT:-10000} --threads=${WAITRESS_THREADS:-16} server:app"]
