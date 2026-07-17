"""Local AI Job Hunter's tracker — a local dashboard of the roles you pursue.

Add roles (with the pasted job description), edit them inline, watch the pipeline
metrics, and draft the CV/cover letter for a role straight from its row using the
local model. Starts empty; nothing leaves your machine. Run with:
  ./.venv/bin/streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

import adzuna
import followup
import hunt
import reed
import settings
import tracker_db
import tracker_draft
from cv_profile import load_profile
from local_llm import LocalLLM

# Adzuna first: its keys are issued instantly, so it is the default source.
SOURCES = {"Adzuna": adzuna, "Reed": reed}

st.set_page_config(page_title="CV Drafter — Tracker", page_icon="📋", layout="wide")

# Columns shown in the grid, in order. The rest (jd_text, cv_file, timestamps) are
# kept but not shown here. `date_found` and `coverage` are read-only (managed).
GRID_COLUMNS = [
    "id", "date_found", "title", "company", "type", "rate", "location",
    "status", "coverage", "date_applied", "contact_email", "outcome", "link", "fit_notes",
]
READONLY_COLUMNS = ["id", "date_found", "coverage"]
TYPE_OPTIONS = ["", "Contract", "Permanent"]


@st.cache_resource
def _conn():
    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    return conn


def _source_ready(name: str) -> bool:
    if name == "Reed":
        return bool(os.environ.get("REED_API_KEY"))
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def _find_roles(conn) -> None:
    """Search a free job board and log new roles to the tracker (C3)."""
    settings.load_env()  # pick up a .env created after the app started
    with st.expander("🔎 Find roles (Reed / Adzuna)"):
        name = st.radio("Source", list(SOURCES), horizontal=True, key="find_source")
        ready = _source_ready(name)
        if not ready:
            need = "REED_API_KEY" if name == "Reed" else "ADZUNA_APP_ID and ADZUNA_APP_KEY"
            where = "reed.co.uk/developers" if name == "Reed" else "developer.adzuna.com"
            st.info(f"Add {need} to a .env file to search {name} (free key at {where}).")

        terms = st.text_area(
            "Search terms (one per line)", value="ai delivery manager\nprogramme manager",
            height=90, key="find_terms",
        )
        c1, c2, c3 = st.columns(3)
        location = c1.text_input("Location", value="London", key="find_location")
        distance = c2.number_input("Distance (miles)", min_value=0, value=20, key="find_distance")
        min_salary = c3.number_input(
            "Min salary", min_value=0, value=0, step=1000, key="find_salary"
        )
        role_type = st.radio(
            "Type", ["Any", "Contract", "Permanent"], horizontal=True, key="find_type"
        )

        if st.button("Find roles", type="primary", disabled=not ready, key="find_go"):
            keywords = [t.strip() for t in terms.splitlines() if t.strip()]
            if not keywords:
                st.error("Add at least one search term.")
                st.stop()
            common = {
                "location": location.strip() or None,
                "distance": int(distance),
                "minimum_salary": int(min_salary) or None,
                "contract": role_type == "Contract" or None,
                "permanent": role_type == "Permanent" or None,
            }
            searches = [{"keywords": kw, **common} for kw in keywords]
            with st.spinner(f"Searching {name}..."):
                try:
                    summary = hunt.sweep(
                        conn, searches, source=SOURCES[name],
                        title_terms=hunt.RELEVANT_TITLE_TERMS,
                    )
                except RuntimeError as exc:  # missing/rejected key, API down
                    st.error(f"Search failed: {exc}")
                    st.stop()
            st.success(
                f"Added {len(summary['added'])} new role(s). Skipped "
                f"{summary['skipped_seen']} already tracked, "
                f"{summary['skipped_duplicate']} duplicate re-posts, "
                f"{summary['skipped_irrelevant']} off-target titles, "
                f"{summary['skipped_clearance']} needing clearance."
            )


def _add_role_form(conn) -> None:
    empty = not tracker_db.list_roles(conn)
    with st.expander("➕ Add a role", expanded=empty):
        with st.form("add_role", clear_on_submit=True):
            title = st.text_input("Title *")
            c1, c2, c3 = st.columns(3)
            company = c1.text_input("Company")
            role_type = c2.selectbox("Type", TYPE_OPTIONS)
            rate = c3.text_input("Rate")
            c4, c5 = st.columns(2)
            location = c4.text_input("Location")
            link = c5.text_input("Link")
            fit_notes = st.text_input("Fit notes")
            jd_text = st.text_area(
                "Job description (paste the advert; used to draft the CV later)",
                height=160,
            )
            submitted = st.form_submit_button("Add role")
        if submitted:
            if not title.strip():
                st.error("A role needs a title.")
            else:
                tracker_db.add_role(
                    conn,
                    title=title.strip(),
                    company=company.strip() or None,
                    type=role_type or None,
                    rate=rate.strip() or None,
                    location=location.strip() or None,
                    link=link.strip() or None,
                    fit_notes=fit_notes.strip() or None,
                    jd_text=jd_text.strip() or None,
                )
                st.success(f"Added: {title.strip()}")
                st.rerun()


def _persist_grid_edits() -> None:
    """Callback: persist inline edits, and archive rows removed from the grid.

    Everything is keyed to the ids of the rows *as displayed* (stored in session
    state before the grid renders), so it stays correct even when filtered.
    Removing a row archives it (reversible from the Archive panel), never deletes.
    """
    state = st.session_state.get("roles_editor", {})
    ids = st.session_state.get("grid_ids", [])
    if not ids:
        return
    conn = _conn()
    if state.get("edited_rows"):
        n = tracker_db.apply_editor_changes(conn, ids, state["edited_rows"])
        if n:
            st.toast(f"Saved {n} change(s)")
    if state.get("deleted_rows"):
        n = tracker_db.archive_editor_deletions(conn, ids, state["deleted_rows"])
        if n:
            st.toast(f"Archived {n} role(s). Restore from the Archive panel below.")
    if state.get("added_rows"):
        st.toast("Use the Add a role form above to add roles.")


def _metrics_row(roles, due_count: int) -> None:
    m = tracker_db.summarise(roles)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("To triage", m["to_triage"], help="Found, not yet reviewed")
    c2.metric("Pursuing", m["pursuing"], help="Drafting a CV / cover letter")
    c3.metric("Applied", m["applied"])
    c4.metric("Follow-ups due", due_count, help="Applied 2+ working days ago, no follow-up yet")
    c5.metric("Passed", m["passed"])


def _followups_due(conn, due: list[dict]) -> None:
    """Applied roles due a follow-up: capture the contact, draft, open in email."""
    if not due:
        return
    st.subheader(f"📮 Follow-ups due ({len(due)})")
    st.caption(
        "Applied two or more working days ago with no follow-up recorded. Drafts only: "
        "sending happens in your own email app, never from here."
    )
    for r in due:
        label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
        with st.expander(f"{label} (applied {r.get('date_applied')})"):
            email = st.text_input(
                "Recruiter email", value=r.get("contact_email") or "",
                key=f"fu_email_{r['id']}",
                help="Parsed from the advert when published there; otherwise paste it "
                     "from your application confirmation. Never guessed.",
            )
            if r.get("contact_source") == "advert" and r.get("contact_email"):
                st.caption("Address found in the advert text.")
            if st.button("Draft follow-up", key=f"fu_draft_{r['id']}"):
                if email.strip() != (r.get("contact_email") or ""):
                    tracker_db.update_role(conn, r["id"], contact_email=email.strip() or None,
                                           contact_source="manual" if email.strip() else None)
                try:
                    profile = load_profile()
                except FileNotFoundError:
                    profile = {}
                llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
                if profile and llm.is_up():
                    with st.spinner("Drafting locally..."):
                        st.session_state[f"fu_text_{r['id']}"] = followup.draft_followup(
                            r, profile, llm
                        )
                else:
                    st.session_state[f"fu_text_{r['id']}"] = followup.template_followup(
                        r, profile
                    )
            draft = st.session_state.get(f"fu_text_{r['id']}")
            if draft:
                st.text_input("Subject", value=draft["subject"], key=f"fu_subj_{r['id']}")
                st.text_area("Body", value=draft["body"], height=180, key=f"fu_body_{r['id']}")
                if draft.get("honesty") and draft["honesty"].warnings:
                    for w in draft["honesty"].warnings:
                        st.caption(f"review: {w}")
                c1, c2 = st.columns(2)
                target = st.session_state.get(f"fu_email_{r['id']}", "").strip()
                if target:
                    c1.link_button(
                        "✉ Open in your email app",
                        followup.mailto_link(
                            target,
                            st.session_state.get(f"fu_subj_{r['id']}", draft["subject"]),
                            st.session_state.get(f"fu_body_{r['id']}", draft["body"]),
                        ),
                    )
                if c2.button("Mark followed up", key=f"fu_done_{r['id']}"):
                    followup.mark_followed_up(conn, r["id"])
                    st.session_state.pop(f"fu_text_{r['id']}", None)
                    st.rerun()


def _download(col, path, label) -> None:
    if not path:
        return
    p = Path(path)
    if p.exists():
        col.download_button(label, p.read_bytes(), file_name=p.name, key=f"dl_{p.name}")


def _latest_draft_panel() -> None:
    """Show the most recent draft's result and download links (survives the rerun)."""
    d = st.session_state.get("last_draft")
    if not d:
        return
    with st.container(border=True):
        st.markdown(f"**Latest draft: {d['title']}**")
        st.write(f"Coverage {d['coverage']}%. Honesty: {d['honesty']}.")
        for w in d.get("warnings", []):
            st.caption(f"review: {w}")
        if d.get("gaps"):
            st.caption(f"keyword gaps: {', '.join(d['gaps'])}")
        c1, c2, c3 = st.columns(3)
        _download(c1, d.get("cv_path"), "⬇ Screening CV (.docx)")
        _download(c2, d.get("pdf_path"), "⬇ Interview CV (.pdf)")
        _download(c3, d.get("cover_path"), "⬇ Cover letter (.docx)")


