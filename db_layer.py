"""Env-driven SQLite/Postgres database access layer (#259, hosting-migration phase 1).

ONE place every connection goes through. Driven by the SSC_DB_URL env var:

  * unset / "sqlite" / a filesystem path  -> sqlite3 (the DEFAULT — production path,
    byte-for-byte unchanged: same timeout, row_factory=Row, WAL + busy_timeout).
  * "postgres://..." / "postgresql://..."  -> psycopg v3, wrapped to present the SAME
    interface the existing sqlite3 code uses (conn.execute(sql, params).fetchone(),
    cur.lastrowid, row["col"] AND row[0], `with conn:`, etc.).

This is ADDITIVE: SQLite stays the default so production is unaffected and we keep a
safety net. It ALSO gives test-isolation-from-prod — the gate can point SSC_DB_URL at
a SEPARATE Postgres test database and never touch the live SQLite file.

NO production cutover here (#259 is local/isolated only). Dates stay TEXT/ISO (LOCAL,
never UTC) on both backends — we never convert to timestamptz.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = SCRIPT_DIR / "superstars.db"


def db_url() -> str:
    return (os.environ.get("SSC_DB_URL") or "").strip()


def is_postgres() -> bool:
    u = db_url().lower()
    return u.startswith("postgres://") or u.startswith("postgresql://")


def _sqlite_path_from_url():
    """If SSC_DB_URL names a sqlite file (sqlite:///C:/x.db or sqlite:C:/x.db) return
    that path, else None. Lets the gate run against an ISOLATED COPY of the snapshot
    so the live superstars.db is never written to (test-isolation prerequisite, #259)."""
    u = db_url()
    if not u or is_postgres():
        return None
    low = u.lower()
    if low.startswith("sqlite:"):
        rest = u[len("sqlite:"):]
        rest = rest.lstrip("/") if rest.startswith("///") else rest.lstrip("/") if rest.startswith("//") else rest
        return rest or None
    return None


# =====================================================================
# paramstyle adapter: sqlite '?' qmark  ->  psycopg '%s' pyformat.
# CRITICAL: psycopg treats '%' in the SQL text specially, so every LITERAL '%'
# (e.g. LIKE '%foo%') must be doubled to '%%'. A blind ?->%s replace breaks LIKE.
# We walk the string so a '?' INSIDE a string literal is left alone, and we double
# every literal '%' (incl. inside string literals, which is where LIKE patterns live).
# =====================================================================
_INSERT_RE = re.compile(r"^\s*INSERT\s+(?:OR\s+(IGNORE|REPLACE)\s+)?INTO\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?",
                        re.IGNORECASE)


def to_pg_sql(sql: str) -> str:
    """Translate qmark placeholders -> pyformat, doubling literal % for psycopg."""
    # SQLite last_insert_rowid() -> Postgres lastval() (last identity value this session)
    sql = re.sub(r"last_insert_rowid\s*\(\s*\)", "lastval()", sql, flags=re.IGNORECASE)
    out = []
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
            out.append(ch)
        elif ch == "%":
            out.append("%%")
        elif ch == "?" and not in_str:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


# =====================================================================
# Postgres path (lazy import of psycopg so SQLite-only installs never need it)
# =====================================================================

# #292 — per-(url, SSC_TZ) connection pools. Keyed by tz as well as url so the
# env-read-per-call doctrine holds: a caller that sets SSC_TZ (the tz gate
# suite; the cloud process after ssc_tz.enforce) draws connections whose
# session TimeZone matches, and a caller without it never receives one that
# has it. Pools are process-lived; min_size=0 means an import alone never
# opens a socket.
import threading as _threading

_POOLS: dict = {}
_POOLS_LOCK = _threading.Lock()


def _pool_for(url):
    tz = (os.environ.get("SSC_TZ") or "").strip()
    key = (url, tz)
    pool = _POOLS.get(key)
    if pool is not None:
        return pool
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            from psycopg_pool import ConnectionPool
            kwargs = {"autocommit": False, "row_factory": _hybrid_row_factory}
            if tz:
                kwargs["options"] = f"-c TimeZone={tz}"   # #290 — rides per connection
            pool = ConnectionPool(url, min_size=0, max_size=12, max_idle=300.0,
                                  timeout=30.0, kwargs=kwargs, open=True)
            _POOLS[key] = pool
    return pool

class Row(dict):
    """sqlite3.Row work-alike over a Postgres tuple: supports BOTH row["col"] and
    row[0], iterates VALUES (so `a, b = row` and `list(row)` match sqlite), and is a
    real dict so dict(row) / 'k' in row / row.get('k') keep working."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._cols = tuple(cols)
        self._vals = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return dict.__getitem__(self, key)

    def __iter__(self):
        return iter(self._vals)        # sqlite Row iterates values, not keys

    def keys(self):
        return list(self._cols)


def _hybrid_row_factory(cursor):
    cols = [c.name for c in (cursor.description or [])]

    def make(values):
        return Row(cols, values)
    return make


class _NoopCursor:
    """For statements that don't apply to Postgres (PRAGMA ...)."""
    lastrowid = None
    rowcount = -1

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, n=1):
        return []

    def __iter__(self):
        return iter(())


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, n=1):
        return self._cur.fetchmany(n)

    def execute(self, sql, params=()):
        return _exec(self._cur, sql, params)

    def __iter__(self):
        return iter(self._cur)


