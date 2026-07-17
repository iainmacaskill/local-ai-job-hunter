"""Cover the slim tracker persistence layer (B1)."""

import pytest

import tracker_db


def _db(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    return conn


def test_add_list_get_roundtrip(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(
        conn, title="AI Delivery Manager", company="Acme", type="Contract",
        rate="£650/day", location="London", status="Found",
    )
    got = tracker_db.get_role(conn, rid)
    assert got["title"] == "AI Delivery Manager" and got["company"] == "Acme"
    assert got["status"] == "Found"           # explicit
    assert got["date_found"] and got["created_at"]   # defaults stamped
    listed = tracker_db.list_roles(conn)
    assert [r["id"] for r in listed] == [rid]


def test_status_defaults_to_found_when_omitted(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="Programme Manager")
    assert tracker_db.get_role(conn, rid)["status"] == "Found"


def test_title_is_required(tmp_path):
    conn = _db(tmp_path)
    with pytest.raises(ValueError):
        tracker_db.add_role(conn, title="  ", company="Acme")


def test_update_role_changes_fields_and_ignores_unknown(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="PM")
    tracker_db.update_role(conn, rid, status="Applied", date_applied="2026-07-17",
                           bogus_column="nope")
    got = tracker_db.get_role(conn, rid)
    assert got["status"] == "Applied" and got["date_applied"] == "2026-07-17"
    assert "bogus_column" not in got


def test_newest_first_ordering(tmp_path):
    conn = _db(tmp_path)
    first = tracker_db.add_role(conn, title="First")
    second = tracker_db.add_role(conn, title="Second")
    assert [r["id"] for r in tracker_db.list_roles(conn)] == [second, first]


def test_apply_editor_changes_maps_index_to_displayed_id(tmp_path):
    conn = _db(tmp_path)
    first = tracker_db.add_role(conn, title="First")     # row index 1 (newest first)
    second = tracker_db.add_role(conn, title="Second")   # row index 0
    ids = [r["id"] for r in tracker_db.list_roles(conn)]  # displayed order: [second, first]
    # Edit row 0 (Second) -> Applied, and row 1 (First) -> a fit note.
    edited = {
        "0": {"status": "Applied", "date_applied": "2026-07-17"},
        1: {"fit_notes": "strong match"},
    }
    n = tracker_db.apply_editor_changes(conn, ids, edited)
    assert n == 2
    assert tracker_db.get_role(conn, second)["status"] == "Applied"
    assert tracker_db.get_role(conn, second)["date_applied"] == "2026-07-17"
    assert tracker_db.get_role(conn, first)["fit_notes"] == "strong match"


def test_apply_editor_changes_respects_a_filtered_id_list(tmp_path):
    conn = _db(tmp_path)
    tracker_db.add_role(conn, title="Hidden")
    keep = tracker_db.add_role(conn, title="Shown")
    # As if the grid were filtered to a single row: only `keep` is displayed at index 0.
    n = tracker_db.apply_editor_changes(conn, [keep], {"0": {"status": "Pass"}})
    assert n == 1
    assert tracker_db.get_role(conn, keep)["status"] == "Pass"


def test_apply_editor_changes_ignores_unknown_columns_and_empty(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="Only")
    ids = [r["id"] for r in tracker_db.list_roles(conn)]
    # A change with only an unknown column should not count as an update.
    assert tracker_db.apply_editor_changes(conn, ids, {"0": {"bogus": "x"}}) == 0
    assert tracker_db.apply_editor_changes(conn, ids, {}) == 0
    assert tracker_db.get_role(conn, rid)["status"] == "Found"


def test_summarise_counts_the_search_funnel(tmp_path):
    conn = _db(tmp_path)
    for title, status in [
        ("a", "Found"), ("b", "Found"), ("c", "Draft CV"),
        ("d", "Draft CV & Cover Letter"), ("e", "Applied"), ("f", "Pass"),
    ]:
        rid = tracker_db.add_role(conn, title=title)
        tracker_db.update_role(conn, rid, status=status)
    m = tracker_db.summarise(tracker_db.list_roles(conn))
    assert m["total"] == 6
    assert m["to_triage"] == 2       # two Found
    assert m["pursuing"] == 2        # Draft CV + Draft CV & Cover Letter
    assert m["applied"] == 1         # Applied
    assert m["passed"] == 1          # Pass


def test_init_db_migrates_retired_statuses(tmp_path):
    conn = _db(tmp_path)
    # Rows left on old (pre-slim) statuses, then re-init to migrate them.
    for status in ("Expired", "Rejected", "Interview", "Offer", "CV Drafted"):
        rid = tracker_db.add_role(conn, title=status)
        conn.execute("UPDATE roles SET status = ? WHERE id = ?", (status, rid))
    conn.commit()
    tracker_db.init_db(conn)
    live = {(r["title"], r["status"]) for r in tracker_db.list_roles(conn)}
    assert ("Expired", "Pass") in live and ("Rejected", "Pass") in live
    assert ("Interview", "Applied") in live and ("Offer", "Applied") in live
    assert ("CV Drafted", "Draft CV") in live
    assert all(r["status"] in tracker_db.STATUSES for r in tracker_db.list_roles(conn))
