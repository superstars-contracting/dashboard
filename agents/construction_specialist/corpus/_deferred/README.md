# Deferred corpus items — PLACEHOLDERS ONLY

**Do NOT fill these in the Phase A / v0 scaffolding batch (#198).**

These items are curated from **public sources** in a **separate later batch**. They are
listed here for traceability so the agent (and the operator) know what is intentionally
absent vs. what was forgotten. The agent must treat any topic below as **not in corpus**:
answer from general knowledge *and explicitly flag it as unverified, to be confirmed
against the official source* — never fabricate a citation.

When a later batch curates one of these, it must:
1. Record the **retrieval date** and **source URL** (spec §4 governance — staleness is auditable).
2. Add the item's files to `corpus_manifest.json` (move it from `deferred_public_sources` to `included`).
3. Re-run `build_corpus.py` to re-stamp `CORPUS_VERSION`.

| # | Item | Intended public source | Status |
|---|---|---|---|
| C3 | SPRAT reference summary (technician levels 1/2/3, safe-practices, rescue/two-rope) | sprat.org (public publications) | **deferred** |
| C4 | IRATA reference summary (ICOP / TACS, level definitions) | irata.org (public) | **deferred** |
| C5 | Local Law 11 / FISP reference (filing cycles, SWARMP/SAFE/Unsafe, QEWI) | NYC.gov / DOB, 1 RCNY §103-04 | **deferred** |
| C6 | Local Law 77 of 2023 summary (Ch 33 construction-safety amendments) | NYC.gov / DOB | **deferred** |
| C7 | Local Law 126 / Parking Structure Inspection (cadence, Safe/SREM/Unsafe, QPSI) | NYC.gov / DOB, 1 RCNY §103-13 | **deferred** |
| C10 | Concrete & cementitious systems — deep write-up | manufacturer / public technical literature | **deferred** |
| C11 | Sto & EIFS systems — deep write-up | Sto + public technical literature | **deferred** |
| C12 | Brick & masonry systems — deep write-up | BIA + manufacturer data | **deferred** |
| C13 | Sealants, coatings, water repellents — deep write-up | manufacturer data sheets | **deferred** |
| C14 | Roofing membranes & assemblies — deep write-up | manufacturer public literature | **deferred** |
| C15 | Software reference — Bluebeam Revu | public docs | **deferred** |
| C16 | Software reference — Revit / AutoCAD | public docs | **deferred** |
| C17 | Software reference — Primavera (P6/P3) | public docs | **deferred** |
| C18 | Engineering & building-science reference (literacy only) | public sources | **deferred** |
| C19 | Architectural reference (CSI MasterFormat, detailing) | public sources | **deferred** |
| C20 | NYC construction-process reference (permit lifecycle, submittal vs transmittal) | DOB / DOB NOW + industry practice | **deferred** |
