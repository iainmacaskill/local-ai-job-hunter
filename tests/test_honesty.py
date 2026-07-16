import copy

from honesty import verify, verify_text

PROFILE = {
    "jobs": [
        {"title": "Delivery Lead", "company": "Acme", "dates": "Jan 2024 - Present",
         "bullets": ["Cut delivery defects by 30% with Agile.", "Ran cross-functional teams."]},
        {"title": "Project Manager", "company": "Globex", "dates": "2020 - 2023",
         "bullets": ["Migrated 15 million records with zero downtime."]},
    ],
    "achievements": ["Reduced false-positive alerts by 18%."],
    "competencies": ["Agile", "Delivery Management"],
}

CLEAN = {
    "target_title": "Delivery Lead",
    "summary": "Delivery lead with a track record of Agile programme delivery.",
    "core_skills": ["Agile", "Delivery Management"],
    "experience": [
        {"title": "Delivery Lead", "company": "Acme", "dates": "Jan 2024 - Present",
         "bullets": ["Reduced defects by 30% using Agile ceremonies."]},
        {"title": "Project Manager", "company": "Globex", "dates": "2020 - 2023",
         "bullets": ["Migrated 15 million records with no downtime."]},
    ],
}


def test_clean_payload_passes():
    r = verify(CLEAN, PROFILE)
    assert r.ok and not r.errors and not r.warnings


def test_invented_employer_is_an_error():
    p = copy.deepcopy(CLEAN)
    p["experience"][0]["company"] = "Initech"  # never worked there
    r = verify(p, PROFILE)
    assert not r.ok
    assert any("Initech" in e for e in r.errors)


def test_altered_title_is_an_error():
    p = copy.deepcopy(CLEAN)
    p["experience"][0]["title"] = "Head of Delivery"  # inflated title
    r = verify(p, PROFILE)
    assert not r.ok
    assert any("title altered" in e for e in r.errors)


def test_altered_dates_is_an_error():
    p = copy.deepcopy(CLEAN)
    p["experience"][1]["dates"] = "2016 - 2023"  # stretched tenure
    r = verify(p, PROFILE)
    assert not r.ok
    assert any("dates altered" in e for e in r.errors)


def test_fabricated_metric_is_a_warning_not_a_block():
    p = copy.deepcopy(CLEAN)
    p["experience"][0]["bullets"].append("Boosted revenue by 47%.")  # 47% is nowhere real
    r = verify(p, PROFILE)
    assert r.ok  # a figure is a review flag, not a hard block
    assert any("47%" in w for w in r.warnings)


def test_real_metric_does_not_warn():
    # 30%, 15 million, 18% are all genuinely in the profile
    r = verify(CLEAN, PROFILE)
    assert not any("figure" in w for w in r.warnings)


def test_em_dash_is_flagged():
    p = copy.deepcopy(CLEAN)
    p["summary"] = "Delivery lead — regulated environments."
    r = verify(p, PROFILE)
    assert any("em dash" in w for w in r.warnings)


def test_verify_text_clean_prose_passes():
    r = verify_text("Delivered a 15 million record migration and cut defects 30%.", PROFILE)
    assert r.ok and not r.warnings


def test_verify_text_flags_fake_figure_and_em_dash():
    r = verify_text("Saved the client 40% in year one — every quarter.", PROFILE)
    assert any("40%" in w for w in r.warnings)
    assert any("em dash" in w for w in r.warnings)
