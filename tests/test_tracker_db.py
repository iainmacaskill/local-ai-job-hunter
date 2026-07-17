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
