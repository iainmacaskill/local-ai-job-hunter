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

import re

import reed
import tracker_db

# Roles requiring these clearances are skipped (not pursued).
CLEARANCE_TERMS = (
    "dv clearance", "developed vetting", "sc clearance", "sc cleared", "sc-cleared",
    "security clearance", "must hold sc", "nppv", "national security vetting",
)

# Relevance filter for Iain's hunt: a board's keyword search (Adzuna especially) is
# loose and returns tangential roles, so keep only those whose TITLE mentions one of
# these delivery/leadership terms. Short/acronym terms match whole words (so "AI"
# does not match "repair"); longer phrases match as substrings. Pass a different set
# (or None) to sweep to widen or disable it.
RELEVANT_TITLE_TERMS = (
    "ai", "data", "digital", "transformation", "programme", "program", "delivery",
    "pmo", "change", "agile", "scrum", "portfolio", "project", "product owner",
    "product manager",
)


def _needs_clearance(*texts: str) -> bool:
    blob = " ".join(t or "" for t in texts).lower()
    return any(term in blob for term in CLEARANCE_TERMS)


def _title_relevant(title: str, terms) -> bool:
    low = (title or "").lower()
    for t in terms:
        if len(t) <= 4:  # acronym/short term: whole-word match only
            if re.search(rf"\b{re.escape(t)}\b", low):
                return True
        elif t in low:
            return True
    return False


def sweep(
    conn, searches: list[dict], *, source=reed, fetch_jd: bool = True, title_terms=None
) -> dict:
    """Run each search in ``searches`` against ``source`` and log new roles.

    ``source`` is a job-source module (``reed`` or ``adzuna``) exposing ``search()``
    and a ``HAS_JD_DETAIL`` flag (and ``job_description()`` when that flag is set).
    ``searches`` is a list of keyword-arg dicts for that source's ``search`` (e.g.
    ``{"keywords": "ai delivery manager", "location": "London", "contract": True}``).
    ``title_terms`` (e.g. ``RELEVANT_TITLE_TERMS``) drops roles whose title matches
    none of them, cutting the noise a loose board search returns; pass None to keep
    all. Credentials come from each source's own environment variables. Returns a
    summary: ``{"added", "skipped_seen", "skipped_clearance", "skipped_irrelevant"}``.
    """
    tracked = tracker_db.list_roles(conn)
    seen_ids = {r["source_job_id"] for r in tracked if r.get("source_job_id")}
    seen_links = {r["link"] for r in tracked if r.get("link")}
    source_name = getattr(source, "__name__", "job").split(".")[-1].title()

    added: list[dict] = []
    skipped_seen = 0
    skipped_clearance = 0
    skipped_irrelevant = 0
    handled: set[str] = set()  # dedupe within this run (a role can hit several searches)

    for s in searches:
        for role in source.search(**s):
            if role.job_id in seen_ids or role.job_id in handled or role.link in seen_links:
                skipped_seen += 1
                continue
            handled.add(role.job_id)

            if title_terms and not _title_relevant(role.title, title_terms):
                skipped_irrelevant += 1
                continue

            jd = role.description
            if fetch_jd and getattr(source, "HAS_JD_DETAIL", False):
                try:
                    jd = source.job_description(role.job_id) or role.description
                except Exception:  # noqa: BLE001 - a JD fetch failure must not sink the sweep
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
                fit_notes=f"{source_name} sweep: {s.get('keywords', '')}".strip(),
                status="Found",
            )
            added.append({"id": rid, "title": role.title, "company": role.company})

    return {
        "added": added,
        "skipped_seen": skipped_seen,
        "skipped_clearance": skipped_clearance,
        "skipped_irrelevant": skipped_irrelevant,
    }


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import importlib

    import settings

    settings.load_env()  # pick up REED_API_KEY / ADZUNA_APP_ID+KEY from a .env
    ap = argparse.ArgumentParser(description="Sweep a job board into the local tracker.")
    ap.add_argument("--source", choices=["reed", "adzuna"], default="reed")
    ap.add_argument("--keywords", required=True, action="append",
                    help="search term; repeat for several (e.g. --keywords a --keywords b)")
    ap.add_argument("--location", default=None)
    ap.add_argument("--distance", type=int, default=10, help="miles from --location")
    ap.add_argument("--min-salary", type=int, default=None)
    ap.add_argument("--contract", action="store_true", help="contract roles only")
    ap.add_argument("--permanent", action="store_true", help="permanent roles only")
    ap.add_argument("--all-titles", action="store_true",
                    help="keep every result (skip the title-relevance filter)")
    args = ap.parse_args(argv)

    source = importlib.import_module(args.source)  # reed or adzuna
    common = {
        "location": args.location,
        "distance": args.distance,
        "minimum_salary": args.min_salary,
        "contract": args.contract or None,
        "permanent": args.permanent or None,
    }
    searches = [{"keywords": kw, **common} for kw in args.keywords]
    title_terms = None if args.all_titles else RELEVANT_TITLE_TERMS

    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    try:
        summary = sweep(conn, searches, source=source, title_terms=title_terms)
    except RuntimeError as exc:  # missing/rejected key, API down (ReedError/AdzunaError)
        print(f"error: {exc}")
        return 1
    print(f"added:     {len(summary['added'])} new role(s)")
    for role in summary["added"]:
        print(f"  + {role['title']}, {role['company']}")
    print(f"skipped:   {summary['skipped_seen']} already tracked, "
          f"{summary['skipped_irrelevant']} off-target titles, "
          f"{summary['skipped_clearance']} needing clearance")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
