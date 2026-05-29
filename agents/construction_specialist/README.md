# agents/construction_specialist/ — Construction Specialist Agent (Phase A / v0)

Co-located **definition + corpus** for SSC's foundational AI specialist (spec
decision Q4). Discoverable to Claude Code's Task tool via the thin stub at
`.claude/agents/construction-specialist.md`. Contract: `CONSTRUCTION_SPECIALIST_AGENT_SPEC.md`
(v1.2) in the Superstars Dashboard project folder.

## Layout

| Path | What |
|------|------|
| `construction_specialist.md` | Authoritative operating contract (persona, scope, gates, answer shape, provenance step). |
| `provenance.py` | PII-safe provenance writer (importable + CLI). One audit row per substantive interaction. |
| `corpus/` | Version-controlled MVP context pack. |
| `corpus/CORPUS_MANIFEST.md` / `corpus_manifest.json` | What's in vs. deferred; the `CORPUS_VERSION` stamp. |
| `corpus/chapter33/` | Chapter 33 orientation index (C1), from `toolbox_talks_data.py`. |
| `corpus/sika/` | Sika spec index (C2), from the `spec_products` table. |
| `corpus/_deferred/` | Clearly-marked placeholders (LL11/77/126, SPRAT/IRATA, deep product write-ups) — a separate later batch. |
| `corpus/build_corpus.py` | Regenerates the corpus indexes + re-stamps `CORPUS_VERSION`. |
| `.claude/agents/construction-specialist.md` | Discovery stub (repo root). |

## Invoke (MVP = Claude Code Task-tool sub-agent)

```
Task(subagent_type="construction-specialist", prompt="<your construction question>")
```

The sub-agent reads its contract + the relevant corpus index, answers
citation-anchored with an adjacency prompt, hard-declines/routes anything
out of scope (EOR/architect/attorney/attestation; procurement = draft+analyze
only), and writes **exactly one** PII-safe row to `construction_agent_provenance`.

## Audit trail

Every substantive interaction → one row in `construction_agent_provenance`
(migration: `apply_construction_agent_provenance_schema.py`). PII-safe: W-#### only,
no names/PINs/rates. The anti-corruption meta-smoke
(`tests/smoke_no_production_data_corruption.py`) snapshots the table as a backstop;
the surface's own regression net is `tests/smoke_construction_agent.py`.

## Regenerate corpus / re-stamp version

```
python agents/construction_specialist/corpus/build_corpus.py
```
