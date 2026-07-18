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

# The job-board APIs cannot filter on remote/hybrid working: it lives in the advert
# text. The sweep detects these signals and stamps them into the fit notes so the
# workstyle is visible on the board without opening every advert.
WORKSTYLE_RE = re.compile(
    r"\b(remote|hybrid|work from home|wfh|home[- ]?based)\b", re.IGNORECASE
)


def workstyle_signals(*texts: str) -> list[str]:
    """Distinct remote/hybrid signals found in the given texts, normalised."""
    blob = " ".join(t or "" for t in texts)
    found = {m.lower().replace("-", " ") for m in WORKSTYLE_RE.findall(blob)}
    if "work from home" in found:
        found.discard("work from home")
        found.add("wfh")
    return sorted(found)


# Day-count arithmetic: adverts state the split many ways ("2 days WFO/week",
# "one day per week in the office", "3 days from home", "fully remote"). Office
# days count down from a five-day week.
_NUM = "one|two|three|four|five|[1-5]"
_WORD_TO_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_FULLY_REMOTE_RE = re.compile(
    r"\b(fully remote|100% remote|remote[- ]first|fully home[- ]?based)\b", re.IGNORECASE
)
_OFFICE_DAYS_RE = re.compile(
    rf"\b({_NUM})\s*days?\s*(?:per week|a week|/week|/wk)?\s*"
    rf"(?:wfo|in|at|on)[- ]?\s*(?:the\s+)?(?:office|site|london)?\b",
    re.IGNORECASE,
)
_HOME_DAYS_RE = re.compile(
    rf"\b({_NUM})\s*days?\s*(?:per week|a week|/week|/wk)?\s*"
    rf"(?:from|at)?\s*(?:home|wfh|remote)\b",
    re.IGNORECASE,
)


def _to_n(token: str) -> int:
    return _WORD_TO_N.get(token.lower(), 0) or int(token)


def home_days(*texts: str) -> int | None:
    """Best-effort days per week at home implied by the text; None when unstated.

    Explicit day counts win; a blanket remote signal with no office-day count
    reads as five. "Hybrid" alone stays None: the split is genuinely unknown.
    """
    blob = " ".join(t or "" for t in texts)
    m = _HOME_DAYS_RE.search(blob)
    if m:
        return max(0, min(5, _to_n(m.group(1))))
    m = _OFFICE_DAYS_RE.search(blob)
    if m:
        return max(0, min(5, 5 - _to_n(m.group(1))))
    if _FULLY_REMOTE_RE.search(blob):
        return 5
    signals = set(workstyle_signals(blob))
    if signals & {"remote", "wfh", "home based"}:
        return 5  # a plain remote signal with no stated office days
    return None

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


# --- fuzzy duplicate detection (agency re-posts) ---------------------------- #
# The same vacancy often arrives several times: posted by multiple agencies, or
# with the employer spelled differently ("J.P. Morgan" vs "JPMorganChase"). The
# rule here is deliberately conservative: titles must match exactly after
# normalisation, and companies must match after normalisation (or one be a prefix
# of the other), so distinct roles are never silently merged.

_COMPANY_SUFFIXES = ("ltd", "limited", "plc", "llp", "llc", "inc", "uk")
_MIN_PREFIX_LEN = 5  # avoid merging on very short company stems


def _norm_title(s: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9&+ ]+", " ", (s or "").lower()).split())


def _norm_company(s: str | None) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    changed = True
    while changed:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            if stem.endswith(suffix) and len(stem) > len(suffix):
                stem = stem[: -len(suffix)]
                changed = True
    return stem


def _same_company(a: str | None, b: str | None) -> bool:
    na, nb = _norm_company(a), _norm_company(b)
    if not na or not nb:
        return False  # unknown employers are never merged
    if na == nb:
        return True
    shorter, longer = sorted((na, nb), key=len)
    return len(shorter) >= _MIN_PREFIX_LEN and longer.startswith(shorter)


