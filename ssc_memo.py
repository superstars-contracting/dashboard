"""#292 — ssc_memo: the HOUSE write-invalidated memoization layer.

Expensive NEUTRAL compute is cached per scope and served while the scope's
GENERATION is unchanged; domain WRITES bump the generation. Freshness is a
fact derived from writes, never a guess: **TTL freshness-guessing is banned**
(HANDOFF doctrine). Time-dependent computations put the date IN the scope key
(('labor_cost', code, '2026-08-04')) — a new day is a new key by
construction, not an expiry heuristic.

SECURITY BOUNDARY (non-negotiable): this layer caches the RAW AGGREGATION
only — the expensive, role-NEUTRAL compute. Role gating, payload curation,
key omission, and audience shaping happen per-request ABOVE the cache. A
cached computation must never let one role see another role's shaped
payload; the guard suite proves it with a two-role probe. Serves are
DEEP COPIES so a caller shaping its response can never mutate the cache.

Generations are two-level and additive: bump(domain) invalidates every
scope under the domain (a worker RATE change crosses projects); bump(domain,
leaf...) invalidates one. memoize() captures the generation BEFORE compute,
so a write landing mid-compute leaves the stored entry already-stale —
the next read recomputes. Single-flight: concurrent callers of one scope
produce ONE compute (pool-parallel aggregate parts included).

Process-local by design: recompute-on-boot is correct, and a second app
instance is safe-by-miss (its own cache, its own generations), never wrong.

Registered domains (extensible — one bump line at each write site):
  labor_cost   — sign-in writes (manual add/edit/delete, worker-app in/out,
                 DCR reconcile), rate changes (approve/initial/set — bump the
                 DOMAIN: rates are per-worker and cross projects), expense
                 create/void (defense-in-depth: expenses are currently
                 live-computed above the cached labor engine).
  drop_rollup  — drop/stage-status writes (wired when the census numbers
                 indict the rollup; the layer is ready).
"""
from __future__ import annotations

import copy
import threading

_LOCK = threading.Lock()          # guards the maps below
_GEN: dict = {}                   # scope tuple -> int
_CACHE: dict = {}                 # scope tuple -> (generation, value)
_FLIGHT: dict = {}                # scope tuple -> per-scope compute lock
_STATS: dict = {}                 # scope tuple -> {"computes": n, "serves": n}
_MAX_ENTRIES = 256                # tiny app; date-keyed scopes retire naturally


def _gen_for(scope: tuple) -> int:
    """Effective generation = domain root + exact scope (additive)."""
    root = (scope[0],)
    return _GEN.get(root, 0) + _GEN.get(scope, 0)


def bump(*scope) -> None:
    """Invalidate. bump('labor_cost') hits every scope in the domain;
    bump('labor_cost', code) hits one project's scopes via the root+leaf sum
    only when the LEAF matches — so leaf bumps use the exact cached key's
    prefix: we bump the (domain, leaf) pair and every cached key under the
    domain re-derives; date-suffixed keys fold the leaf bump in through
    their prefix match below."""
    scope = tuple(scope)
    with _LOCK:
        _GEN[scope] = _GEN.get(scope, 0) + 1
        # a leaf bump must reach date-suffixed keys: drop cached entries whose
        # key starts with the bumped scope (cheap: cache is small)
        for k in [k for k in _CACHE if k[:len(scope)] == scope]:
            _CACHE.pop(k, None)


def memoize(scope, compute_fn):
    """Serve the cached value while the generation matches; recompute only
    when a write moved it. Returns a DEEP COPY (cache can never be mutated
    by response shaping)."""
    scope = tuple(scope)
    with _LOCK:
        flight = _FLIGHT.get(scope)
        if flight is None:
            flight = _FLIGHT[scope] = threading.Lock()
    with flight:                                  # single-flight per scope
        with _LOCK:
            gen = _gen_for(scope)
            hit = _CACHE.get(scope)
            st = _STATS.setdefault(scope, {"computes": 0, "serves": 0})
            if hit is not None and hit[0] == gen:
                st["serves"] += 1
                return copy.deepcopy(hit[1])
        value = compute_fn()                      # outside _LOCK: db work
        with _LOCK:
            st = _STATS.setdefault(scope, {"computes": 0, "serves": 0})
            st["computes"] += 1
            if len(_CACHE) >= _MAX_ENTRIES:
                _CACHE.pop(next(iter(_CACHE)), None)
            _CACHE[scope] = (gen, value)          # gen CAPTURED PRE-COMPUTE
        return copy.deepcopy(value)


def stats(*scope) -> dict:
    """Test/diagnostic hook: {'computes': n, 'serves': n} for a scope."""
    with _LOCK:
        return dict(_STATS.get(tuple(scope), {"computes": 0, "serves": 0}))


def reset() -> None:
    """Test hook: drop every cache, generation, and stat."""
    with _LOCK:
        _GEN.clear()
        _CACHE.clear()
        _STATS.clear()
