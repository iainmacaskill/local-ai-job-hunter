"""Local LLM client for the offline drafting MVP.

Talks to an OpenAI-compatible local endpoint (LM Studio by default, on :1234)
using the **raw** ``/v1/completions`` endpoint with a hand-built qwen ChatML
prompt. A pre-closed ``<think></think>`` block is prefilled into the assistant
turn, which stops the reasoning-model from burning its whole token budget
thinking (LM Studio ignores the API-level thinking switches — ``/no_think``,
``enable_thinking:false`` and ``response_format`` all leave ``content`` empty).
That prefill turns a 40-70s empty response into a ~9s clean, parseable one.

Dependency-light on purpose: stdlib ``urllib`` only, so it drops into the
project's existing venv without new installs. Model-agnostic via ``model`` /
``base_url`` (qwen family shares the ChatML template, so Ollama qwen works too).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "qwen/qwen3.6-27b"
STOP = "<|im_end|>"


class LocalLLMError(RuntimeError):
    """Raised when the endpoint is unreachable or returns unusable output."""


@dataclass
class LocalLLM:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: int = 180
    temperature: float = 0.0
    # JSON-reliability counters, reported by the eval when comparing models.
    stats: dict = field(
        default_factory=lambda: {"json_calls": 0, "json_retries": 0, "json_failures": 0}
    )

    # -- connectivity ------------------------------------------------------ #
    def is_up(self, connect_timeout: float = 1.5) -> bool:
        """True if something is listening on the endpoint's host/port."""
        parsed = urlparse(self.base_url)
        host, port = parsed.hostname or "localhost", parsed.port or 80
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                return True
        except OSError:
            return False

    def list_models(self, connect_timeout: float = 2.0) -> list[str]:
        """Model ids the endpoint currently offers (empty list on any failure).

        LM Studio lists every downloaded model here and loads the requested one
        on demand, so "offered" is the honest word rather than "loaded".
        """
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            with urllib.request.urlopen(req, timeout=connect_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError):
            return []
        return sorted(str(m.get("id")) for m in body.get("data", []) if m.get("id"))

    # -- prompt build ------------------------------------------------------ #
    @staticmethod
    def build_prompt(system: str, user: str, prefill: str = "") -> str:
        """qwen ChatML with an assistant turn whose think block is pre-closed.

        ``prefill`` seeds the start of the answer (e.g. ``{`` to force JSON), a
        reliable way to stop a small model wandering into prose on longer tasks.
        """
        return (
            f"<|im_start|>system\n{system.strip()}{STOP}\n"
            f"<|im_start|>user\n{user.strip()}{STOP}\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n{prefill}"
        )

    # -- raw completion ---------------------------------------------------- #
    def complete_text(
        self, system: str, user: str, max_tokens: int = 800, prefill: str = ""
    ) -> str:
        payload = {
            "model": self.model,
            "prompt": self.build_prompt(system, user, prefill),
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stop": [STOP],
        }
        req = urllib.request.Request(
            f"{self.base_url}/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"), strict=False)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise LocalLLMError(f"local endpoint unreachable at {self.base_url}: {exc}") from exc
        return (body["choices"][0].get("text") or "").strip()

    # -- json helper ------------------------------------------------------- #
    def complete_json(
        self, system: str, user: str, max_tokens: int = 900, retries: int = 2
    ) -> dict:
        """Return a parsed JSON object; prefill ``{`` and retry on bad output.

        The assistant turn is seeded with ``{`` so the model must continue a JSON
        object rather than drift into prose. Both the raw text and a ``{``-prepended
        variant are tried, covering models that echo the brace and those that don't.
        """
        self.stats["json_calls"] += 1
        sys_prompt = system
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            if attempt:
                self.stats["json_retries"] += 1
            text = self.complete_text(sys_prompt, user, max_tokens=max_tokens, prefill="{")
            for candidate in (text, "{" + text):
                try:
                    return extract_json(candidate)
                except (ValueError, json.JSONDecodeError) as exc:
                    last_err = exc
            sys_prompt = (
                f"{system}\n\nReturn ONLY a single valid JSON object, no prose, "
                f"no markdown fences."
            )
        self.stats["json_failures"] += 1
        raise LocalLLMError(f"no valid JSON after {retries + 1} attempts: {last_err}")


def extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of a model's text output."""
    s = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in output: {text[:120]!r}")
    obj = json.loads(s[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("parsed JSON is not an object")
    return obj
