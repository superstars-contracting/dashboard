"""
smoke_field_photos.py — Field Photos Phase 1 (#235).

HIGH-STAKES: the operator uploads REAL field photos tomorrow. This tests hard,
synthetic-only (synthetic project SMK-FOTO + PIL-generated images; real data
untouched; cleanup scoped to SMK-FOTO rows + its data_room/field_photos dir).

Covers:
  FUNCTIONAL: upload single+batch -> Unassigned; gallery + stats; unassigned
    time-clusters; BULK assign a group -> moves into the drop in the gallery;
    thumb/file gated serving; PATCH tags; DELETE row + both files; filters +
    group toggles; NO *_path anywhere.
  FIELD EDGE CASES (each with a generated fixture): sideways (EXIF Orientation 6)
    -> stored UPRIGHT (dims swapped, orientation_applied); DateTimeOriginal ->
    taken_at LOCAL exact (no off-by-one) + time-grouped; NO EXIF -> fallback date
    + estimated flag; HEIC -> processed; corrupt/non-image in a batch -> skipped
    with a reason, the rest still succeed; oversized count -> clean 400; duplicate
    re-upload -> handled (no crash).
  SPEED/STRESS (measured): ~250 mixed-size/format batch upload (chunked); seed
    ~1000 -> gallery paginates fast; ~300 Unassigned -> bulk-assign 300 in ONE
    call.
  GATING: unauth -> 401.
"""
import io
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from PIL import Image

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
FP_DIR = SCRIPT_DIR / "data_room" / "field_photos"
PROJECT = "SMK-FOTO"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def jpg(w, h, exif=None, noise=False):
    if noise:
        im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    else:
        im = Image.new("RGB", (w, h), (120, 90, 60))
    b = io.BytesIO()
    if exif is not None:
        im.save(b, "JPEG", exif=exif)
    else:
        im.save(b, "JPEG")
    return b.getvalue()


def heic(w, h):
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = Image.new("RGB", (w, h), (80, 120, 90))
    b = io.BytesIO()
    im.save(b, "HEIF")
    return b.getvalue()


def exif(dt=None, orient=None):
    ex = Image.Exif()
    if orient:
        ex[274] = orient
    if dt:
        ex[36867] = dt
    return ex


def upload(files, **tags):
    """files: list of (filename, bytes[, mime])."""
    mp = []
    for f in files:
        n, data = f[0], f[1]
        mime = f[2] if len(f) > 2 else "image/jpeg"
        mp.append(("photos", (n, io.BytesIO(data), mime)))
    return requests.post(f"{BASE}/api/projects/{PROJECT}/photos/upload", files=mp, data=tags, timeout=300)


def gallery(**params):
    return requests.get(f"{BASE}/api/projects/{PROJECT}/photos", params=params, timeout=60).json()["data"]


def has_path_leak(obj):
    import json
    blob = json.dumps(obj)
    return any(s in blob for s in ("file_path", "thumb_path", "field_photos\\", "field_photos/", "data_room"))


def setup():
    conn = db()
    conn.execute("INSERT OR IGNORE INTO projects (project_code,name,status) VALUES (?,?,?)",
                 (PROJECT, "SMK Field Photos", "active"))
    for seq, elev in [(1, "North"), (2, "West")]:
        conn.execute("INSERT OR IGNORE INTO drops (drop_id,project_code,elevation,sequence_no,lifecycle) "
                     "VALUES (?,?,?,?, 'not_started')", (f"{PROJECT}-DP{seq}", PROJECT, elev, seq))
    conn.commit()
    conn.close()


