import pytest

import settings

_HAVE_JT = settings.JOBTRACKER_PATH.is_dir()
if _HAVE_JT:
    settings.wire_jobtracker()
    import screening_cv  # noqa: E402

    import draft_cv  # noqa: E402
    from local_llm import LocalLLM  # noqa: E402

pytestmark = pytest.mark.skipif(not _HAVE_JT, reason="jobtracker checkout not present")

REWRITTEN = ["Rewritten bullet mirroring AI and data delivery.", "Second rewritten bullet."]


class FakeLLM:
    """Routes by the distinctive words in each step's system prompt."""

    def complete_json(self, system, user, max_tokens=0):
        if "Extract the 12" in system:
            return {"keywords": ["AI", "data", "Agile", "PRINCE2", "stakeholder management"]}
        if "target_title" in system:
            return {
                "target_title": "Test Project Manager",
                "summary": "Summary sentence one. Summary sentence two.",
                "core_skills": ["Skill A", "Skill B", "Skill C", "Skill D"],
            }
        if "Rewrite this single role" in system:
            return {"bullets": list(REWRITTEN)}
        return {}


def _draft():
    prof = screening_cv.load_profile()
    import tempfile

    out = tempfile.mkdtemp()
    res = draft_cv.draft_screening_cv(
        "JD: needs AI and data delivery, Agile, PRINCE2, stakeholder management.",
        role_title="Test Project Manager",
        profile=prof,
        llm=FakeLLM(),
        out_dir=out,
    )
    return prof, res


def test_renders_docx_and_scores_coverage():
    _prof, res = _draft()
    assert res["docx"].exists() and res["docx"].suffix == ".docx"
    assert set(res["coverage"]) >= {"pct", "covered", "missing"}
    assert isinstance(res["coverage"]["pct"], int)


def test_experience_structure_comes_from_profile_not_model():
    """The honesty invariant: the model never invents/renames/reorders employers."""
    prof, res = _draft()
    exp = res["payload"]["experience"]
    got = [(e["title"], e["company"], e["dates"]) for e in exp]
    want = [(j["title"], j["company"], j["dates"]) for j in prof["jobs"]]
    assert got == want  # same roles, same order, untouched by the model


def test_one_line_roles_are_passed_through_not_inflated():
    prof, res = _draft()
    for job, e in zip(prof["jobs"], res["payload"]["experience"]):
        real = [b for b in job.get("bullets", []) if str(b).strip()]
        if len(real) < 2:
            assert e["bullets"] == real          # unchanged, never padded
        else:
            assert e["bullets"] == REWRITTEN     # multi-bullet roles get rewritten


def test_extract_keywords_returns_list():
    kws = draft_cv.extract_keywords("some jd", FakeLLM())
    assert "AI" in kws and isinstance(kws, list)


# --- live end-to-end: real local model, skips unless the endpoint is up --- #
def test_live_end_to_end_draft(tmp_path):
    if not LocalLLM().is_up():
        pytest.skip("no local LLM endpoint running")
    res = draft_cv.draft_screening_cv(
        "Technical Project Manager (Data & Analytics), financial services, remote. "
        "Must-haves: data and analytics delivery, cross-functional teams, Agile, PRINCE2, PMP.",
        role_title="Technical Project Manager (Data & Analytics)",
        out_dir=tmp_path,
    )
    assert res["docx"].exists()
    assert 0 <= res["coverage"]["pct"] <= 100
    assert res["payload"]["summary"]
