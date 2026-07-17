"""Cover the follow-up feature (Phase D): contacts, due dates, drafts. Offline."""

import datetime as dt

import followup
import tracker_db

PROFILE = {"name": "Alex Rivera", "jobs": []}


def _db(tmp_path):
    conn = tracker_db.connect(tmp_path / "t.db")
    tracker_db.init_db(conn)
    return conn


def _applied(conn, title="AI Delivery Manager", applied="2026-07-14", **extra):
    rid = tracker_db.add_role(conn, title=title, company="Acme", **extra)
    tracker_db.update_role(conn, rid, status="Applied", date_applied=applied)
    return rid


# --- contact discovery ------------------------------------------------------ #

def test_find_advert_email_finds_person_and_skips_noreply():
    jd = "Apply now. Questions to jane.doe@agency.co.uk or noreply@jobs-board.com."
    assert followup.find_advert_email(jd) == "jane.doe@agency.co.uk"
    assert followup.find_advert_email("no address in this advert") is None
    assert followup.find_advert_email(None) is None
    assert followup.find_advert_email("only noreply@x.com here") is None


def test_scan_contacts_stamps_advert_email_but_never_overwrites(tmp_path):
    conn = _db(tmp_path)
    a = tracker_db.add_role(conn, title="A", jd_text="Contact bob@agency.com to apply.")
    b = tracker_db.add_role(conn, title="B", jd_text="Contact new@agency.com.",
                            contact_email="kept@manual.com", contact_source="manual")
    assert followup.scan_contacts(conn) == 1
    assert tracker_db.get_role(conn, a)["contact_email"] == "bob@agency.com"
    assert tracker_db.get_role(conn, a)["contact_source"] == "advert"
    assert tracker_db.get_role(conn, b)["contact_email"] == "kept@manual.com"  # untouched


# --- due-date logic --------------------------------------------------------- #

def test_add_working_days_skips_weekends():
    thu, fri, mon = dt.date(2026, 7, 2), dt.date(2026, 7, 3), dt.date(2026, 7, 6)
    assert followup.add_working_days(thu, 2) == dt.date(2026, 7, 6)   # Thu -> Mon
    assert followup.add_working_days(fri, 2) == dt.date(2026, 7, 7)   # Fri -> Tue
    assert followup.add_working_days(mon, 2) == dt.date(2026, 7, 8)   # Mon -> Wed


def test_list_due_selects_only_ripe_unfollowed_applied(tmp_path):
    conn = _db(tmp_path)
    today = dt.date(2026, 7, 17)                       # Friday
    ripe = _applied(conn, title="Ripe", applied="2026-07-14")      # Tue, due Thu 16th
    _applied(conn, title="Fresh", applied="2026-07-16")            # Thu, due Mon 20th
    done = _applied(conn, title="Done", applied="2026-07-10")
    tracker_db.update_role(conn, done, followed_up_at="2026-07-15")
    tracker_db.add_role(conn, title="Not applied")
    due = followup.list_due(conn, today=today)
    assert [r["id"] for r in due] == [ripe]


def test_list_due_ignores_missing_or_bad_dates(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="No date")
    tracker_db.update_role(conn, rid, status="Applied")            # date_applied empty
    assert followup.list_due(conn, today=dt.date(2026, 7, 17)) == []


def test_apply_editor_changes_stamps_date_applied_on_move_to_applied(tmp_path):
    conn = _db(tmp_path)
    rid = tracker_db.add_role(conn, title="Auto stamp")
    tracker_db.apply_editor_changes(conn, [rid], {"0": {"status": "Applied"}})
    got = tracker_db.get_role(conn, rid)
    assert got["status"] == "Applied"
    assert got["date_applied"] == dt.date.today().isoformat()


# --- drafting --------------------------------------------------------------- #

def test_template_followup_mentions_role_and_stays_em_dash_free(tmp_path):
    conn = _db(tmp_path)
    rid = _applied(conn)
    out = followup.template_followup(tracker_db.get_role(conn, rid), PROFILE)
    assert "AI Delivery Manager" in out["subject"]
    assert "AI Delivery Manager" in out["body"] and "Alex Rivera" in out["body"]
    assert "—" not in out["subject"] + out["body"]


class FakeLLM:
    def complete_json(self, system, user, max_tokens=0):
        return {"subject": "Following up: AI Delivery Manager",
                "body": "Hello,\n\nI remain very interested.\n\nKind regards,\nAlex Rivera"}


def test_draft_followup_uses_llm_and_verifies(tmp_path):
    conn = _db(tmp_path)
    rid = _applied(conn)
    out = followup.draft_followup(tracker_db.get_role(conn, rid), PROFILE, FakeLLM())
    assert "interested" in out["body"]
    assert out["honesty"] is not None and out["honesty"].ok


def test_draft_followup_falls_back_to_template_on_llm_error(tmp_path):
    from local_llm import LocalLLMError

    class DeadLLM:
        def complete_json(self, *a, **k):
            raise LocalLLMError("endpoint down")

    conn = _db(tmp_path)
    rid = _applied(conn)
    out = followup.draft_followup(tracker_db.get_role(conn, rid), PROFILE, DeadLLM())
    assert "continued interest" in out["body"]      # the template


def test_mailto_link_encodes_subject_and_body():
    url = followup.mailto_link("jane@agency.co.uk", "Hello & thanks", "Line one\nLine two")
    assert url.startswith("mailto:jane@agency.co.uk?")
    assert "Hello%20%26%20thanks" in url and "Line%20one%0ALine%20two" in url


def test_mark_followed_up_stamps_date(tmp_path):
    conn = _db(tmp_path)
    rid = _applied(conn)
    followup.mark_followed_up(conn, rid, when=dt.date(2026, 7, 17))
    assert tracker_db.get_role(conn, rid)["followed_up_at"] == "2026-07-17"