def functional():
    print("\n-- FUNCTIONAL --")
    # single upload -> Unassigned
    r = upload([("single.jpg", jpg(1600, 1200, exif=exif(dt="2026-06-05 09:00:00")))])
    ok("upload_single_201", r.status_code == 201, f"HTTP {r.status_code}")
    j = r.json()["data"]
    ok("single_stored_unassigned", j["stored_count"] == 1 and j["landed"] == "unassigned", str(j))
    ok("upload_no_path_leak", not has_path_leak(j))
    # batch upload -> Unassigned
    rb = upload([(f"b{i}.jpg", jpg(1200, 900, exif=exif(dt=f"2026-06-06 1{i}:00:00"))) for i in range(4)])
    ok("upload_batch_201", rb.status_code == 201 and rb.json()["data"]["stored_count"] == 4)
    # gallery + stats + no path
    g = gallery(group="all")
    ok("gallery_lists", g["total"] >= 5 and len(g["photos"]) >= 5, f"total={g['total']}")
    ok("gallery_stats", "total" in g["stats"] and g["stats"]["total"] >= 5)
    ok("gallery_no_path_leak", not has_path_leak(g))
    ok("gallery_has_drops_list", any(d["label"].startswith("DP-1") for d in g["drops"]))
    # thumb + file serving
    pid = g["photos"][0]["id"]
    th = requests.get(f"{BASE}/api/field-photos/{pid}/thumb", timeout=30)
    fl = requests.get(f"{BASE}/api/field-photos/{pid}/file", timeout=30)
    ok("thumb_serves", th.status_code == 200 and th.headers.get("Content-Type", "").startswith("image/"))
    ok("file_serves", fl.status_code == 200 and fl.headers.get("Content-Type", "").startswith("image/"))
    # unassigned time clusters
    u = requests.get(f"{BASE}/api/projects/{PROJECT}/photos/unassigned", timeout=30).json()["data"]
    ok("unassigned_clusters", len(u["clusters"]) >= 1 and u["count"] >= 5, f"clusters={len(u['clusters'])} count={u['count']}")
    ok("unassigned_no_path_leak", not has_path_leak(u))
    # BULK assign a set to DP1 -> moves into the drop
    ids = [p["id"] for p in g["photos"][:3]]
    a = requests.post(f"{BASE}/api/field-photos/assign",
                      json={"photo_ids": ids, "drop_id": f"{PROJECT}-DP1", "stage": "Survey"}, timeout=30)
    ok("assign_bulk_ok", a.status_code == 200 and a.json()["data"]["assigned"] == 3, f"HTTP {a.status_code}")
    gd = gallery(group="drop", drop_id=f"{PROJECT}-DP1")
    ok("assign_moves_into_drop", gd["total"] == 3 and all(p["drop_label"].startswith("DP-1") for p in gd["photos"]))
    ok("assign_stage_set", all(p["stage"] == "Survey" for p in gd["photos"]))
    # PATCH tags
    p1 = ids[0]
    pt = requests.patch(f"{BASE}/api/field-photos/{p1}", json={"caption": "north wall crack", "worker_id": "W-0002"}, timeout=20)
    ok("patch_tags", pt.status_code == 200 and pt.json()["data"]["caption"] == "north wall crack"
       and pt.json()["data"]["worker_id"] == "W-0002")
    ok("patch_no_path_leak", not has_path_leak(pt.json()["data"]))
    # filter by date + group toggle
    gf = gallery(group="time", date="2026-06-06")
    ok("filter_by_date", gf["total"] == 4, f"date-filtered total={gf['total']}")
    # DELETE -> row + files gone
    conn = db()
    fp_paths = conn.execute("SELECT file_path, thumb_path FROM field_photos WHERE id=?", (p1,)).fetchone()
    conn.close()
    dl = requests.delete(f"{BASE}/api/field-photos/{p1}", timeout=20)
    ok("delete_200", dl.status_code == 200)
    conn = db()
    gone = conn.execute("SELECT COUNT(*) FROM field_photos WHERE id=?", (p1,)).fetchone()[0] == 0
    conn.close()
    files_gone = not Path(fp_paths["file_path"]).exists() and not Path(fp_paths["thumb_path"]).exists()
    ok("delete_removes_row_and_files", gone and files_gone, f"row_gone={gone} files_gone={files_gone}")
    th404 = requests.get(f"{BASE}/api/field-photos/{p1}/thumb", timeout=20)
    ok("deleted_thumb_404", th404.status_code == 404)


