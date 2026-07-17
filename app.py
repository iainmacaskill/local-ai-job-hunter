"""cv-drafter-local tracker (Phase B) — a local dashboard of the roles you pursue.

Story B1: connect to the local SQLite store and list roles. It starts empty (a
fresh tracker); adding, editing, the pipeline metrics and drafting-from-a-row
arrive in B2 to B4. Run with:  ./.venv/bin/streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import tracker_db

st.set_page_config(page_title="CV Drafter — Tracker", page_icon="📋", layout="wide")


@st.cache_resource
def _conn():
    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    return conn


st.title("📋 Roles")

roles = tracker_db.list_roles(_conn())

if not roles:
    st.info(
        "No roles yet. This is your fresh, local tracker. Nothing here leaves your "
        "machine. Adding roles arrives in the next story (B2)."
    )
else:
    st.caption(f"{len(roles)} role(s)")
    st.dataframe(
        roles,
        use_container_width=True,
        hide_index=True,
        column_order=[
            "id", "date_found", "title", "company", "type", "rate",
            "location", "status", "coverage", "date_applied", "outcome",
        ],
    )