def is_duplicate(title_a, company_a, title_b, company_b) -> bool:
    """True when two postings look like the same vacancy re-posted."""
    ta, tb = _norm_title(title_a), _norm_title(title_b)
    return bool(ta) and ta == tb and _same_company(company_a, company_b)


def dedupe_board(conn) -> list[dict]:
    """Archive fuzzy duplicates already on the board; keep the earliest of each.

    Reversible by design: duplicates are archived (Archive panel restores them),
    never deleted. Returns the archived roles as ``[{"id", "title", "company"}]``.
    """
    active = sorted(tracker_db.list_roles(conn), key=lambda r: r["id"])  # oldest first
    keepers: list[dict] = []
    archived: list[dict] = []
    for role in active:
        dup_of = next(
            (k for k in keepers
             if is_duplicate(role["title"], role.get("company"),
                             k["title"], k.get("company"))),
            None,
        )
        if dup_of is None:
            keepers.append(role)
        else:
            archived.append({"id": role["id"], "title": role["title"],
                             "company": role.get("company")})
    tracker_db.archive_roles(conn, [r["id"] for r in archived])
    return archived


def _title_relevant(title: str, terms) -> bool:
    low = (title or "").lower()
    for t in terms:
        if len(t) <= 4:  # acronym/short term: whole-word match only
            if re.search(rf"\b{re.escape(t)}\b", low):
                return True
        elif t in low:
            return True
    return False


