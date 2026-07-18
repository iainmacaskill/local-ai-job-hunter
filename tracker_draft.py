"""Draft the queued document(s) for a tracked role (Phase B, story B4).

This is the seam that connects the tracker to the Phase A drafting engine: it reads
a role's saved job description, runs the drafters, records the outcome (filename,
coverage) back onto the role and settles it to 'CV Drafted'. Kept out of the
Streamlit layer so the integration is unit-testable with a fake model.
"""

from __future__ import annotations

from pathlib import Path

import draft_cover
import draft_cv
import tracker_db
from cv_profile import OUTPUT_DIR

# Statuses the tracker uses as a "please draft this" trigger.
CV_QUEUE_STATUSES = tracker_db.DRAFT_STATUSES

# Below this length a stored job description is almost certainly a search-result
# snippet (Adzuna returns ~300 characters), not the full advert. Drafting against
# a snippet produces a thin CV and a misleadingly rosy coverage score.
SNIPPET_MIN_CHARS = 600


def looks_like_snippet(jd_text: str | None) -> bool:
    """True when the stored JD is too short to be a full advert."""
    return 0 < len((jd_text or "").strip()) < SNIPPET_MIN_CHARS


def interview_pdf_path(role: dict, out_dir=None) -> Path | None:
    """The designed PDF that pairs with a role's drafted screening CV, if any."""
    cv_file = role.get("cv_file")
    if not cv_file:
        return None
    pdf_name = cv_file.replace(" - Screening - ", " - Interview - ")
    pdf_name = pdf_name.rsplit(".", 1)[0] + ".pdf"
    path = Path(out_dir) if out_dir else OUTPUT_DIR
    return path / pdf_name


def draft_for_role(conn, role: dict, llm=None, out_dir=None, render_pdf: bool = True,
                   guidance: str | None = None) -> dict:
    """Draft the queued document(s) for ``role`` and stamp the results back.

    Reads ``role['jd_text']``, drafts the screening CV (and a designed PDF), plus a
    cover letter when the role's status is 'Draft CV & Cover Letter'. Records
    ``cv_file`` / ``cover_file`` / ``coverage`` on the role; the status is left as the
    draft trigger (the filled-in CV file is what drops it out of the "to draft" queue,
    and you move it to 'Applied' yourself). Returns ``{"cv": <draft_cv result>,
    "cover": <draft_cover result or None>}``. Raises ``ValueError`` if no job
    description is saved.
    """
    jd = (role.get("jd_text") or "").strip()
    if not jd:
        raise ValueError("no job description saved for this role")

    cover = role.get("status") == "Draft CV & Cover Letter"
    title = role.get("title")

    cv = draft_cv.draft_screening_cv(jd, role_title=title, llm=llm, out_dir=out_dir,
                                     render_pdf=render_pdf, guidance=guidance,
                                     company=role.get("company"))
    fields = {
        "cv_file": cv["docx"].name,
        "coverage": cv["coverage"]["pct"],
    }
    cover_res = None
    if cover:
        cover_res = draft_cover.draft_cover_letter(
            jd, role_title=title, company=role.get("company"), llm=llm, out_dir=out_dir,
            guidance=guidance,
        )
        fields["cover_file"] = cover_res["docx"].name

    tracker_db.update_role(conn, int(role["id"]), **fields)
    return {"cv": cv, "cover": cover_res}