def _draft_queue(conn, roles) -> None:
    """Roles queued for drafting: a draft status, and no CV drafted yet."""
    queued = [
        r for r in roles
        if (r["status"] or "") in tracker_draft.CV_QUEUE_STATUSES and not r.get("cv_file")
    ]
    if not queued:
        return
    st.subheader(f"✍️ To draft ({len(queued)})")
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
    up = llm.is_up()
    if not up:
        st.warning(
            f"Local model not reachable at {settings.LLM_BASE_URL}. "
            "Start LM Studio's local server to draft."
        )
    for r in queued:
        label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
        with st.expander(label, expanded=True):
            jd = st.text_area(
                "Job description", value=r.get("jd_text") or "", height=140, key=f"jd_{r['id']}"
            )
            cover = r["status"] == "Draft CV & Cover Letter"
            st.caption(
                "Will draft: screening CV and interview PDF"
                + (", plus a cover letter." if cover else ".")
            )
            if st.button("Draft now", key=f"draft_{r['id']}", disabled=not up, type="primary"):
                if not jd.strip():
                    st.error("Paste the job description first.")
                    st.stop()
                tracker_db.update_role(conn, r["id"], jd_text=jd.strip())
                role = dict(r)
                role["jd_text"] = jd.strip()
                with st.spinner("Drafting locally, about a minute..."):
                    try:
                        out = tracker_draft.draft_for_role(conn, role, llm=llm)
                    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
                        st.error(f"Drafting failed: {exc}")
                        st.stop()
                cv = out["cv"]
                st.session_state["last_draft"] = {
                    "title": r["title"],
                    "coverage": cv["coverage"]["pct"],
                    "gaps": cv["coverage"]["missing"],
                    "honesty": cv["honesty"].summary(),
                    "warnings": list(cv["honesty"].warnings),
                    "cv_path": str(cv["docx"]),
                    "pdf_path": str(cv["pdf"]) if cv.get("pdf") else None,
                    "cover_path": str(out["cover"]["docx"]) if out.get("cover") else None,
                }
                st.rerun()


