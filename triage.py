"""Ranked triage: score each Found role against your profile, honestly.

The board can find ninety roles in a sweep; deciding which are worth pursuing is
the biggest remaining time sink. This module asks the local model for a 0-100 fit
score and a one-line reason for each Found role, grounded ONLY in the advert text
and your profile facts, and told to name the genuine gap when the fit is weak. The
board then ranks scored roles to the top, so triage starts from a shortlist.

When the model is offline, a deterministic fallback scores by keyword overlap
(how many of your competencies the advert mentions) and says so, rather than
pretending to a judgement it did not make.

Run a batch from the terminal:  ./.venv/bin/python triage.py [--limit N] [--rescore]
"""

from __future__ import annotations

import cv_render
import tracker_db
from local_llm import LocalLLMError

STYLE = (
    "Write in British English. Do not use em dashes. Be honest: when the fit is "
    "weak, name the genuine gap rather than flattering. Use ONLY the facts provided."
)


def _facts(profile: dict) -> str:
    comps = ", ".join(profile.get("competencies", [])[:16])
    roles = "; ".join(
        f"{j.get('title')} at {j.get('company')}" for j in profile.get("jobs", [])
    )
    return (
        f"Competencies: {comps}\n"
        f"Career: {roles}\n"
        f"Certifications: {profile.get('certifications', '')}"
    )


def keyword_score(role: dict, profile: dict) -> dict:
    """Deterministic fallback: how many profile competencies the advert mentions."""
    text = " ".join([role.get("title") or "", role.get("jd_text") or ""])
    cov = cv_render.keyword_coverage(profile.get("competencies", []), text)
    return {"score": cov["pct"], "reason": "Keyword overlap only (local model offline)."}


def score_role(role: dict, profile: dict, llm=None) -> dict:
    """Score one role 0-100 with a one-line honest reason. Falls back on error."""
    if llm is None:
        return keyword_score(role, profile)
    advert = (
        f"Title: {role.get('title')}\n"
        f"Company: {role.get('company') or '(not stated)'}\n"
        f"Advert text:\n{(role.get('jd_text') or '')[:1500]}"
    )
    try:
        out = llm.complete_json(
            system=(
                "You triage job adverts for this candidate. Rate how well the advert "
                "fits their genuine experience, 0 to 100 (90+ = obvious strong match, "
                "50 = plausible stretch, below 30 = wrong role for them). "
                'Return JSON: {"score": integer, "reason": one short sentence saying '
                "the main reason for or against}. " + STYLE
            ),
            user=f"CANDIDATE FACTS:\n{_facts(profile)}\n\nADVERT:\n{advert}",
            max_tokens=220,
        )
    except LocalLLMError:
        return keyword_score(role, profile)
    try:
        score = max(0, min(100, int(out.get("score"))))
    except (TypeError, ValueError):
        return keyword_score(role, profile)
    reason = str(out.get("reason") or "").strip()
    return {"score": score, "reason": reason}


def score_found(conn, profile: dict, llm=None, limit: int | None = None,
                rescore: bool = False, progress=None) -> list[dict]:
    """Score Found roles that have no fit score yet (all of them with ``rescore``).

    Each result is written to the role as it lands, so an interrupted batch keeps
    its progress. ``progress`` (done, total) is called after each role for UIs.
    """
    todo = [
        r for r in tracker_db.list_roles(conn)
        if r.get("status") == "Found" and (rescore or r.get("fit_score") is None)
    ]
    if limit:
        todo = todo[:limit]
    done: list[dict] = []
    for i, role in enumerate(todo, start=1):
        result = score_role(role, profile, llm)
        tracker_db.update_role(
            conn, role["id"], fit_score=result["score"], fit_reason=result["reason"]
        )
        done.append({"id": role["id"], "title": role["title"],
                     "company": role.get("company"), **result})
        if progress:
            progress(i, len(todo))
    return done


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from cv_profile import load_profile
    from local_llm import LocalLLM

    ap = argparse.ArgumentParser(description="Score Found roles against your profile.")
    ap.add_argument("--limit", type=int, default=None, help="score at most N roles")
    ap.add_argument("--rescore", action="store_true", help="re-score already-scored roles")
    args = ap.parse_args(argv)

    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    profile = load_profile()
    llm = LocalLLM()
    if not llm.is_up():
        print("local model offline: scoring by keyword overlap only")
        llm = None

    results = score_found(
        conn, profile, llm, limit=args.limit, rescore=args.rescore,
        progress=lambda i, n: print(f"  scored {i}/{n}", end="\r"),
    )
    print()
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        print(f"  {r['score']:3}  {r['title']}, {r['company']}")
        if r["reason"]:
            print(f"       {r['reason']}")
    print(f"scored: {len(results)} role(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
