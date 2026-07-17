"""Sweep Reed for new roles and log them to the tracker (Phase C, C2).

Runs one or more Reed searches, skips roles already tracked and roles that need
clearance Iain will not pursue, fetches each surviving role's full job description,
and inserts it into the tracker as 'Found' — ready to triage, then draft from.

Hard filters that Reed can do itself (salary floor, location/distance, permanent vs
contract) are pushed into the search parameters; this module adds the two filters
the API cannot: de-duplication against what is already tracked, and a clearance
skip. Kept out of the Streamlit layer so the sweep is unit-testable.
"""

from __future__ import annotations

import reed
import tracker_db

# Roles requiring these clearances are skipped (not pursued).
CLEARANCE_TERMS = (
    "dv clearance", "developed vetting", "sc clearance", "sc cleared", "sc-cleared",
    "security clearance", "must hold sc", "nppv", "national security vetting",
)


def _needs_clearance(*texts: str) -> bool:
    blob = " ".join(t or "" for t in texts).lower()
    return any(term in blob for term in CLEARANCE_TERMS)


def sweep(conn, searches: list[dict], *, fetch_jd: bool = True, api_key: str | None = None) -> dict:
    """Run each Reed search in ``searches`` and log new roles to the tracker.

    ``searches`` is a list of keyword-arg dicts for ``reed.search`` (e.g.
    ``{"keywords": "ai delivery manager", "location": "London", "contract": True}``).
    Returns a summary: ``{"added": [...], "skipped_seen": n, "skipped_clearance": n}``.
    """
    tracked = tracker_db.list_roles(conn)
    seen_ids = {r["source_job_id"] for r in tracked if r.get("source_job_id")}
    seen_links = {r["link"] for r in tracked if r.get("link")}

    added: list[dict] = []
    skipped_seen = 0
    skipped_clearance = 0
    handled: set[str] = set()  # dedupe within this run (a role can hit several searches)

    for s in searches:
        for role in reed.search(api_key=api_key, **s):
            if role.job_id in seen_ids or role.job_id in handled or role.link in seen_links:
                skipped_seen += 1
                continue
            handled.add(role.job_id)

            jd = role.description
            if fetch_jd:
                try:
                    jd = reed.job_description(role.job_id, api_key=api_key) or role.description
                except reed.ReedError:
                    jd = role.description  # fall back to the search blurb

            if _needs_clearance(role.title, jd):
                skipped_clearance += 1
                continue

            rid = tracker_db.add_role(
                conn,
                title=role.title,
                company=role.company or None,
                type=role.role_type or None,
                rate=role.salary or None,
                location=role.location or None,
                link=role.link or None,
                jd_text=jd or None,
                source_job_id=role.job_id or None,
                fit_notes=f"Reed sweep: {s.get('keywords', '')}".strip(),
                status="Found",
            )
            added.append({"id": rid, "title": role.title, "company": role.company})

    return {
        "added": added,
        "skipped_seen": skipped_seen,
        "skipped_clearance": skipped_clearance,
    }
