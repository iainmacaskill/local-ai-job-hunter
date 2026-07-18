"""Cover the tracker -> drafter integration (B4): draft a queued role, stamp it."""

import pytest

import tracker_db
import tracker_draft

JD = "AI delivery role. Must-haves: AI, data delivery, Agile, PRINCE2, stakeholder management."


class FakeLLM:
    """Routes by the distinctive words in each drafter's system prompts."""

    def complete_json(self, system, user, max_tokens=0):
        if "Extract the 12" in system:
            return {"keywords": ["AI", "data", "Agile", "PRINCE2", "stakeholder management"]}
        if "target_title" in system:
            return {
                "target_title": "AI Delivery Manager",
                "summary": "Delivery leader with AI and data programme experience.",
                "core_skills": ["AI", "data delivery", "Agile", "PRINCE2"],
            }
        if "Rewrite this single role" in system:
            return {"bullets": ["Led AI and data delivery.", "Ran Agile teams to plan."]}
        if "paragraphs" in system:
            return {"paragraphs": [
                "I am applying for the AI Delivery Manager role.",
                "I have led regulated programmes and cross-functional teams to delivery.",
                "I would welcome the chance to contribute to your organisation.",
            ]}
        return {}


def _queued_role(tmp_path, status):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    rid = tracker_db.add_role(conn, title="AI Delivery Manager", company="Acme", jd_text=JD)
    tracker_db.update_role(conn, rid, status=status)
    return conn, tracker_db.get_role(conn, rid)


def test_draft_cv_only_stamps_the_row(tmp_path):
    conn, role = _queued_role(tmp_path, "Draft CV")
    out = tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                       render_pdf=False)
    assert out["cover"] is None
    saved = tracker_db.get_role(conn, role["id"])
    assert saved["status"] == "Draft CV"      # unchanged; the CV file is what settles it
    assert saved["cv_file"] and saved["cv_file"].endswith(".docx")
    assert isinstance(saved["coverage"], int) and 0 <= saved["coverage"] <= 100
    assert saved["cover_file"] is None
    assert out["cv"]["docx"].exists()


def test_draft_cv_and_cover_stamps_both(tmp_path):
    conn, role = _queued_role(tmp_path, "Draft CV & Cover Letter")
    out = tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                       render_pdf=False)
    assert out["cover"] is not None and out["cover"]["docx"].exists()
    saved = tracker_db.get_role(conn, role["id"])
    assert saved["status"] == "Draft CV & Cover Letter"   # unchanged
    assert saved["cover_file"] and saved["cover_file"].endswith(".docx")


class SpyLLM(FakeLLM):
    """FakeLLM that also records every prompt it is sent."""

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user, max_tokens=0):
        self.prompts.append(user)
        return super().complete_json(system, user, max_tokens)


def test_redraft_guidance_reaches_the_prompts_and_restamps(tmp_path):
    conn, role = _queued_role(tmp_path, "Draft CV")
    spy = SpyLLM()
    out = tracker_draft.draft_for_role(
        conn, role, llm=spy, out_dir=tmp_path, render_pdf=False,
        guidance="Lead with the NHS AI programme.",
    )
    guided = [p for p in spy.prompts if "Lead with the NHS AI programme." in p]
    assert guided, "guidance never reached a prompt"
    assert any("USER FEEDBACK" in p and "facts always win" in p for p in guided)
    saved = tracker_db.get_role(conn, role["id"])
    assert saved["cv_file"] and isinstance(saved["coverage"], int)
    assert out["cv"]["honesty"] is not None       # guard still verifies redrafts


def test_same_title_at_two_companies_never_collides(tmp_path):
    """Two 'Programme Manager' roles at different employers must produce
    different files, or the second draft silently overwrites the first."""
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    files = []
    for company in ("Prism Digital", "Pearson Whiffin"):
        rid = tracker_db.add_role(conn, title="Programme Manager", company=company,
                                  jd_text=JD)
        tracker_db.update_role(conn, rid, status="Draft CV")
        role = tracker_db.get_role(conn, rid)
        out = tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                           render_pdf=False)
        files.append(out["cv"]["docx"].name)
    assert files[0] != files[1]
    assert "Prism Digital" in files[0] and "Pearson Whiffin" in files[1]


def test_interview_pdf_path_derives_from_cv_file(tmp_path):
    role = {"cv_file": "Alex Rivera - Screening - AI Delivery Manager.docx"}
    p = tracker_draft.interview_pdf_path(role, out_dir=tmp_path)
    assert p.name == "Alex Rivera - Interview - AI Delivery Manager.pdf"
    assert p.parent == tmp_path
    assert tracker_draft.interview_pdf_path({"cv_file": None}) is None


def test_queue_statuses_are_valid():
    """The draft-queue triggers must be real statuses, or the tracker would offer a
    status the drafter never acts on."""
    for s in tracker_draft.CV_QUEUE_STATUSES:
        assert s in tracker_db.STATUSES


def test_draft_without_jd_raises(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    rid = tracker_db.add_role(conn, title="No JD")
    tracker_db.update_role(conn, rid, status="Draft CV")
    role = tracker_db.get_role(conn, rid)
    with pytest.raises(ValueError):
        tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                     render_pdf=False)
