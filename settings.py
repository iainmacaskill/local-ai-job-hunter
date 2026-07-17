"""Runtime configuration for cv-drafter-local.

Just the local-LLM endpoint defaults. Override either via environment variable to
point at a different OpenAI-compatible server (e.g. Ollama on :11434).

Named ``settings`` (not ``config``) by convention; the whole tool is standalone
and has no external checkout on its import path.
"""

from __future__ import annotations

import os

# Local LLM endpoint defaults (override via env to A/B against Ollama on :11434).
LLM_BASE_URL = os.environ.get("CVDRAFTER_LLM_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("CVDRAFTER_LLM_MODEL", "qwen/qwen3.6-27b")
