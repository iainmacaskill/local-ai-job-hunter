import json

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


def test_json_stats_count_calls_retries_and_failures(monkeypatch):
    llm = LocalLLM()
    outputs = iter(["not json at all", '{"ok": 1}'])
    monkeypatch.setattr(llm, "complete_text", lambda *a, **k: next(outputs))
    assert llm.complete_json("s", "u", retries=2) == {"ok": 1}
    assert llm.stats == {"json_calls": 1, "json_retries": 1, "json_failures": 0}

    monkeypatch.setattr(llm, "complete_text", lambda *a, **k: "never json")
    with pytest.raises(local_llm.LocalLLMError):
        llm.complete_json("s", "u", retries=1)
    assert llm.stats == {"json_calls": 2, "json_retries": 2, "json_failures": 1}


def test_stats_are_per_instance():
    a, b = LocalLLM(), LocalLLM()
    a.stats["json_calls"] = 5
    assert b.stats["json_calls"] == 0    # no shared mutable default


def test_http_error_surfaces_the_endpoint_body(monkeypatch):
    """A 400 means the endpoint answered: show its reason, never say 'unreachable'."""
    import io
    import urllib.error

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            "http://x", 400, "Bad Request", None,
            io.BytesIO(b'{"error":"insufficient system resources"}'),
        )

    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(local_llm.LocalLLMError) as err:
        LocalLLM().complete_text("s", "u")
    msg = str(err.value)
    assert "HTTP 400" in msg and "insufficient system resources" in msg
    assert "unreachable" not in msg


def test_list_models_empty_on_dead_endpoint():
    assert LocalLLM(base_url="http://127.0.0.1:9").list_models(connect_timeout=0.3) == []


def test_list_models_parses_and_sorts_ids(monkeypatch):
    class FakeResp:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    payload = {"data": [{"id": "qwen/qwen3.6-27b"}, {"id": "qwen/qwen3.5-8b"}, {"x": 1}]}
    monkeypatch.setattr(local_llm.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(payload))
    assert LocalLLM().list_models() == ["qwen/qwen3.5-8b", "qwen/qwen3.6-27b"]


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
