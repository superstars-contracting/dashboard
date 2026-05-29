# Construction Specialist Agent — Corpus Manifest

**CORPUS_VERSION:** `v0-2026-05-28-a8d60f6147e4`
(stamp = `v0` + local build date + `sha256(corpus_manifest.json)[:12]`; regenerate with `build_corpus.py`)

**Phase:** A / v0 — MVP scaffolding (#198). Corpus assembled from **only what already
lives in the app repo.** Public-source curation (Local Law 11/77/126, SPRAT/IRATA,
deep product-systems write-ups) is a **separate later batch** and is NOT done here.

The machine-readable manifest is `corpus_manifest.json`. This file is the human
companion. Per spec §4, this manifest is the live record of what the agent reasons
from until the Documentation Librarian agent takes ownership.

---

## Included this batch (from the repo)

| # | Item | Source | Files | Count |
|---|---|---|---|---|
| C1 | NYC Building Code **Chapter 33** — Safeguards During Construction | `toolbox_talks_data.py` (19 §-tagged toolbox talks) | `chapter33/ch33_index.md`, `chapter33/ch33_index.json` | 19 topics |
| C2 | **Sika** product specifications | `spec_products` table in `superstars.db` | `sika/sika_spec_index.md`, `sika/sika_spec_index.json` | 107 products, 10 categories |

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

**MVP product depth (operator decision Q7).** Deep on the **frequent three** —
concrete repair, Sika/sealants, brick repointing. Sto/EIFS, roofing, and the broader
product-systems library are v1.

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
| C10–C14 | Deep product-systems write-ups (concrete, Sto/EIFS, brick, sealants, roofing) | manufacturer + public technical literature |
| C15–C20 | Software / engineering / architectural / NYC-process references | public docs |

---

## Regenerating / re-stamping

```
python agents/construction_specialist/corpus/build_corpus.py
```

Re-extracts C1 from `toolbox_talks_data.py` and C2 from `superstars.db`, rewrites the
index files + `corpus_manifest.json`, and re-computes `CORPUS_VERSION`. Bump happens
automatically when a source changes (the version is a content hash). Update the stamp
quoted at the top of this file to match after re-running.
