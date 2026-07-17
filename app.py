"""cv-drafter-local tracker (Phase B) — a local dashboard of the roles you pursue.

Story B2: add roles (including the pasted job description, so B4 can draft from a
row) and edit them inline. Starts empty; nothing leaves your machine. Run with:
  ./.venv/bin/streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import tracker_db

st.set_page_config(page_title="CV Drafter — Tracker", page_icon="📋", layout="wide")

# Columns shown in the grid, in order. The rest (jd_text, cv_file, timestamps) are
# kept but not shown here. `date_found` and `coverage` are read-only (managed).
GRID_COLUMNS = [
    "id", "date_found", "title", "company", "type", "rate", "location",
    "status", "coverage", "date_applied", "outcome", "link", "fit_notes",
]
READONLY_COLUMNS = ["id", "date_found", "coverage"]
TYPE_OPTIONS = ["", "Contract", "Permanent"]


@st.cache_resource
def _conn():
    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    return conn


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
    """Callback: write the grid's inline edits back to the database."""
    state = st.session_state.get("roles_editor", {})
    conn = _conn()
    n = tracker_db.apply_editor_changes(
        conn, tracker_db.list_roles(conn), state.get("edited_rows", {})
    )
    if n:
        st.toast(f"Saved {n} change(s)")


conn = _conn()

st.title("📋 Roles")
_add_role_form(conn)

roles = tracker_db.list_roles(conn)

if not roles:
    st.info(
        "No roles yet. Add one above. This is your fresh, local tracker. Nothing here "
        "leaves your machine."
    )
else:
    st.caption(f"{len(roles)} role(s). Edit any cell to update; changes save automatically.")
    df = pd.DataFrame(roles, columns=[c for c in GRID_COLUMNS])
    st.data_editor(
        df,
        key="roles_editor",
        on_change=_persist_grid_edits,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
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
