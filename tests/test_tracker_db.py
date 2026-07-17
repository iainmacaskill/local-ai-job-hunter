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


def test_apply_editor_changes_maps_index_to_id(tmp_path):
    conn = _db(tmp_path)
    first = tracker_db.add_role(conn, title="First")     # row index 1 (newest first)
    second = tracker_db.add_role(conn, title="Second")   # row index 0
    ordered = tracker_db.list_roles(conn)
    # Edit row 0 (Second) -> Applied, and row 1 (First) -> a fit note.
    edited = {
        "0": {"status": "Applied", "date_applied": "2026-07-17"},
        1: {"fit_notes": "strong match"},
    }
    n = tracker_db.apply_editor_changes(conn, ordered, edited)
    assert n == 2
    assert tracker_db.get_role(conn, second)["status"] == "Applied"
    assert tracker_db.get_role(conn, second)["date_applied"] == "2026-07-17"
    assert tracker_db.get_role(conn, first)["fit_notes"] == "strong match"


def test_apply_editor_changes_ignores_unknown_columns_and_empty(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="Only")
    ordered = tracker_db.list_roles(conn)
    # A change with only an unknown column should not count as an update.
    assert tracker_db.apply_editor_changes(conn, ordered, {"0": {"bogus": "x"}}) == 0
    assert tracker_db.apply_editor_changes(conn, ordered, {}) == 0
    assert tracker_db.get_role(conn, rid)["status"] == "Found"
