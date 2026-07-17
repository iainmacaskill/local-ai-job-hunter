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


def test_draft_cv_only_stamps_row_and_settles(tmp_path):
    conn, role = _queued_role(tmp_path, "Draft CV")
    out = tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                       render_pdf=False)
    assert out["cover"] is None
    saved = tracker_db.get_role(conn, role["id"])
    assert saved["status"] == "CV Drafted"
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
    assert saved["status"] == "CV Drafted"
    assert saved["cover_file"] and saved["cover_file"].endswith(".docx")


def test_queue_and_settle_statuses_are_valid_pipeline_statuses():
    """The queue triggers and the settle target must be real pipeline statuses,
    or the tracker would offer a status the drafter can never clear."""
    for s in tracker_draft.CV_QUEUE_STATUSES:
        assert s in tracker_db.STATUSES
    assert "CV Drafted" in tracker_db.STATUSES


def test_draft_without_jd_raises(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    rid = tracker_db.add_role(conn, title="No JD")
    tracker_db.update_role(conn, rid, status="Draft CV")
    role = tracker_db.get_role(conn, rid)
    with pytest.raises(ValueError):
        tracker_draft.draft_for_role(conn, role, llm=FakeLLM(), out_dir=tmp_path,
                                     render_pdf=False)
