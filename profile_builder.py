"""Build/extend profile.json from source CVs and a short interview (Source CV tab).

Two ways in, same honesty rule as drafting (draft_cv.py): the model only ever
surfaces facts already present in what the user gave it. It never invents an
employer, date, metric or skill.

  1. extract_profile(): reads the combined text of every uploaded source CV and
     proposes a profile.json-shaped draft. Only facts literally stated in the
     source text are extracted.
  2. gap_questions(): looks at the CURRENT profile.json, finds thin spots (a
     role with under two bullets, no achievements, missing certifications) and
     asks short, specific questions to fill them. The user's own typed answers
     become new bullets/achievements on save — never model-invented.
  3. merge_profile(): folds a new draft into the existing profile
     non-destructively. Nothing already saved is ever dropped; only new jobs
     and new bullets are added (deduped by normalised text).
"""

from __future__ import annotations

STYLE = (
    "Write in British English. Do not use em dashes (use commas, colons or "
    "parentheses instead)."
)

_PROFILE_SCHEMA_HINT = (
    '{"name": string, "contact": string, "competencies": array of short phrases, '
    '"achievements": array of strings, "certifications": string, "education": string, '
    '"jobs": array of {"title": string, "company": string, "dates": string, '
    '"bullets": array of strings}}'
)


def extract_profile(source_text: str, llm) -> dict:
    """Propose a profile.json-shaped draft from raw source-CV text.

    Absolute rule, same as the drafter: only extract what the text literally
    says. If a field is not stated anywhere in the source, leave it empty
    rather than guessing.
    """
    if not source_text.strip():
        return {}
    out = llm.complete_json(
        system=(
            "You extract career facts from CVs/LinkedIn exports into structured JSON. "
            "Use ONLY facts literally present in the source text: never invent an "
            "employer, job title, date, metric or skill that is not there. If several "
            "sources describe the same role slightly differently, combine them and keep "
            "the richest true detail (the most specific numbers/achievements stated), "
            "but do not merge two genuinely different roles into one. "
            f'Return JSON: {_PROFILE_SCHEMA_HINT}. {STYLE}'
        ),
        user=f"SOURCE TEXT (one or more CVs, most recent role usually first):\n{source_text}",
        max_tokens=2500,
    )
    jobs = []
    for j in out.get("jobs", []) or []:
        bullets = [str(b).strip() for b in (j.get("bullets") or []) if str(b).strip()]
        if j.get("title") and bullets:
            jobs.append({
                "title": str(j.get("title", "")).strip(),
                "company": str(j.get("company", "")).strip(),
                "dates": str(j.get("dates", "")).strip(),
                "bullets": bullets,
            })
    return {
        "name": str(out.get("name", "")).strip(),
        "contact": str(out.get("contact", "")).strip(),
        "competencies": [str(c).strip() for c in out.get("competencies", []) if str(c).strip()],
        "achievements": [str(a).strip() for a in out.get("achievements", []) if str(a).strip()],
        "certifications": str(out.get("certifications", "")).strip(),
        "education": str(out.get("education", "")).strip(),
        "jobs": jobs,
    }


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def merge_profile(existing: dict, incoming: dict) -> dict:
    """Fold ``incoming`` into ``existing`` non-destructively.

    Existing jobs are matched to incoming ones by (title, company); new bullets
    the existing job does not already have are appended. Jobs in incoming with
    no match are added as new roles. Scalar fields (name/contact/certifications/
    education) keep the existing value if set, else take the incoming one.
    List fields (competencies/achievements) are unioned, case-insensitively
    deduped, existing order preserved.
    """
    merged = dict(existing) if existing else {}

    for field in ("name", "contact", "certifications", "education"):
        if not (merged.get(field) or "").strip() and incoming.get(field):
            merged[field] = incoming[field]

    for field in ("competencies", "achievements"):
        seen = {_norm(x) for x in merged.get(field, [])}
        combined = list(merged.get(field, []))
        for item in incoming.get(field, []):
            if _norm(item) not in seen:
                combined.append(item)
                seen.add(_norm(item))
        merged[field] = combined

    existing_jobs = list(merged.get("jobs", []))
    job_index = {(_norm(j.get("title")), _norm(j.get("company"))): j for j in existing_jobs}
    for inc_job in incoming.get("jobs", []):
        key = (_norm(inc_job.get("title")), _norm(inc_job.get("company")))
        match = job_index.get(key)
        if match is None:
            existing_jobs.append(dict(inc_job))
            job_index[key] = existing_jobs[-1]
            continue
        seen_bullets = {_norm(b) for b in match.get("bullets", [])}
        for b in inc_job.get("bullets", []):
            if _norm(b) not in seen_bullets:
                match.setdefault("bullets", []).append(b)
                seen_bullets.add(_norm(b))
        if not (match.get("dates") or "").strip() and inc_job.get("dates"):
            match["dates"] = inc_job["dates"]
    merged["jobs"] = existing_jobs
    return merged


def gap_questions(profile: dict, llm, max_questions: int = 6) -> list[dict]:
    """Short, specific questions targeting the thinnest parts of ``profile``.

    Each item is {"question": str, "target": "achievements" | job index (int)}.
    Answers are the user's own words; nothing here is model-generated content
    for the CV itself, only the prompts asking for it.
    """
    gaps = []
    for i, job in enumerate(profile.get("jobs", [])):
        n = len(job.get("bullets", []))
        if n < 2:
            gaps.append(f"[job {i}] {job.get('title')} at {job.get('company')}: "
                        f"only {n} bullet(s) recorded")
    if len(profile.get("achievements", [])) < 2:
        gaps.append("[achievements] fewer than 2 standout achievements recorded")
    if not (profile.get("certifications") or "").strip():
        gaps.append("[certifications] none recorded")
    if not gaps:
        return []

    out = llm.complete_json(
        system=(
            "You are conducting a short interview to help someone build up their CV "
            "content. For each gap listed, write ONE short, specific, easy-to-answer "
            "question (a sentence someone could answer off the top of their head), "
            "e.g. asking for team size, budget, a metric, or a concrete outcome. "
            'Return JSON: {"questions": array of {"gap": the gap label as given, '
            '"question": string}}. ' + STYLE
        ),
        user="GAPS:\n" + "\n".join(gaps[:max_questions]),
        max_tokens=800,
    )
    result = []
    for q in out.get("questions", []) or []:
        gap_label = str(q.get("gap", ""))
        question = str(q.get("question", "")).strip()
        if not question:
            continue
        if gap_label.startswith("[job "):
            try:
                idx = int(gap_label.split("[job ")[1].split("]")[0])
                result.append({"question": question, "target": idx})
                continue
            except (ValueError, IndexError):
                pass
        result.append({"question": question, "target": "achievements"})
    return result