def _archive_panel(conn) -> None:
    """Archived roles: restore them, or permanently delete after a confirm tick."""
    archived = tracker_db.list_archived(conn)
    if not archived:
        return
    with st.expander(f"🗂 Archive ({len(archived)})"):
        st.caption(
            "Archived roles are off the board but still known to the sweep, so they "
            "will not be re-added by a search. Restore any, or delete them for good."
        )
        for r in archived:
            c1, c2 = st.columns([5, 1])
            label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
            c1.write(f"{label} ({r.get('status')})")
            if c2.button("Restore", key=f"restore_{r['id']}"):
                tracker_db.restore_roles(conn, [r["id"]])
                st.rerun()
        st.divider()
        sure = st.checkbox(
            f"Yes, permanently delete all {len(archived)} archived role(s)",
            key="purge_confirm",
        )
        if st.button("Delete permanently", disabled=not sure, key="purge_go"):
            n = tracker_db.delete_roles(conn, [r["id"] for r in archived])
            st.toast(f"Deleted {n} role(s) permanently")
            st.rerun()


conn = _conn()

st.title("📋 Roles")
_latest_draft_panel()
_find_roles(conn)
_add_role_form(conn)

followup.scan_contacts(conn)  # stamp advert-published emails onto contact-less roles
roles = tracker_db.list_roles(conn)
due = followup.list_due(conn)