def edge_cases():
    print("\n-- FIELD EDGE CASES --")
    # sideways (Orientation 6, stored 600x400 landscape) -> stored UPRIGHT (portrait)
    rs = upload([("sideways.jpg", jpg(600, 400, exif=exif(dt="2026-06-07 08:00:00", orient=6)))])
    sid = rs.json()["data"]["stored"][0]["id"]
    conn = db()
    row = conn.execute("SELECT width, height, orientation_applied FROM field_photos WHERE id=?", (sid,)).fetchone()
    conn.close()
    ok("sideways_upright", row["height"] > row["width"] and row["orientation_applied"] == 1,
       f"W={row['width']} H={row['height']} applied={row['orientation_applied']}")
    # DateTimeOriginal -> taken_at exact LOCAL (no off-by-one)
    rd = upload([("dated.jpg", jpg(1000, 800, exif=exif(dt="2026-06-08 14:23:45")))])
    ok("exif_date_exact", rd.json()["data"]["stored"][0]["taken_at"] == "2026-06-08 14:23:45"
       and rd.json()["data"]["stored"][0]["estimated"] is False)
    # NO EXIF -> fallback date + estimated flag (batch date used)
    rn = upload([("nodate.jpg", jpg(900, 700))], date="06/03/2026")
    s = rn.json()["data"]["stored"][0]
    ok("no_exif_estimated", s["estimated"] is True and s["taken_at"].startswith("2026-06-03"), str(s))
    # HEIC -> processed
    try:
        rh = upload([("iphone.heic", heic(1400, 1050), "image/heic")])
        ok("heic_processed", rh.status_code == 201 and rh.json()["data"]["stored_count"] == 1,
           f"stored={rh.json()['data']['stored_count']} skipped={rh.json()['data']['skipped']}")
    except Exception as e:
        ok("heic_processed", False, f"exc {e}")
    # corrupt + non-image in a batch -> skipped with reason, the rest succeed
    rc = upload([("good.jpg", jpg(800, 600)),
                 ("corrupt.jpg", b"this is not an image"),
                 ("note.txt", b"hello", "text/plain"),
                 ("good2.jpg", jpg(700, 500))])
    jc = rc.json()["data"]
    ok("batch_survives_bad_files", jc["stored_count"] == 2 and jc["skipped_count"] == 2, str(jc))
    ok("skip_has_reason", all(x.get("reason") for x in jc["skipped"]), str(jc["skipped"]))
    # oversized COUNT -> clean 400 (not 500)
    too_many = [(f"x{i}.jpg", jpg(80, 60)) for i in range(70)]
    ro = upload(too_many)
    ok("oversized_count_clean_400", ro.status_code == 400 and "max_files" in ro.json(), f"HTTP {ro.status_code}")
    # duplicate re-upload (same bytes/name) -> handled, two rows, no crash
    dup = jpg(1000, 800, exif=exif(dt="2026-06-08 11:11:11"))
    upload([("dup.jpg", dup)])
    rdup = upload([("dup.jpg", dup)])
    ok("duplicate_ok", rdup.status_code == 201 and rdup.json()["data"]["stored_count"] == 1)


