# Testing Limits — Validated Capacity Ceilings

A living record of what volumes / ranges of the Superstars dashboard have been
exercised under automated smoke tests. The intent is straightforward: the
team should always know the **proven** boundaries, so that when an operator
or an agent pushes into unverified territory they do so knowingly, not
blindly.

## How to read this table

- **Validated ceiling** — the highest N that has been tested clean (zero
  assertion failures) in a controlled smoke run.
- **Result at ceiling** — the outcome of the most recent run at that N
  (status + headline performance numbers).
- **Watch zone** — qualitative notes on where performance starts to soften
  approaching the ceiling, and what happens beyond it. **Beyond the ceiling
  is UNVERIFIED, not known-broken** — it may well work, but no one has
  proven it yet.
- **Notes** — observations, known causes of variance, links to the smoke
  test that produced the row.

## Discipline

Every future stress test or capacity push that surfaces a new ceiling, or
extends an existing one, **must add or update a row here**. The doc is only
useful if it stays current — a stale ceiling is worse than no ceiling at
all because it implies false confidence.

When a smoke test surfaces a regression (a previously-clean ceiling now
fails), update the Result and Notes columns — do not silently drop the row.

---

## Validated ceilings

| Capability | Validated ceiling | Result at ceiling | Watch zone | Notes |
|---|---|---|---|---|
| **DCR sequential issuance** | 200 DCRs | clean (200/200), p50 1.5s, p95 4.2s, p99 ~9s | perf softens approaching 200; >200 unverified | Open-Meteo weather aggregator causes p99 outliers. See `tests/smoke_dcr_volume.py`. |
| **DCR delete + gap-fill re-issue** | 30 cycles | clean (30/30 gap-fills produced the expected reused sequence) | >30 cycles unverified | sequence gap-fill confirmed working (`next_dcr_sequence` returns lowest unused). See `tests/smoke_dcr_volume.py` phase 2. |
| **Backdated DCRs with manual labor** | 30 days | clean (30/30), p50 1.1s, p95 2.0s, max 2.6s; first→second-half degradation +15.2% | mild degradation observed; >30 days unverified | exercises POST `/api/sign-ins` with both `time_in` + `time_out` + backdated `date`. 8 pass / 0 fail in latest run. See `tests/smoke_dcr_backdated_30day.py`. |
| **Concurrent form saves under issue race** | not isolated-tested | n/a | any rapid multi-save scenario | form-state bug fixed in `fix(dashboard): reset DCR entry form state cleanly between issuances`; `pendingSaves` Set awaits in-flight saveRow Promises before `issueDcr` POSTs. Not yet exercised by an automated race test. |
| **Worker count (single project)** | 8 (real Mott Haven roster) | clean | untested at 50+ / 100+ | the form's worker dropdown and the DCR labor aggregator are O(N) over the project's assigned workers; both should scale, but unverified beyond the current roster. |
| **Certs per worker** | low (POC only — 1 test cert + 1 CoF in prior verification) | n/a | untested at scale | cert intake pipeline has no known issues but has not been exercised with 10+ certs per worker. |
| **Photos per DCR** | low (smoke tests don't generate photos) | n/a | untested at scale | upload path uses `/api/photos` with multipart; aggregator includes photo metadata in section 11. No bulk-upload test exists. |
| **Workers signed in per day** | up to 4 per day (within the 30-day backdated run) | clean | untested at 20+ per day | the DCR labor section renders one `<tr>` per sign-in; no pagination. At very high crew sizes (50+) the rendered HTML grows but should still render. |
| **DCRs in archive** | 200 (during the volume smoke) | clean — archive endpoint returned all 200 distinct sequences | >200 unverified — archive list rendering may need pagination at scale | archive GET endpoint is unfiltered SELECT ORDER BY; no LIMIT. UI lists all in one table. |

---

## Smoke test inventory

| Test | Scope | Frequency |
|---|---|---|
| `tests/smoke_dcr_volume.py` | 200 sequential issuances + 30 delete/gap-fill cycles + cleanup. ~7 min. | Before any sustained-load change or refactor of the DCR issuance path. |
| `tests/smoke_dcr_backdated_30day.py` | 30 backdated days with manual labor entries + work_log + deliveries + cleanup. ~40 s. | Before any change to `POST /api/sign-ins`, the labor section, or the DCR aggregator's labor pull. Also any time backdated entry is being relied on operationally. |

Run each manually as needed:

```
python tests/smoke_dcr_volume.py
python tests/smoke_dcr_backdated_30day.py
```

Both scripts manage their own server lifecycle, clean up everything they create, and exit non-zero on any assertion failure.

## When to push a ceiling higher

Reasonable triggers:

- Operational scope expands (e.g., second project added → worker pool doubles).
- An operator reports degraded performance in real use.
- Before a sustained-load period (a big backlog of backdated DCRs to enter, a roster expansion, a photo-heavy day).
- After any refactor of an issuance / aggregator / archive code path.

When pushing a ceiling, extend the existing smoke test's `N` constant (or fork a new variant) and update the corresponding row here with the new validated N + result.
