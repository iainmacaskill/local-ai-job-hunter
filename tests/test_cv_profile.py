import json
from pathlib import Path

import pytest

import cv_profile as profile_mod

REPO = Path(profile_mod.__file__).resolve().parent
USED_KEYS = ("name", "contact", "jobs", "competencies", "achievements",
             "certifications", "education")


def test_example_profile_parses_and_has_the_used_keys():
    d = json.loads((REPO / "profile.example.json").read_text())
    for key in USED_KEYS:
        assert key in d, f"example profile missing {key!r}"
    assert d["jobs"]
    assert all({"title", "company", "dates", "bullets"} <= set(j) for j in d["jobs"])


def test_config_paths():
    assert profile_mod.PROFILE_PATH.suffix == ".json"
    assert isinstance(profile_mod.OUTPUT_DIR, Path)


def test_load_profile_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        profile_mod.load_profile(tmp_path / "does-not-exist.json")


def test_load_profile_reads_a_given_file():
    d = profile_mod.load_profile(REPO / "profile.example.json")
    assert d["name"] == "Alex Rivera"
