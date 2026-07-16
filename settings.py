"""Reuse bridge + config for cv-drafter-local.

This project reuses jobtracker's rendering/scoring engine **by import** rather than
duplicating it. This module resolves the jobtracker checkout and puts it on
``sys.path`` so ``import screening_cv`` / ``interview_cv`` / ``cover_letter`` work.

It is deliberately named ``settings`` (not ``config``) to avoid shadowing
jobtracker's own ``config`` module once its directory is on the path — and it is
*appended* to ``sys.path`` so this project's own modules always win a name clash.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

JOBTRACKER_PATH = Path(
    os.environ.get("JOBTRACKER_PATH", Path(__file__).resolve().parent.parent / "jobtracker")
).resolve()

# Local LLM endpoint defaults (override via env to A/B against Ollama on :11434).
LLM_BASE_URL = os.environ.get("CVDRAFTER_LLM_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("CVDRAFTER_LLM_MODEL", "qwen/qwen3.6-27b")


def wire_jobtracker() -> Path:
    """Append the jobtracker checkout to ``sys.path`` (idempotent).

    Returns its path. Raises ``FileNotFoundError`` if it isn't where we expect,
    so a misconfigured reuse fails loudly rather than with a confusing ImportError.
    """
    if not JOBTRACKER_PATH.is_dir():
        raise FileNotFoundError(
            f"jobtracker checkout not found at {JOBTRACKER_PATH} "
            f"(set JOBTRACKER_PATH to point at it)"
        )
    p = str(JOBTRACKER_PATH)
    if p not in sys.path:
        sys.path.append(p)
    return JOBTRACKER_PATH
