# Construction Specialist Agent — Corpus Manifest

**CORPUS_VERSION:** `v0.2-2026-05-28-129ebd404f52`
(stamp = `v0.2` + local build date + `sha256(corpus_manifest.json)[:12]`; regenerate with `build_corpus.py`)

**Phase:** A / v0.2 — MVP scaffolding (#198) **+ frequent-three product systems (#198 Batch 2)**.
The C1/C2 base was assembled from what already lives in the app repo; the three product
write-ups (C10/C12/C13) are **validated public/manufacturer technical literature** curated
2026-05-28. Remaining public-source curation (LL11/77/126, SPRAT/IRATA, Sto/EIFS, roofing,
software/engineering/architectural/process) stays a **separate later batch**.

The machine-readable manifest is `corpus_manifest.json`. This file is the human
companion. Per spec §4, this manifest is the live record of what the agent reasons
from until the Documentation Librarian agent takes ownership.

---

## Included

| # | Item | Source | Files | Count |
|---|---|---|---|---|
| C1 | NYC Building Code **Chapter 33** — Safeguards During Construction | `toolbox_talks_data.py` (19 §-tagged toolbox talks) | `chapter33/ch33_index.md`, `chapter33/ch33_index.json` | 19 topics |
| C2 | **Sika** product specifications | `spec_products` table in `superstars.db` | `sika/sika_spec_index.md`, `sika/sika_spec_index.json` | 107 products, 10 categories |
| C10 | **Concrete repair** systems | validated public/manufacturer technical literature (2026-05-28) | `products/concrete_repair.md` | frequent-three |
| C13 | **Sealants & joint design** | validated public/manufacturer technical literature (2026-05-28) | `products/sealants_joint_design.md` | frequent-three |
| C12 | **Brick masonry & repointing** | validated public technical literature incl. NPS Brief 2 (2026-05-28) | `products/brick_masonry_repointing.md` | frequent-three |

**C1 note — orientation, not controlling text.** The Chapter 33 index is SSC's
plain-language distillation drawn from the toolbox-talk corpus, each entry carrying its
`§`-section reference. The controlling legal text is the official NYC Building Code
Chapter 33 (137 pp, 21 sections, amended by Local Law 77 of 2023). The **source PDF is
NOT in the repo** — `data_room/dob_codes/INSTRUCTIONS.md` lists BC-33 as *Pending
Download*. The operator can copy it from
`…\Superstars Dashboard\toolbox_source\DOB Chapter 33.pdf` into
`data_room/dob_codes/` when convenient; the agent does not block on it. The agent
cites the §-section and flags that exact text must be confirmed against the official code.

**C2 note — TDS is controlling.** The Sika index is extracted from the `spec_products`
table (the DB is gitignored; these committed index files are the version-controlled
corpus of record). For any product, the controlling document is the manufacturer-
published Technical Data Sheet at `spec_url`. The agent names the product, cites the
TDS, and flags that surface prep / mix ratios / cure times must be confirmed against the
current TDS.

**C10 / C13 / C12 note — the frequent three (operator decision Q7), validated 2026-05-28.**
Orientation references for concrete repair, sealants/joint design, and brick repointing.
Each names its governing standards (ICRI 310.2R, ASTM C928/C1583, ACI 546 / ASTM C920,
C1193 / NPS Brief 2, ASTM C270) and keeps a **"Flagged for verification"** section listing
the specific figures/designations that must be confirmed before being treated as hard spec.
Controlling authority is always the manufacturer TDS and the EOR/design professional; the
concrete file carries the incipient-anode and post-tension-deck safety cautions, and routes
structural decisions to the EOR. Sto/EIFS, roofing, and the broader product-systems library
are still v1.

---

## Deferred — clearly-marked placeholders (DO NOT fill this batch)

These are named for traceability only. See `_deferred/README.md`. Each, when curated in
a later batch, records its retrieval date + source URL so staleness is auditable.

| # | Item | Intended public source |
|---|---|---|
| C3 | SPRAT reference summary | sprat.org |
| C4 | IRATA reference summary | irata.org (ICOP / TACS) |
| C5 | Local Law 11 / FISP reference | NYC.gov / DOB, 1 RCNY §103-04 |
| C6 | Local Law 77 of 2023 summary | NYC.gov / DOB |
| C7 | Local Law 126 / Parking Structure Inspection | NYC.gov / DOB, 1 RCNY §103-13 |
| C11 | Sto & EIFS systems — deep write-up | Sto + public technical literature |
| C14 | Roofing membranes & assemblies — deep write-up | manufacturer public literature |
| C15–C20 | Software / engineering / architectural / NYC-process references | public docs |

---

## Regenerating / re-stamping

```
python agents/construction_specialist/corpus/build_corpus.py
```

Re-extracts C1 from `toolbox_talks_data.py` and C2 from `superstars.db`, lists the
committed product files (C10/C12/C13), rewrites the index files + `corpus_manifest.json`,
and re-computes `CORPUS_VERSION`. Bump happens automatically when a source changes (the
version is a content hash). Update the stamp quoted at the top of this file to match after
re-running. (The product `.md` files are hand-curated and committed verbatim — they are
listed by, not generated by, `build_corpus.py`.)