if not roles:
    st.info(
        "No roles yet. Add one above. This is your fresh, local tracker. Nothing here "
        "leaves your machine."
    )
else:
    _metrics_row(roles, len(due))
    selected = st.multiselect(
        "Filter by status", tracker_db.STATUSES, default=tracker_db.STATUSES
    )
    view = [r for r in roles if (r["status"] or "") in selected]
    # Remember the displayed row ids (in order) so the edit callback maps correctly.
    st.session_state["grid_ids"] = [r["id"] for r in view]

    st.caption(
        f"Showing {len(view)} of {len(roles)} role(s). Edit any cell; changes save "
        f"automatically. Tick rows and press Delete to archive them (reversible below)."
    )
    df = pd.DataFrame(view, columns=list(GRID_COLUMNS))
    st.data_editor(
        df,
        key="roles_editor",
        on_change=_persist_grid_edits,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        disabled=READONLY_COLUMNS,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "date_found": st.column_config.TextColumn("Found", width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=tracker_db.STATUSES),
            "type": st.column_config.SelectboxColumn("Type", options=TYPE_OPTIONS),
            "coverage": st.column_config.NumberColumn("Cov %", width="small"),
            "link": st.column_config.LinkColumn("Link"),
            "fit_notes": st.column_config.TextColumn("Fit notes", width="large"),
        },
    )
    if st.button(
        "🧹 Archive duplicate re-posts",
        help="Same vacancy posted again (by another agency, or with the employer "
             "spelled differently). Keeps the earliest; archiving is reversible below.",
    ):
        archived = hunt.dedupe_board(conn)
        if archived:
            st.toast(f"Archived {len(archived)} duplicate(s). Restore from the Archive panel.")
        else:
            st.toast("No duplicates found.")
        st.rerun()

    _draft_queue(conn, roles)
    _followups_due(conn, due)

_archive_panel(conn)
