"""Cover the Reed -> tracker sweep (C2): dedupe, clearance skip, insert. Offline."""

import types

import hunt
import reed
import tracker_db


def _role(job_id, title="AI Delivery Manager", company="Acme", desc="Lead AI delivery."):
    return reed.Role(
        job_id=job_id, title=title, company=company, location="London",
        salary="£600 to £700", posted="17/07/2026",
        link=f"https://www.reed.co.uk/jobs/x/{job_id}", description=desc, role_type="Contract",
    )


def _db(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    return conn


def _patch_reed(monkeypatch, results, jd="Full job description."):
    monkeypatch.setattr(reed, "search", lambda **kw: list(results))
    monkeypatch.setattr(reed, "job_description", lambda job_id, api_key=None: jd)


def test_sweep_inserts_new_roles_as_found_with_jd(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _patch_reed(monkeypatch, [_role("111"), _role("222", title="Programme Manager")])
    summary = hunt.sweep(conn, [{"keywords": "ai delivery manager"}])

    assert len(summary["added"]) == 2 and summary["skipped_seen"] == 0
    rows = tracker_db.list_roles(conn)
    assert {r["source_job_id"] for r in rows} == {"111", "222"}
    r = tracker_db.get_role(conn, summary["added"][0]["id"])
    assert r["status"] == "Found"
    assert r["jd_text"] == "Full job description."   # full JD fetched, not the blurb
    assert r["link"].endswith("/222") or r["link"].endswith("/111")


def test_sweep_dedupes_against_tracked_and_within_run(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    tracker_db.add_role(conn, title="Existing", source_job_id="111")
    # 111 already tracked; 222 appears in two searches (should insert once).
    _patch_reed(monkeypatch, [_role("111"), _role("222")])
    summary = hunt.sweep(conn, [{"keywords": "one"}, {"keywords": "two"}])
    assert len(summary["added"]) == 1                 # only 222, once
    assert summary["skipped_seen"] == 3               # 111 twice + 222 the second time
    assert sum(1 for r in tracker_db.list_roles(conn) if r["source_job_id"] == "222") == 1


def test_sweep_skips_clearance_roles(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _patch_reed(
        monkeypatch,
        [_role("111"), _role("222", title="Delivery Manager")],
        jd="Great role. Must hold SC clearance from day one.",
    )
    summary = hunt.sweep(conn, [{"keywords": "delivery"}])
    assert summary["added"] == [] and summary["skipped_clearance"] == 2
    assert tracker_db.list_roles(conn) == []


def test_sweep_falls_back_to_blurb_when_jd_fetch_fails(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(reed, "search", lambda **kw: [_role("111", desc="Search blurb.")])

    def boom(job_id, api_key=None):
        raise reed.ReedError("detail endpoint down")

    monkeypatch.setattr(reed, "job_description", boom)
    summary = hunt.sweep(conn, [{"keywords": "x"}])
    assert len(summary["added"]) == 1
    assert tracker_db.get_role(conn, summary["added"][0]["id"])["jd_text"] == "Search blurb."


def _snippet_source():
    """A source without a detail endpoint (like Adzuna): only the search blurb.

    A SimpleNamespace stands in for a source module, so ``__name__`` is a plain
    attribute (a class would have its own name shadow it).
    """
    return types.SimpleNamespace(
        __name__="adzuna",
        HAS_JD_DETAIL=False,
        search=lambda **kw: [_role("999", desc="Snippet from search only.")],
    )


def test_sweep_uses_snippet_when_source_has_no_detail_endpoint(tmp_path):
    conn = _db(tmp_path)
    summary = hunt.sweep(conn, [{"keywords": "x"}], source=_snippet_source())
    assert len(summary["added"]) == 1
    r = tracker_db.get_role(conn, summary["added"][0]["id"])
    assert r["jd_text"] == "Snippet from search only."
    assert r["fit_notes"].startswith("Adzuna sweep:")


def test_sweep_never_readds_an_archived_role(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="Pruned", source_job_id="111")
    tracker_db.archive_roles(conn, [rid])
    _patch_reed(monkeypatch, [_role("111")])
    summary = hunt.sweep(conn, [{"keywords": "x"}])
    assert summary["added"] == [] and summary["skipped_seen"] == 1
    assert len(tracker_db.list_roles(conn, include_archived=True)) == 1   # still just one


def test_sweep_filters_off_target_titles(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _patch_reed(monkeypatch, [
        _role("111", title="AI Delivery Manager"),   # relevant (ai + delivery)
        _role("222", title="HGV Repair Engineer"),   # off-target ('ai' only inside 'repair')
        _role("333", title="Supply Chain Manager"),  # off-target (manager, no domain term)
    ])
    summary = hunt.sweep(conn, [{"keywords": "x"}], title_terms=hunt.RELEVANT_TITLE_TERMS)
    assert [a["title"] for a in summary["added"]] == ["AI Delivery Manager"]
    assert summary["skipped_irrelevant"] == 2


def test_is_duplicate_matches_reposts_conservatively():
    dup = hunt.is_duplicate
    # Employer spelling variants and legal suffixes collapse.
    assert dup("Agentic AI Ops Lead", "JPMorganChase", "Agentic AI Ops Lead", "J.P. Morgan")
    assert dup("Programme Manager", "Linear Executive Search",
               "Programme Manager", "Linear Executive Search Limited")
    assert dup("PM - AI (12 month FTC)", "TechUK", "PM - AI (12 month FTC)", "techUK")
    # Distinct roles are never merged.
    assert not dup("Programme Manager", "Fincroft", "Programme Manager", "La Fosse")
    assert not dup("Programme Manager", "Acme", "Senior Programme Manager", "Acme")
    assert not dup("Programme Manager", "", "Programme Manager", "")   # unknown employers
    assert not dup("Programme Manager", "Reed", "Programme Manager", "Reel")  # short stems


def test_sweep_skips_fuzzy_duplicate_reposts(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    tracker_db.add_role(conn, title="AI Delivery Manager", company="J.P. Morgan",
                        source_job_id="900")
    _patch_reed(monkeypatch, [
        _role("111", company="JPMorganChase"),          # re-post of the tracked role
        _role("222", company="JPMorganChase"),          # re-post within the run of 111
        _role("333", company="Distinct Corp"),          # same title, different employer
    ])
    summary = hunt.sweep(conn, [{"keywords": "x"}])
    assert summary["skipped_duplicate"] == 2
    assert [a["company"] for a in summary["added"]] == ["Distinct Corp"]


def test_dedupe_board_archives_newer_copies_keeps_oldest(tmp_path):
    conn = _db(tmp_path)
    first = tracker_db.add_role(conn, title="PM - AI (12 month FTC)", company="TechUK")
    second = tracker_db.add_role(conn, title="PM - AI (12 month FTC)", company="techUK")
    third = tracker_db.add_role(conn, title="PM - AI (12 month FTC)", company="techUK")
    other = tracker_db.add_role(conn, title="PM - AI (12 month FTC)", company="Other Org")
    archived = hunt.dedupe_board(conn)
    assert sorted(r["id"] for r in archived) == [second, third]
    active_ids = {r["id"] for r in tracker_db.list_roles(conn)}
    assert active_ids == {first, other}                     # earliest + distinct survive
    assert {r["id"] for r in tracker_db.list_archived(conn)} == {second, third}


def test_workstyle_signals_detect_and_normalise():
    got = hunt.workstyle_signals(
        "Hybrid Programme Manager", "Mostly Work From Home; some remote, home-based OK."
    )
    assert got == ["home based", "hybrid", "remote", "wfh"]
    assert hunt.workstyle_signals("On-site role in the office") == []


def test_sweep_stamps_workstyle_and_days_into_fit_notes(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _patch_reed(monkeypatch, [_role("111")],
                jd="Hybrid working: two days a week in the London office, rest remote.")
    summary = hunt.sweep(conn, [{"keywords": "programme manager"}])
    r = tracker_db.get_role(conn, summary["added"][0]["id"])
    assert r["fit_notes"].endswith("| hybrid/remote, 3d home")


def test_home_days_parses_the_common_phrasings():
    assert hunt.home_days("Hybrid, 2 days WFO/week") == 3          # real Infosys wording
    assert hunt.home_days("one day per week in the office") == 4
    assert hunt.home_days("3 days from home, hybrid") == 3
    assert hunt.home_days("Fully remote role") == 5
    assert hunt.home_days("Remote with monthly meetups") == 5      # plain remote signal
    assert hunt.home_days("4 days on site") == 1
    assert hunt.home_days("Hybrid working available") is None      # split unknown
    assert hunt.home_days("Office based in London") is None


def test_init_db_migrates_source_job_id_onto_old_table(tmp_path):
    # An older tracker.db created before source_job_id existed.
    conn = tracker_db.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE roles (id INTEGER PRIMARY KEY, title TEXT, status TEXT)")
    conn.commit()
    tracker_db.init_db(conn)  # should add the missing column, not crash
    cols = {row[1] for row in conn.execute("PRAGMA table_info(roles)")}
    assert "source_job_id" in cols
