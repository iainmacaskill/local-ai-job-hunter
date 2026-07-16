import pytest

import local_llm
from local_llm import LocalLLM, extract_json


def test_build_prompt_has_chatml_and_closed_think_block():
    p = LocalLLM.build_prompt("SYS", "USER")
    assert "<|im_start|>system\nSYS" in p
    assert "<|im_start|>user\nUSER" in p
    # the pre-closed think block is what defeats the reasoning loop
    assert p.rstrip().endswith("<think>\n\n</think>")
    assert "<|im_start|>assistant" in p


def test_extract_json_plain():
    assert extract_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_extract_json_strips_fences_and_prose():
    noisy = 'Sure! Here you go:\n```json\n{"title": "PM", "n": 4}\n```\nHope that helps.'
    assert extract_json(noisy) == {"title": "PM", "n": 4}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


def test_extract_json_rejects_non_object():
    with pytest.raises(ValueError):
        extract_json("[1, 2, 3]")


def test_is_up_false_on_dead_port():
    # nothing should be listening here
    assert LocalLLM(base_url="http://127.0.0.1:9").is_up(connect_timeout=0.3) is False


# --- live integration: skips unless a local endpoint is actually running --- #
def test_complete_json_live_returns_payload():
    llm = LocalLLM()
    if not llm.is_up():
        pytest.skip(f"no local LLM endpoint at {local_llm.DEFAULT_BASE_URL}")
    out = llm.complete_json(
        system=("You write ATS CV content using ONLY facts given. Output a JSON object with "
                "keys target_title (string) and core_skills (array of 3 strings). JSON only."),
        user=("JOB: Data Delivery Manager. CANDIDATE FACTS: led NHS AI programme; PRINCE2/PMP/CSM; "
              "Oracle to Salesforce migration."),
        max_tokens=400,
    )
    assert isinstance(out, dict)
    assert out.get("target_title")
    assert isinstance(out.get("core_skills"), list) and len(out["core_skills"]) >= 1
