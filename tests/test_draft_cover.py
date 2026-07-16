import pytest

import settings

_HAVE_JT = settings.JOBTRACKER_PATH.is_dir()
if _HAVE_JT:
    settings.wire_jobtracker()
    import screening_cv  # noqa: E402

    import draft_cover  # noqa: E402
    from local_llm import LocalLLM  # noqa: E402

pytestmark = pytest.mark.skipif(not _HAVE_JT, reason="jobtracker checkout not present")

CLEAN = [
    "I am writing to apply for the role, drawing on my background in AI programme delivery.",
    "I have led regulated programmes and cross-functional teams through to successful delivery.",
    "I would welcome the opportunity to discuss how I can contribute to your organisation.",
]


class FakeLLM:
    def __init__(self, paragraphs=None):
        self.paragraphs = paragraphs if paragraphs is not None else CLEAN

    def complete_json(self, system, user, max_tokens=0):
        if "paragraphs" in system:
            return {"paragraphs": self.paragraphs}
        return {}


def test_renders_docx_and_txt_and_verifies_clean(tmp_path):
    prof = screening_cv.load_profile()
    res = draft_cover.draft_cover_letter(
        "JD: AI delivery role in financial services.",
        role_title="AI Delivery Manager", company="Acme",
        profile=prof, llm=FakeLLM(), out_dir=tmp_path,
    )
    assert res["docx"].exists() and res["docx"].suffix == ".docx"
    assert res["txt"].exists() and res["txt"].suffix == ".txt"
    assert len(res["paragraphs"]) == 3
    assert res["honesty"].ok and not res["honesty"].warnings


def test_guard_flags_fake_figure_and_em_dash(tmp_path):
    prof = screening_cv.load_profile()
    bad = ["I cut costs by 47% and, importantly — delivered early.", CLEAN[1], CLEAN[2]]
    res = draft_cover.draft_cover_letter(
        "JD", role_title="X", company="Y",
        profile=prof, llm=FakeLLM(bad), out_dir=tmp_path,
    )
    warns = res["honesty"].warnings
    assert any("47%" in w for w in warns)
    assert any("em dash" in w for w in warns)


def test_live_end_to_end_cover(tmp_path):
    if not LocalLLM().is_up():
        pytest.skip("no local LLM endpoint running")
    res = draft_cover.draft_cover_letter(
        "Technical Project Manager (Data & Analytics), financial services, remote. "
        "Must-haves: data delivery, cross-functional teams, Agile, PRINCE2, PMP.",
        role_title="Technical Project Manager (Data & Analytics)", company="HSBC",
        out_dir=tmp_path,
    )
    assert res["docx"].exists() and res["txt"].exists()
    assert 1 <= len(res["paragraphs"]) <= 3
