"""Runtime configuration for Local Job Hunter.

Loads a gitignored ``.env`` (if present) and then the local-LLM endpoint defaults.
Override anything via a real environment variable or a line in ``.env`` — for the
local model (``CVDRAFTER_LLM_URL`` / ``CVDRAFTER_LLM_MODEL``) or the job sources
(``REED_API_KEY``, ``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``).

Named ``settings`` (not ``config``) by convention; the whole tool is standalone and
has no external checkout on its import path.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent


def load_env(path: Path | str | None = None) -> None:
    """Populate ``os.environ`` from a simple KEY=VALUE ``.env`` file.

    Real environment variables win (values are only set when absent), so a shell
    ``export`` overrides the file. No dependency on python-dotenv. Blank lines,
    ``#`` comments and surrounding quotes are handled; anything malformed is skipped.
    """
    p = Path(path) if path else REPO / ".env"
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env()  # so config and the job-source clients see .env values

# Local LLM endpoint defaults (override via env to A/B against Ollama on :11434).
LLM_BASE_URL = os.environ.get("CVDRAFTER_LLM_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("CVDRAFTER_LLM_MODEL", "qwen/qwen3.6-27b")
