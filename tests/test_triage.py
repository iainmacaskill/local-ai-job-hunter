"""Cover ranked triage and the snippet heuristic. Offline."""

import tracker_db
import tracker_draft
import triage

PROFILE = {
    "name": "Alex Rivera",
    "competencies": ["Programme Delivery", "Agile", "Stakeholder Management", "AI"],
    "jobs": [{"title": "Programme Manager", "company": "Example Corp"}],
    "certifications": "PRINCE2",
}


def _db(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    return conn


class FakeLLM:
    def __init__(self, score=85, reason="Strong AI programme delivery match."):
        self.out = {"score": score, "reason": reason}

    def complete_json(self, system, user, max_tokens=0):
        return self.out


def test_score_role_uses_llm_and_clamps():
    role = {"title": "AI Delivery Manager", "company": "Acme", "jd_text": "Lead AI delivery."}
    out = triage.score_role(role, PROFILE, FakeLLM(score=85))
    assert out == {"score": 85, "reason": "Strong AI programme delivery match."}
    assert triage.score_role(role, PROFILE, FakeLLM(score=250))["score"] == 100
    assert triage.score_role(role, PROFILE, FakeLLM(score=-5))["score"] == 0


def test_score_role_falls_back_on_bad_or_failing_llm():
    role = {"title": "Agile Delivery Lead", "company": "Acme",
            "jd_text": "Needs Agile and stakeholder management."}
    # Non-numeric score -> keyword fallback.
    out = triage.score_role(role, PROFILE, FakeLLM(score="not a number"))
    assert "Keyword overlap" in out["reason"]

    class DeadLLM:
        def complete_json(self, *a, **k):
            from local_llm import LocalLLMError
            raise LocalLLMError("down")

    out = triage.score_role(role, PROFILE, DeadLLM())
    assert "Keyword overlap" in out["reason"] and 0 <= out["score"] <= 100


def test_keyword_fallback_reflects_overlap():
    hit = {"title": "Agile Programme Delivery", "jd_text": "AI and stakeholder management."}
    miss = {"title": "HGV Mechanic", "jd_text": "Fix lorries."}
    assert triage.keyword_score(hit, PROFILE)["score"] == 100    # all 4 competencies present
    assert triage.keyword_score(miss, PROFILE)["score"] == 0


def test_score_found_scores_only_unscored_found_roles(tmp_path):
    conn = _db(tmp_path)
    new = tracker_db.add_role(conn, title="New", jd_text="AI delivery")
    scored = tracker_db.add_role(conn, title="Scored", jd_text="AI delivery")
    tracker_db.update_role(conn, scored, fit_score=50, fit_reason="old")
    applied = tracker_db.add_role(conn, title="Applied", jd_text="AI delivery")
    tracker_db.update_role(conn, applied, status="Applied")

    results = triage.score_found(conn, PROFILE, FakeLLM(score=90))
    assert [r["id"] for r in results] == [new]
    saved = tracker_db.get_role(conn, new)
    assert saved["fit_score"] == 90 and saved["fit_reason"]
    assert tracker_db.get_role(conn, scored)["fit_score"] == 50   # untouched
    assert tracker_db.get_role(conn, applied)["fit_score"] is None


def test_score_found_rescore_and_limit_and_progress(tmp_path):
    conn = _db(tmp_path)
    for i in range(3):
        rid = tracker_db.add_role(conn, title=f"R{i}", jd_text="AI")
        tracker_db.update_role(conn, rid, fit_score=10, fit_reason="stale")
    ticks = []
    results = triage.score_found(conn, PROFILE, FakeLLM(score=70), rescore=True,
                                 limit=2, progress=lambda i, n: ticks.append((i, n)))
    assert len(results) == 2 and ticks == [(1, 2), (2, 2)]


def test_looks_like_snippet_thresholds():
    assert tracker_draft.looks_like_snippet("Short Adzuna snippet about the role.")
    assert not tracker_draft.looks_like_snippet("")          # empty is not a snippet
    assert not tracker_draft.looks_like_snippet(None)
    assert not tracker_draft.looks_like_snippet("x" * 700)   # full advert length
