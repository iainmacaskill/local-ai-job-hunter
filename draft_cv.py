"""S2: draft a screening CV from a job description using the local model.

Pipeline (each step is a small, focused local-model call so a 27B model stays
reliable):

  1. extract the must-have keywords from the JD          -> for coverage scoring
  2. write target_title + summary + core_skills          -> grounded in profile facts
  3. rewrite each substantive role's bullets to mirror    -> facts-bounded, per role
     the JD's language
  4. assemble the screening payload with STRUCTURE taken   -> titles/companies/dates
     straight from profile.json                              never touched by the model
  5. render .docx via cv_render and a designed .pdf via pdf_render;
     score coverage

Honesty is architectural: the model only produces prose. Every employer, role
title and date comes from profile.json, and one-line roles are passed through
unchanged rather than inflated. The S3 guard adds verification on top of this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv_render
import honesty
import pdf_render
import settings
from cv_profile import OUTPUT_DIR, load_profile
from local_llm import LocalLLM

STYLE = (
    "Write in British English. Do not use em dashes (use commas, colons or "
    "parentheses instead). Do not invent skills, tools, employers, metrics or "
    "claims that are not in the facts provided."
)


def _facts_block(profile: dict) -> str:
    """A compact, factual grounding block for the header prompt."""
    comps = ", ".join(profile.get("competencies", [])[:16])
    roles = "; ".join(
        f"{j.get('title')} at {j.get('company')} ({j.get('dates')})"
        for j in profile.get("jobs", [])
    )
    return (
        f"Competencies: {comps}\n"
        f"Roles: {roles}\n"
        f"Certifications: {profile.get('certifications', '')}\n"
        f"Education: {profile.get('education', '')}"
    )


def extract_keywords(jd_text: str, llm) -> list[str]:
    out = llm.complete_json(
        system=(
            "Extract the 12 to 18 most important must-have skills, tools, methods and "
            'domain terms from this job advert. Return JSON: {"keywords": [strings]}. '
            "Use the advert's own wording and short forms exactly as they appear (for "
            "example 'AI' if it says AI, not 'Artificial Intelligence'). Terms only, no "
            "duplicates, no sentences."
        ),
        user=jd_text,
        max_tokens=400,
    )
    return [str(k).strip() for k in out.get("keywords", []) if str(k).strip()]


def _guidance_line(guidance: str | None) -> str:
    """User feedback folded into a prompt; it may steer emphasis, never facts."""
    if not (guidance or "").strip():
        return ""
    return (
        f"USER FEEDBACK on the previous draft, to apply where it does not conflict "
        f"with the candidate facts (facts always win): {guidance.strip()}\n\n"
    )


def write_head(
    jd_text: str, profile: dict, role_title: str | None, llm,
    keywords: list[str] | None = None, guidance: str | None = None,
) -> dict:
    kw_line = (
        f"Where the candidate genuinely matches, use these exact advert terms in the "
        f"summary and core_skills: {', '.join(keywords)}. Never claim any the candidate "
        f"lacks.\n\n"
        if keywords
        else ""
    )
    out = llm.complete_json(
        system=(
            "You write the header of an ATS CV using ONLY the candidate facts given. "
            'Return JSON: {"target_title": string, "summary": string of 2 to 3 sentences, '
            '"core_skills": array of 8 to 10 short phrases}. Mirror the job advert wording '
            f"where the candidate genuinely matches. {STYLE}"
        ),
        user=(
            f"JOB ADVERT:\n{jd_text}\n\n"
            f"{kw_line}"
            f"{_guidance_line(guidance)}"
            f"CANDIDATE FACTS:\n{_facts_block(profile)}\n\n"
            f"Target title to aim for: {role_title or '(use the advert job title)'}"
        ),
        max_tokens=600,
    )
    return {
        "target_title": (out.get("target_title") or role_title or "").strip(),
        "summary": (out.get("summary") or "").strip(),
        "core_skills": [str(s).strip() for s in out.get("core_skills", []) if str(s).strip()],
    }


def rewrite_bullets(
    jd_text: str, job: dict, llm, keywords: list[str] | None = None,
    guidance: str | None = None,
) -> dict:
    """Rewrite one role's bullets to mirror the JD, using only that role's facts.

    Returns {"intro": str, "bullets": list[str]}. ``intro`` is a one-sentence
    line rendered between the role's title/dates and its bullets; it is only
    ever generated when ``guidance`` is given (e.g. "add an intro sentence to
    each role"), so a plain draft's format never changes unasked. When no
    intro is warranted the model returns an empty string, which the renderers
    treat as "no intro line" rather than a blank paragraph.
    """
    existing = [b for b in job.get("bullets", []) if str(b).strip()]
    if len(existing) < 2:
        return {"intro": "", "bullets": existing}  # one-line roles passed through
    kw_line = (
        f"Mirror these advert terms where the bullet genuinely supports them: "
        f"{', '.join(keywords[:12])}.\n"
        if keywords
        else ""
    )
    intro_instruction = (
        'Also set "intro" to one short sentence introducing the role (only if the '
        "user's guidance below asks for this format; leave it as an empty string "
        "otherwise). "
        if guidance
        else 'Set "intro" to an empty string. '
    )
    out = llm.complete_json(
        system=(
            "Rewrite this single role's bullet points to mirror the job advert's "
            "language, using ONLY facts already present in the given bullets. Do not add "
            "employers, tools, metrics or claims that are not there. "
            f"{intro_instruction}"
            'Return JSON: {"intro": string, "bullets": array of 2 to 3 strings}. ' + STYLE
        ),
        user=(
            f"JOB ADVERT (for language to mirror):\n{jd_text[:1200]}\n\n"
            f"{kw_line}"
            f"{_guidance_line(guidance)}"
            f"ROLE: {job.get('title')} at {job.get('company')} ({job.get('dates')})\n"
            f"EXISTING BULLETS:\n- " + "\n- ".join(existing)
        ),
        max_tokens=550,
    )
    new = [str(b).strip() for b in out.get("bullets", []) if str(b).strip()]
    return {
        "intro": str(out.get("intro") or "").strip(),
        "bullets": new or existing,  # never drop a role's content on a bad response
    }


def build_payload(
    jd_text: str, profile: dict, role_title: str | None, llm,
    keywords: list[str] | None = None, guidance: str | None = None,
) -> dict:
    head = write_head(jd_text, profile, role_title, llm, keywords, guidance)
    experience = [
        {
            "title": job.get("title"),
            "company": job.get("company"),
            "dates": job.get("dates"),
            **rewrite_bullets(jd_text, job, llm, keywords, guidance),
        }
        for job in profile.get("jobs", [])
    ]
    return {
        "target_title": head["target_title"],
        "summary": head["summary"],
        "core_skills": head["core_skills"],
        "experience": experience,
    }


def _render_pdf(
    payload: dict, role: dict, profile: dict, out_dir: Path
) -> tuple[Path | None, str | None]:
    """Render the designed interview PDF from the same payload; never raises.

    The PDF is a bonus (needs headless Chrome), so a missing browser or a render
    failure returns ``(None, reason)`` rather than sinking the whole draft. out_dir
    is resolved to an absolute path because the renderer builds a file:// URI.
    """
    try:
        pdf = pdf_render.generate_interview_cv(
            role, payload, profile, out_dir=out_dir.resolve()
        )
        return pdf, None
    except Exception as exc:  # noqa: BLE001 - PDF is optional; degrade gracefully
        return None, str(exc)


def draft_screening_cv(
    jd_text: str,
    role_title: str | None = None,
    profile: dict | None = None,
    llm=None,
    out_dir: Path | None = None,
    render_pdf: bool = True,
    guidance: str | None = None,
    company: str | None = None,
) -> dict:
    """Draft + render a screening CV (.docx, and a designed .pdf by default).

    ``guidance`` carries the user's feedback on a previous draft; it steers
    emphasis and wording only, never the facts, and the honesty guard verifies
    the result as usual. Returns paths, payload, coverage, keywords and the
    honesty report.
    """
    profile = profile or load_profile()
    llm = llm or LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
    out_dir = Path(out_dir) if out_dir else OUTPUT_DIR

    jd_keywords = extract_keywords(jd_text, llm)
    payload = build_payload(jd_text, profile, role_title, llm, jd_keywords, guidance)
    report = honesty.verify(payload, profile)  # S3: verify before we render
    role = {"title": role_title or payload["target_title"], "company": company}
    docx = cv_render.generate_screening_cv(role, payload, profile, out_dir=out_dir)
    pdf, pdf_error = _render_pdf(payload, role, profile, out_dir) if render_pdf else (None, None)
    coverage = cv_render.keyword_coverage(
        jd_keywords, cv_render.cv_fulltext(payload, profile)
    )
    return {
        "docx": docx,
        "pdf": pdf,
        "pdf_error": pdf_error,
        "payload": payload,
        "jd_keywords": jd_keywords,
        "coverage": coverage,
        "honesty": report,
    }


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft a screening CV from a JD (local model).")
    ap.add_argument("--jd-file", required=True, help="path to a JD text file, or - for stdin")
    ap.add_argument("--title", default=None, help="target role title (optional)")
    args = ap.parse_args(argv)
    jd = sys.stdin.read() if args.jd_file == "-" else Path(args.jd_file).read_text(encoding="utf-8")
    res = draft_screening_cv(jd, role_title=args.title)
    cov, rep = res["coverage"], res["honesty"]
    print(f"saved:    {res['docx']}")
    if res.get("pdf"):
        print(f"          {res['pdf']}")
    elif res.get("pdf_error"):
        print(f"pdf:      skipped ({res['pdf_error']})")
    print(f"coverage: {cov['pct']}%  ({len(cov['covered'])}/{len(res['jd_keywords'])} keywords)")
    if cov["missing"]:
        print(f"gaps:     {', '.join(cov['missing'])}")
    print(f"honesty:  {rep.summary()}")
    for err in rep.errors:
        print(f"  ERROR   {err}")
    for warn in rep.warnings:
        print(f"  review  {warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
