"""Cover saved searches (Phase D): CRUD, upsert, and the sweep-param mapping."""

import pytest

import hunt
import tracker_db


def _db(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    return conn


def test_save_list_get_roundtrip(tmp_path):
    conn = _db(tmp_path)
    sid = tracker_db.save_search(
        conn, "London AI hunt", keywords="ai delivery manager\nprogramme manager",
        source="Adzuna", location="London", distance=20, min_salary=60000,
        role_type="Contract",
    )
    rows = tracker_db.list_searches(conn)
    assert [r["id"] for r in rows] == [sid]
    s = tracker_db.get_search(conn, "London AI hunt")
    assert s["source"] == "Adzuna" and s["distance"] == 20
    assert s["keywords"].splitlines() == ["ai delivery manager", "programme manager"]
    assert s["last_run_at"] is None


def test_save_search_upserts_by_name(tmp_path):
    conn = _db(tmp_path)
    first = tracker_db.save_search(conn, "Hunt", keywords="a", location="London")
    second = tracker_db.save_search(conn, "Hunt", keywords="b", location="Remote")
    assert first == second                       # same row updated, not duplicated
    assert len(tracker_db.list_searches(conn)) == 1
    s = tracker_db.get_search(conn, "Hunt")
    assert s["keywords"] == "b" and s["location"] == "Remote"


def test_save_search_requires_name_and_keywords(tmp_path):
    conn = _db(tmp_path)
    with pytest.raises(ValueError):
        tracker_db.save_search(conn, "  ", keywords="a")
    with pytest.raises(ValueError):
        tracker_db.save_search(conn, "Hunt", keywords="  ")


def test_delete_and_mark_run(tmp_path):
    conn = _db(tmp_path)
    sid = tracker_db.save_search(conn, "Hunt", keywords="a")
    tracker_db.mark_search_run(conn, sid)
    assert tracker_db.get_search(conn, "Hunt")["last_run_at"] is not None
    tracker_db.delete_search(conn, sid)
    assert tracker_db.list_searches(conn) == []


def test_saved_to_searches_maps_fields_and_type_flags():
    saved = {
        "keywords": "ai delivery manager\n\nprogramme manager\n",
        "location": "London", "distance": 20, "min_salary": 60000,
        "role_type": "Contract",
    }
    searches = hunt.saved_to_searches(saved)
    assert [s["keywords"] for s in searches] == ["ai delivery manager", "programme manager"]
    assert all(s["location"] == "London" and s["distance"] == 20 for s in searches)
    assert all(s["minimum_salary"] == 60000 for s in searches)
    assert all(s["contract"] is True and s["permanent"] is None for s in searches)


def test_saved_to_searches_defaults_when_fields_missing():
    searches = hunt.saved_to_searches({"keywords": "pm"})
    assert searches == [{
        "keywords": "pm", "location": None, "distance": 10,
        "minimum_salary": None, "contract": None, "permanent": None,
    }]