def speed():
    print("\n-- SPEED / STRESS --")
    # 1) ~250 mixed-size/format batch upload (chunked, like the UI)
    imgs = []
    for i in range(250):
        if i % 20 == 0:   # ~13 genuinely large noisy images (~8-12 MB JPEG, like real iPhone shots)
            imgs.append((f"big_{i}.jpg", jpg(5000, 3800, noise=True)))
        else:
            imgs.append((f"sm_{i}.jpg", jpg(1024, 768, exif=exif(dt=f"2026-05-20 {8 + i % 10:02d}:{i % 60:02d}:00"))))
    total_bytes = sum(len(b) for _, b in imgs)
    t0 = time.perf_counter()
    stored = skipped = 0
    CHUNK = 25
    for k in range(0, len(imgs), CHUNK):
        r = upload(imgs[k:k + CHUNK])
        if r.status_code != 201:
            ok("stress_chunk_ok", False, f"chunk {k} HTTP {r.status_code}")
            break
        d = r.json()["data"]
        stored += d["stored_count"]
        skipped += d["skipped_count"]
    secs = time.perf_counter() - t0
    ok("stress_250_upload", stored == 250 and skipped == 0,
       f"{stored} stored / {skipped} skipped, {total_bytes // (1024 * 1024)}MB in {secs:.1f}s ({1000 * secs / 250:.0f}ms/img)")

    # 2) seed ~1000 (direct DB) -> gallery paginates fast
    seed_dir = FP_DIR / PROJECT / "_seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    full, thumb = seed_dir / "full.jpg", seed_dir / "thumb.jpg"
    if not full.exists():
        Image.new("RGB", (400, 300), (150, 140, 120)).save(full, "JPEG")
        Image.new("RGB", (120, 90), (150, 140, 120)).save(thumb, "JPEG")
    conn = db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base = datetime(2026, 5, 1, 12, 0, 0)
    rows = [(PROJECT, None, None, None, (base - timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
             0, now, None, str(full), str(thumb), f"seed_{i}.jpg", 12000, "image/jpeg", 400, 300, 0)
            for i in range(1000)]
    conn.executemany(
        "INSERT INTO field_photos (project_code,drop_id,worker_id,stage,taken_at,taken_at_estimated,uploaded_at,"
        "uploaded_by_uid,file_path,thumb_path,file_name,file_size,mime,width,height,orientation_applied) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    total_now = conn.execute("SELECT COUNT(*) FROM field_photos WHERE project_code=?", (PROJECT,)).fetchone()[0]
    conn.close()
    t = time.perf_counter()
    g = gallery(group="all", limit=60, offset=0)
    page_ms = (time.perf_counter() - t) * 1000
    ok("gallery_1000_paginates", len(g["photos"]) == 60 and g["has_more"] and g["total"] == total_now,
       f"{total_now} photos, page(60) in {page_ms:.0f}ms")
    ok("gallery_page_fast", page_ms < 1500, f"{page_ms:.0f}ms")

    # 3) ~300 Unassigned -> bulk-assign 300 in ONE call
    conn = db()
    unassigned_ids = [r[0] for r in conn.execute(
        "SELECT id FROM field_photos WHERE project_code=? AND drop_id IS NULL ORDER BY id LIMIT 300", (PROJECT,)).fetchall()]
    conn.close()
    t = time.perf_counter()
    a = requests.post(f"{BASE}/api/field-photos/assign",
                      json={"photo_ids": unassigned_ids, "drop_id": f"{PROJECT}-DP2"}, timeout=60)
    assign_ms = (time.perf_counter() - t) * 1000
    ok("bulk_assign_300_one_call", a.status_code == 200 and a.json()["data"]["assigned"] == len(unassigned_ids),
       f"assigned {a.json()['data']['assigned']} in {assign_ms:.0f}ms ({len(unassigned_ids)} ids)")


def gating():
    print("\n-- GATING --")
    s = requests.Session()
    r1 = s.get(f"{BASE}/api/projects/{PROJECT}/photos", timeout=20)
    r2 = s.post(f"{BASE}/api/projects/{PROJECT}/photos/upload",
                files=[("photos", ("a.jpg", io.BytesIO(jpg(100, 100)), "image/jpeg"))], timeout=20)
    ok("gallery_unauth_401", r1.status_code == 401, f"HTTP {r1.status_code}")
    ok("upload_unauth_401", r2.status_code == 401, f"HTTP {r2.status_code}")


def cleanup():
    print("\n-- CLEANUP (scoped to SMK-FOTO) --")
    conn = db()
    n = conn.execute("DELETE FROM field_photos WHERE project_code=?", (PROJECT,)).rowcount
    conn.execute("DELETE FROM drops WHERE project_code=?", (PROJECT,))
    conn.execute("DELETE FROM projects WHERE project_code=?", (PROJECT,))
    conn.commit()
    residue = conn.execute("SELECT COUNT(*) FROM field_photos WHERE project_code=?", (PROJECT,)).fetchone()[0]
    conn.close()
    pdir = FP_DIR / PROJECT
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
    print(f"    purged {n} photo rows; removed {pdir}")
    ok("cleanup_zero_residue", residue == 0 and not pdir.exists(), f"rows={residue} dir_exists={pdir.exists()}")


def main():
    print("== #235 Field Photos smoke ==")
    setup()
    try:
        functional()
        edge_cases()
        speed()
        gating()
    finally:
        cleanup()
    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
