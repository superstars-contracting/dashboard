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

# #263 — COMPANY axis. The company overview console (`/`) and its company-level tabs
# (Workforce, Cert Health/Library, Bid Tracker, Specs, Settings) + their data endpoints
# are admin/c_suite ONLY. A `pm` is scoped to assigned PROJECTS instead (see pm_scoping)
# and lands on a projects-only view; it never reaches the company console. This is the
# ROLE axis for "company vs project" — independent of the project-ASSIGNMENT axis.
COMPANY_ROLES = frozenset({"admin", "c_suite"})


def can_access_company(role) -> bool:
    """True iff `role` may reach the company overview console + company-level surfaces.
    The single source of truth for both the `/` gate, the @requires_company endpoints,
    and the role-aware back-link in the project sidebar."""
    return role in COMPANY_ROLES


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


# ===================== #263 — role-aware project-sidebar nav =====================
# Named-block markers, same idea as SECTION but with an explicit keep/strip predicate
# (SECTION only ever STRIPS what a role can't see; these pick BETWEEN two variants).
#
#   <!-- BACKLINK_COMPANY:start --> ... <!-- BACKLINK_COMPANY:end -->   (admin/c_suite)
#   <!-- BACKLINK_PROJECTS:start --> ... <!-- BACKLINK_PROJECTS:end --> (pm/super)
#   <!-- COMPANYLINK:start --> ... <!-- COMPANYLINK:end -->            (in-view deep links)
#
# The project dashboard's "← Back to …" link and its in-view "Company Console →" deep
# links must NEVER hand a pm a path to the company console (which 403s for them). So the
# served HTML is rendered per role: keep the company back-link for company roles, the
# projects back-link otherwise, and strip every COMPANYLINK block for non-company roles.

def _named_block_re(name: str):
    return re.compile(
        r"<!--\s*" + re.escape(name) + r":start\s*-->.*?<!--\s*" + re.escape(name) + r":end\s*-->",
        re.DOTALL,
    )


def _strip_named_block(html: str, name: str, keep: bool) -> str:
    """Remove EVERY `name` block if `keep` is False; leave the html untouched if True."""
    if keep:
        return html
    return _named_block_re(name).sub("", html)


def render_role_nav(html: str, role) -> str:
    """Pick the role-correct project-sidebar nav: the company back-link for company roles
    or the projects back-link otherwise, and drop in-view company deep links for non-company
    roles. Idempotent and order-independent; a no-op if the markers are absent."""
    company = can_access_company(role)
    html = _strip_named_block(html, "BACKLINK_COMPANY", keep=company)
    html = _strip_named_block(html, "BACKLINK_PROJECTS", keep=not company)
    html = _strip_named_block(html, "COMPANYLINK", keep=company)
    return html
