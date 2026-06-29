"""#262 — central role-based section access (RBAC). ONE source of truth.

Both the dashboard sidebar (rendered server-side — gated SECTION blocks are stripped
from the served HTML per role) AND the gated API endpoints read `SECTION_ACCESS`, so
access for a section changes in exactly one place. Role-based only — no per-user perms.

Sections NOT listed here default to ALL dashboard roles, so `pm` keeps every
operational section (Compliance, Drop Plan, Field Photos, Look-ahead, ...). Only the
gated sections restrict: **Financial** (Schedule of Values + Labor Rate Tracker, which
carry contract/billing financials) → admin/c_suite only. `super` gets the default
(everything except the gated Financial section).
"""
from __future__ import annotations

import re

DASHBOARD_ROLES = frozenset({"admin", "c_suite", "pm", "super"})

# Gated sections only. The KEY matches the `<!-- SECTION:<key> -->` markers in the
# templates AND the section passed to requires_section() on the endpoints.
SECTION_ACCESS = {
    "financial": frozenset({"admin", "c_suite"}),
}


def roles_for(section: str) -> frozenset:
    """The set of roles allowed in `section` (defaults to all dashboard roles)."""
    return SECTION_ACCESS.get(section, DASHBOARD_ROLES)


def can_access(section: str, role) -> bool:
    return role in roles_for(section)


def can_access_all_gated(role) -> bool:
    """True iff `role` can access EVERY gated section (admin/c_suite). The fast path:
    no per-role sidebar stripping needed when this is True."""
    return all(role in roles for roles in SECTION_ACCESS.values())


def section_visibility(role) -> dict:
    """{gated_section: bool} for the current role — surfaced on /api/auth/me so the
    client can reflect the same decision (the sidebar itself is server-stripped)."""
    return {s: (role in roles_for(s)) for s in SECTION_ACCESS}


# <!-- SECTION:<name>:start --> ... <!-- SECTION:<name>:end --> — server-stripped from
# the served HTML for any role that can't access <name>. The \1 backreference pins each
# end to its own start; DOTALL so a block spans many lines. The SAME marker wraps both a
# sidebar group AND its content pane, so a gated section is fully ABSENT (not merely
# hidden) for a disallowed role — hiding a menu item is not access control.
_SECTION_RE = re.compile(
    r"<!--\s*SECTION:(\w+):start\s*-->.*?<!--\s*SECTION:\1:end\s*-->",
    re.DOTALL,
)


def render_sections(html: str, role) -> str:
    """Return `html` with every SECTION block the role can't access removed."""
    return _SECTION_RE.sub(
        lambda m: m.group(0) if can_access(m.group(1), role) else "", html)