def saved_to_searches(saved: dict) -> list[dict]:
    """Turn a saved-search row into the search dicts ``sweep`` expects.

    Both keywords and locations are one-per-line: the sweep runs every keyword in
    every location (e.g. the London hybrid market plus the area round home), and
    its de-duplication collapses any role that appears in more than one.
    """
    keywords = [k.strip() for k in (saved.get("keywords") or "").splitlines() if k.strip()]
    locations = [
        loc.strip() for loc in (saved.get("location") or "").splitlines() if loc.strip()
    ] or [None]
    common = {
        "distance": int(saved.get("distance") or 10),
        "minimum_salary": int(saved.get("min_salary") or 0) or None,
        "contract": True if saved.get("role_type") == "Contract" else None,
        "permanent": True if saved.get("role_type") == "Permanent" else None,
    }
    return [
        {"keywords": kw, "location": loc, **common}
        for kw in keywords for loc in locations
    ]


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
    # Include archived roles: pruning a role from the board must not let the next
    # sweep re-add it.
    tracked = tracker_db.list_roles(conn, include_archived=True)
    seen_ids = {r["source_job_id"] for r in tracked if r.get("source_job_id")}
    seen_links = {r["link"] for r in tracked if r.get("link")}
    # Fuzzy re-post detection: postings already known (tracked or added this run).
    seen_postings = [(r["title"], r.get("company")) for r in tracked]
    source_name = getattr(source, "__name__", "job").split(".")[-1].title()

    added: list[dict] = []
    skipped_seen = 0
    skipped_clearance = 0
    skipped_irrelevant = 0
    skipped_duplicate = 0
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

            if any(is_duplicate(role.title, role.company, t, c) for t, c in seen_postings):
                skipped_duplicate += 1
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

            signals = workstyle_signals(role.title, jd)
            days = home_days(role.title, jd)
            tag = "/".join(signals)
            if days is not None:
                tag = f"{tag}, {days}d home" if tag else f"{days}d home"
            style = f" | {tag}" if tag else ""
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
                fit_notes=f"{source_name} sweep: {s.get('keywords', '')}{style}".strip(),
                status="Found",
            )
            added.append({"id": rid, "title": role.title, "company": role.company})
            seen_postings.append((role.title, role.company))

    return {
        "added": added,
        "skipped_seen": skipped_seen,
        "skipped_clearance": skipped_clearance,
        "skipped_irrelevant": skipped_irrelevant,
        "skipped_duplicate": skipped_duplicate,
    }


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import importlib

    import settings

    settings.load_env()  # pick up REED_API_KEY / ADZUNA_APP_ID+KEY from a .env
    ap = argparse.ArgumentParser(description="Sweep a job board into the local tracker.")
    ap.add_argument("--source", choices=["adzuna", "reed"], default="adzuna")
    ap.add_argument("--dedupe-board", action="store_true",
                    help="archive fuzzy duplicate re-posts already on the board, then exit")
    ap.add_argument("--keywords", action="append",
                    help="search term; repeat for several (e.g. --keywords a --keywords b)")
    ap.add_argument("--location", action="append", default=None,
                    help="search area; repeat for several (e.g. --location London "
                         "--location 'PO17 5LG')")
    ap.add_argument("--distance", type=int, default=10, help="miles from each --location")
    ap.add_argument("--min-salary", type=int, default=None)
    ap.add_argument("--contract", action="store_true", help="contract roles only")
    ap.add_argument("--permanent", action="store_true", help="permanent roles only")
    ap.add_argument("--all-titles", action="store_true",
                    help="keep every result (skip the title-relevance filter)")
    ap.add_argument("--save", metavar="NAME",
                    help="store these criteria as a named saved search, then exit")
    ap.add_argument("--saved", metavar="NAME", help="run the named saved search")
    ap.add_argument("--list-saved", action="store_true", help="list saved searches, then exit")
    args = ap.parse_args(argv)

    conn = tracker_db.connect()
    tracker_db.init_db(conn)

    if args.dedupe_board:
        archived = dedupe_board(conn)
        print(f"archived:  {len(archived)} duplicate re-post(s) (restore from the Archive panel)")
        for r in archived:
            print(f"  - {r['title']}, {r['company']}")
        return 0

    if args.list_saved:
        rows = tracker_db.list_searches(conn)
        if not rows:
            print("no saved searches yet (store one with --save NAME)")
        for s in rows:
            terms = ", ".join((s["keywords"] or "").splitlines())
            print(f"  {s['name']}: {s['source']} | {terms} | {s['location'] or 'anywhere'}"
                  f" | last run {s['last_run_at'] or 'never'}")
        return 0

    role_type = "Contract" if args.contract else "Permanent" if args.permanent else None
    if args.save:
        if not args.keywords:
            ap.error("--save needs --keywords")
        tracker_db.save_search(
            conn, args.save, keywords="\n".join(args.keywords), source=args.source.title(),
            location="\n".join(args.location) if args.location else None,
            distance=args.distance,
            min_salary=args.min_salary, role_type=role_type,
        )
        print(f"saved search '{args.save}' (run it with --saved '{args.save}')")
        return 0

    if args.saved:
        saved = tracker_db.get_search(conn, args.saved)
        if not saved:
            print(f"error: no saved search called '{args.saved}' (see --list-saved)")
            return 1
        source = importlib.import_module(saved["source"].lower())
        searches = saved_to_searches(saved)
        saved_id = saved["id"]
    else:
        if not args.keywords:
            ap.error("--keywords is required (or use --saved / --list-saved / --dedupe-board)")
        source = importlib.import_module(args.source)  # reed or adzuna
        common = {
            "distance": args.distance,
            "minimum_salary": args.min_salary,
            "contract": args.contract or None,
            "permanent": args.permanent or None,
        }
        locations = args.location or [None]
        searches = [
            {"keywords": kw, "location": loc, **common}
            for kw in args.keywords for loc in locations
        ]
        saved_id = None
    title_terms = None if args.all_titles else RELEVANT_TITLE_TERMS
    try:
        summary = sweep(conn, searches, source=source, title_terms=title_terms)
    except RuntimeError as exc:  # missing/rejected key, API down (ReedError/AdzunaError)
        print(f"error: {exc}")
        return 1
    if saved_id:
        tracker_db.mark_search_run(conn, saved_id)
    print(f"added:     {len(summary['added'])} new role(s)")
    for role in summary["added"]:
        print(f"  + {role['title']}, {role['company']}")
    print(f"skipped:   {summary['skipped_seen']} already tracked, "
          f"{summary['skipped_duplicate']} duplicate re-posts, "
          f"{summary['skipped_irrelevant']} off-target titles, "
          f"{summary['skipped_clearance']} needing clearance")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
