"""#259 — unit checks for the SQLite/Postgres paramstyle adapter + hybrid Row.
Runs WITHOUT a database (pure-function checks of the dialect translation crux)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db_layer as d

PASS = FAIL = 0


def ck(label, got, want):
    global PASS, FAIL
    ok = got == want
    PASS += ok
    FAIL += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f"  got={got!r} want={want!r}"))


# ---- paramstyle: ? -> %s, and literal % -> %% (LIKE), ? inside '...' left alone ----
ck("qmark params", d.to_pg_sql("SELECT * FROM t WHERE a=? AND b=?"),
   "SELECT * FROM t WHERE a=%s AND b=%s")
ck("literal % in LIKE doubled + param", d.to_pg_sql("x LIKE '%@ex' AND id=?"),
   "x LIKE '%%@ex' AND id=%s")
ck("LIKE prefix pattern doubled", d.to_pg_sql("WHERE worker_id LIKE 'W-9%'"),
   "WHERE worker_id LIKE 'W-9%%'")
ck("param-style LIKE (% is in the bound param, not the SQL)", d.to_pg_sql("WHERE email LIKE ?"),
   "WHERE email LIKE %s")
ck("? inside a string literal is NOT a placeholder", d.to_pg_sql("WHERE note='is it ok?' AND id=?"),
   "WHERE note='is it ok?' AND id=%s")

# ---- hybrid Row: index AND key access, value-iteration, dict() ----
r = d.Row(["id", "email", "role"], [7, "a@b.c", "admin"])
ck("Row[int]", r[0], 7)
ck("Row[str]", r["email"], "a@b.c")
ck("Row value-iter (tuple unpack)", tuple(r), (7, "a@b.c", "admin"))
ck("Row keys()", r.keys(), ["id", "email", "role"])
ck("dict(Row)", dict(r), {"id": 7, "email": "a@b.c", "role": "admin"})
ck("'k' in Row", "role" in r, True)

print(f"\n== db_layer adapter: {PASS} PASS / {FAIL} FAIL ==")
print("OVERALL:", "PASS" if FAIL == 0 else "FAIL")
sys.exit(0 if FAIL == 0 else 1)
