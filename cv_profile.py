"""Local profile and output config for the drafter (A1: own the profile).

The candidate's CV facts live in ``profile.json`` in this repo (gitignored).
Copy ``profile.example.json`` to ``profile.json`` and fill it in. Paths are
env-overridable so the tool is portable.

This module has **no dependency on jobtracker** - it is the first piece of
cutting the cord toward a standalone project (roadmap Phase A).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent
PROFILE_PATH = Path(os.environ.get("CVDRAFTER_PROFILE", REPO / "profile.json"))
OUTPUT_DIR = Path(os.environ.get("CVDRAFTER_OUTPUT", REPO / "outputs"))


def load_profile(path: str | os.PathLike | None = None) -> dict:
    """Load the candidate profile as a dict. Fails loudly if it is missing."""
    p = Path(path) if path else PROFILE_PATH
    if not p.is_file():
        raise FileNotFoundError(
            f"profile not found at {p}. Copy profile.example.json to profile.json "
            f"(or set CVDRAFTER_PROFILE) and fill in your details."
        )
    return json.loads(p.read_text(encoding="utf-8"))