# #290 hotfix — the pk map is a property of the DATABASE SCHEMA, not the
# connection, yet it was recomputed (a pg_catalog join) on EVERY connect().
# The app opens a connection per request, so on the cloud every request paid
# a needless catalog query on top of the TCP+auth handshake (~hundreds of ms
# across a console page's API fan-out). Cache per (url) per process. Schema
# changes only happen at boot/deploy in this app (ensure-at-boot migrations),
# so a stale entry cannot occur within a process lifetime; a table created
# mid-process would merely lack transparent lastrowid until restart.
_PKMAP_CACHE: dict = {}


def _pk_map(conn) -> dict:
    """table(lower) -> single-column integer PK name, for transparent lastrowid via
    RETURNING. Composite/no-PK tables are absent (lastrowid stays None there)."""
    sql = (
        "SELECT c.relname AS tbl, a.attname AS pk "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indisprimary AND array_length(i.indkey, 1) = 1 AND n.nspname = 'public'"
    )
    out = {}
    cur = conn.cursor()
    cur.execute(sql)
    for r in cur.fetchall():
        out[str(r[0]).lower()] = str(r[1])
    cur.close()
    return out


def _exec(cur, sql, params, pkmap=None):
    """Run one statement on a psycopg cursor with sqlite-style semantics."""
    stripped = sql.lstrip()
    head = stripped[:6].upper()
    if head == "PRAGMA":
        return _NoopCursor()
    pg = to_pg_sql(sql)
    lastrowid = None
    m = _INSERT_RE.match(sql)
    if m:
        orkind = (m.group(1) or "").upper()
        tbl = m.group(2).lower()
        if orkind == "IGNORE":
            # SQLite OR IGNORE -> Postgres ON CONFLICT DO NOTHING (any unique/pk conflict)
            pg = re.sub(r"^(\s*INSERT)\s+OR\s+IGNORE\s+INTO", r"\1 INTO", pg, count=1, flags=re.IGNORECASE)
            if "on conflict" not in pg.lower():
                pg = pg.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        elif orkind == "REPLACE":
            # OR REPLACE has no generic 1:1 PG form (needs conflict target + SET); the
            # callers that use it are dialect-fixed explicitly. Strip to a plain INSERT.
            pg = re.sub(r"^(\s*INSERT)\s+OR\s+REPLACE\s+INTO", r"\1 INTO", pg, count=1, flags=re.IGNORECASE)
        # transparent lastrowid: append RETURNING <pk> when caller didn't ask for it
        if pkmap and "returning" not in pg.lower() and orkind != "IGNORE":
            pk = pkmap.get(tbl)
            if pk:
                pg = pg.rstrip().rstrip(";") + f' RETURNING "{pk}"'
                cur.execute(pg, tuple(params) if params else ())
                row = cur.fetchone()
                if row is not None:
                    try:
                        lastrowid = row[0]
                    except Exception:
                        lastrowid = None
                return _PgCursor(cur, lastrowid)
    cur.execute(pg, tuple(params) if params else ())
    return _PgCursor(cur, lastrowid)


class _PgConn:
    """psycopg connection wrapped to mimic sqlite3.Connection for the app's idioms."""

    def __init__(self, url):
        # #292 — connections come from a per-URL POOL: a fresh network+TLS+auth
        # handshake cost ~100-200ms on the cloud and every request (and every
        # PARALLEL aggregate part) was paying it. The pool hands back a warm
        # connection; _PgConn.close() RETURNS it (rollback first) instead of
        # closing. #290's TimeZone startup option rides in the pool's conninfo.
        self._pool = _pool_for(url)     # held so putconn targets the SAME pool
        self._conn = self._pool.getconn()
        self.row_factory = None       # assignment accepted + ignored (always hybrid Row)
        pk = _PKMAP_CACHE.get(url)
        if pk is None:
            pk = _pk_map(self._conn)
            _PKMAP_CACHE[url] = pk
        self._pkmap = pk

    def execute(self, sql, params=()):
        return _exec(self._conn.cursor(), sql, params, self._pkmap)

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(to_pg_sql(sql), [tuple(p) for p in seq])
        return _PgCursor(cur)

    def executescript(self, script):
        # sqlite executescript: run a multi-statement string. Split on ';' boundaries.
        for stmt in _split_sql(script):
            self._conn.cursor().execute(to_pg_sql(stmt))
        return _NoopCursor()

    def cursor(self):
        return _PgCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # #292 — return to the pool, never actually close. Rollback first so a
        # borrowed connection can never carry uncommitted work (byte-equivalent
        # to what a real close did to uncommitted state).
        if self._conn is None:
            return
        c, self._conn = self._conn, None
        try:
            c.rollback()
        except Exception:
            pass
        try:
            self._pool.putconn(c)
        except Exception:
            try:
                c.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


def _split_sql(script: str):
    """Naive ;-splitter for executescript / .sql files (good enough for our DDL: no
    ';' inside string literals or dollar-quoted bodies in these files)."""
    out, buf, in_str = [], [], False
    for ch in script:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


# =====================================================================
# the one entry point
# =====================================================================

def connect(sqlite_path=None, pragma_fk: bool = False):
    """Return a connection honoring SSC_DB_URL. SQLite is the default and is returned
    as a NATIVE sqlite3 connection (production path unchanged). `sqlite_path` lets a
    caller (a smoke / a migration) target a specific .db file; it's ignored on Postgres.
    `pragma_fk` turns on SQLite FK enforcement (Postgres always enforces FKs)."""
    if is_postgres():
        return _PgConn(db_url())
    # explicit arg > SSC_DB_URL sqlite path > default live file
    import ssc_paths  # #287 — local import: db_layer loads before app modules
    path = str(sqlite_path) if sqlite_path else (_sqlite_path_from_url() or str(ssc_paths.sqlite_db_path()))
    conn = sqlite3.connect(path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    if pragma_fk:
        conn.execute("PRAGMA foreign_keys=ON;")
    return conn
