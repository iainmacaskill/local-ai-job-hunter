"""Local AI Job Hunter's tracker — a local dashboard of the roles you pursue.

Add roles (with the pasted job description), edit them inline, watch the pipeline
metrics, and draft the CV/cover letter for a role straight from its row using the
local model. Starts empty; nothing leaves your machine. Run with:
  ./.venv/bin/streamlit run app.py
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pandas as pd
import streamlit as st

import adzuna
import fetch_jd
import followup
import hunt
import reed
import settings
import tracker_db
import tracker_draft
import triage
from cv_profile import OUTPUT_DIR, load_profile
from local_llm import LocalLLM

# Adzuna first: its keys are issued instantly, so it is the default source.
SOURCES = {"Adzuna": adzuna, "Reed": reed}

st.set_page_config(page_title="CV Drafter — Tracker", page_icon="📋", layout="wide")

# Columns shown in the grid, in order. The rest (jd_text, cv_file, timestamps) are
# kept but not shown here. `date_found` and `coverage` are read-only (managed).
GRID_COLUMNS = [
    "id", "status", "title", "open", "type", "rate", "location", "company",
    "date_found", "fit_score", "fit_reason", "coverage", "date_applied",
    "contact_email", "outcome", "link", "fit_notes",
]
READONLY_COLUMNS = ["id", "date_found", "open", "coverage", "fit_score", "fit_reason"]
TYPE_OPTIONS = ["", "Contract", "Permanent"]


@st.cache_resource
def _conn():
    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    return conn


@st.cache_data(ttl=10)
def _model_status() -> dict:
    """What model the app will use, and whether the endpoint actually offers it."""
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
    if not llm.is_up(connect_timeout=0.4):
        return {"state": "offline", "model": settings.LLM_MODEL, "available": []}
    available = llm.list_models()
    state = "ready" if (not available or settings.LLM_MODEL in available) else "mismatch"
    return {"state": state, "model": settings.LLM_MODEL, "available": available}


def _model_badge() -> None:
    s = _model_status()
    if s["state"] == "offline":
        st.caption(f"🔴 **Local model offline.** Start LM Studio's server "
                   f"({settings.LLM_BASE_URL}). Configured model: `{s['model']}`")
    elif s["state"] == "mismatch":
        offered = ", ".join(s["available"][:4]) or "none"
        st.caption(f"🟡 **Configured model `{s['model']}` is not offered by LM Studio** "
                   f"(offered: {offered}). Drafting and scoring will fail until it is "
                   f"loaded, or CVDRAFTER_LLM_MODEL is changed (restart the app after).")
    else:
        st.caption(f"🟢 **Model: `{s['model']}`**")


def _source_ready(name: str) -> bool:
    if name == "Reed":
        return bool(os.environ.get("REED_API_KEY"))
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def _run_sweep(conn, source_name: str, searches: list[dict]) -> None:
    """Shared sweep runner: readiness check, spinner, result message."""
    if not _source_ready(source_name):
        st.error(f"{source_name} keys are not set in .env yet.")
        st.stop()
    with st.spinner(f"Searching {source_name}..."):
        try:
            summary = hunt.sweep(
                conn, searches, source=SOURCES[source_name],
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


def _saved_searches(conn) -> None:
    """One-click repeat sweeps from saved criteria."""
    saved = tracker_db.list_searches(conn)
    if not saved:
        return
    st.markdown("**Saved searches**")
    for s in saved:
        c1, c2, c3 = st.columns([5, 1, 1])
        terms = ", ".join((s["keywords"] or "").splitlines())
        last = f"last run {s['last_run_at'][:10]}" if s["last_run_at"] else "never run"
        c1.write(f"**{s['name']}**")
        places = ", ".join((s["location"] or "").splitlines()) or "anywhere"
        c1.caption(f"{s['source']}: {terms} | {places} | {last}")
        if c2.button("Run", key=f"run_search_{s['id']}", type="primary"):
            _run_sweep(conn, s["source"], hunt.saved_to_searches(s))
            tracker_db.mark_search_run(conn, s["id"])
        if c3.button("🗑", key=f"del_search_{s['id']}", help="Delete this saved search"):
            tracker_db.delete_search(conn, s["id"])
            st.rerun()
    st.divider()


def _find_roles(conn) -> None:
    """Search a free job board and log new roles to the tracker (C3)."""
    settings.load_env()  # pick up a .env created after the app started
    with st.expander("🔎 Find roles (Adzuna / Reed)"):
        _saved_searches(conn)
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
        locations_text = c1.text_area(
            "Locations (one per line)", value="London", height=68, key="find_location",
            help="Each search runs in every location, so you can cover the hybrid "
                 "London market and the area round home in one sweep. Postcodes work.",
        )
        distance = c2.number_input("Distance (miles)", min_value=0, value=20, key="find_distance")
        min_salary = c3.number_input(
            "Min salary", min_value=0, value=90000, step=1000, key="find_salary"
        )
        role_type = st.radio(
            "Type", ["Any", "Contract", "Permanent"], horizontal=True, key="find_type"
        )

        keywords = [t.strip() for t in terms.splitlines() if t.strip()]
        locations = [
            loc.strip() for loc in locations_text.splitlines() if loc.strip()
        ] or [None]
        b1, b2, b3 = st.columns([1, 2, 1])
        if b1.button("Find roles", type="primary", disabled=not ready, key="find_go"):
            if not keywords:
                st.error("Add at least one search term.")
                st.stop()
            common = {
                "distance": int(distance),
                "minimum_salary": int(min_salary) or None,
                "contract": role_type == "Contract" or None,
                "permanent": role_type == "Permanent" or None,
            }
            _run_sweep(conn, name, [
                {"keywords": kw, "location": loc, **common}
                for kw in keywords for loc in locations
            ])

        save_name = b2.text_input(
            "Save as", key="find_save_name", placeholder="e.g. London AI hunt",
            label_visibility="collapsed",
        )
        if b3.button("Save search", key="find_save"):
            if not save_name.strip():
                st.error("Give the saved search a name.")
            elif not keywords:
                st.error("Add at least one search term.")
            else:
                tracker_db.save_search(
                    conn, save_name, keywords="\n".join(keywords), source=name,
                    location="\n".join(loc for loc in locations if loc) or None,
                    distance=int(distance),
                    min_salary=int(min_salary) or None,
                    role_type=role_type if role_type != "Any" else None,
                )
                st.toast(f"Saved '{save_name.strip()}'")
                st.rerun()


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
    cv_only = "Screening CV and interview PDF"
    cv_cover = "Screening CV, interview PDF and a cover letter"
    for r in queued:
        label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
        with st.expander(label, expanded=True):
            if r.get("link"):
                st.markdown(f"Link - [{r['link']}]({r['link']})")
                if st.button("⬇ Fetch advert text", key=f"fetch_{r['id']}",
                             help="Fetches the page at the link and drops its "
                                  "readable text into the box below for you to "
                                  "clean up. Some pages cannot be read this way."):
                    try:
                        st.session_state[f"jd_{r['id']}"] = fetch_jd.fetch_advert_text(
                            r["link"]
                        )
                        st.toast("Advert text fetched. Tidy it up before drafting.")
                    except fetch_jd.FetchError as exc:
                        st.warning(f"Could not fetch the advert: {exc}")
            st.markdown("**Job description**")
            # The warning sits above the box (reading order is top-down), so it
            # checks the box's live value from session state, not the stale row.
            jd_current = st.session_state.get(f"jd_{r['id']}", r.get("jd_text") or "")
            if tracker_draft.looks_like_snippet(jd_current):
                st.warning(
                    "This is the search result's snippet, not the full advert. If it "
                    "ends with three dots, that really is where the job board's "
                    "preview stops: nothing is hidden here. Use Fetch advert text "
                    "above, or paste the full advert into the box, for a proper "
                    "draft and an honest coverage score."
                )
            jd = st.text_area(
                "Job description", value=r.get("jd_text") or "", height=140,
                key=f"jd_{r['id']}", label_visibility="collapsed",
            )
            cover = r["status"] == "Draft CV & Cover Letter"
            choice = st.selectbox(
                "Will draft", [cv_only, cv_cover], index=1 if cover else 0,
                key=f"will_{r['id']}",
                help="Switch before drafting if the application unexpectedly asks "
                     "for a cover letter (or does not need one).",
            )
            if st.button("Draft now", key=f"draft_{r['id']}", disabled=not up, type="primary"):
                if not jd.strip():
                    st.error("Paste the job description first.")
                    st.stop()
                wanted = "Draft CV & Cover Letter" if choice == cv_cover else "Draft CV"
                tracker_db.update_role(conn, r["id"], jd_text=jd.strip(), status=wanted)
                role = dict(r)
                role["jd_text"] = jd.strip()
                role["status"] = wanted
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


def _review_drafts(conn, roles) -> None:
    """View, give feedback on, and download the documents for drafted roles."""
    drafted = [
        r for r in roles
        if r.get("cv_file") and (r["status"] or "") in tracker_draft.CV_QUEUE_STATUSES
    ]
    if not drafted:
        return
    st.subheader(f"📄 Review drafts ({len(drafted)})")
    st.caption(
        "Check the CV, ask for changes, download, then mark the role Applied in the "
        "grid once you have submitted it."
    )
    for r in drafted:
        label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
        with st.expander(f"{label} (coverage {r.get('coverage')}%)"):
            pdf_path = tracker_draft.interview_pdf_path(r)
            if pdf_path and pdf_path.exists():
                # Inline preview without extra dependencies: the browser's own
                # PDF viewer in an embed fed by a data URI.
                b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
                st.markdown(
                    f'<embed src="data:application/pdf;base64,{b64}" '
                    f'type="application/pdf" width="100%" height="560">',
                    unsafe_allow_html=True,
                )
            elif pdf_path:
                st.caption("No interview PDF was rendered for this draft.")

            c1, c2, c3 = st.columns(3)
            _download(c1, str(OUTPUT_DIR / r["cv_file"]), "⬇ Screening CV (.docx)")
            if pdf_path and pdf_path.exists():
                _download(c2, str(pdf_path), "⬇ Interview CV (.pdf)")
            if r.get("cover_file"):
                _download(c3, str(OUTPUT_DIR / r["cover_file"]), "⬇ Cover letter (.docx)")

            feedback = st.text_area(
                "What should change?", key=f"fb_{r['id']}",
                placeholder="e.g. Lead with the NHS AI programme in the summary, and "
                            "make the governance experience more prominent.",
                help="Feedback steers emphasis and wording. It cannot add experience "
                     "you do not have: facts still come from your profile and every "
                     "redraft passes the honesty guard.",
            )
            if st.button("🔁 Redraft with this feedback", key=f"redraft_{r['id']}"):
                if not feedback.strip():
                    st.error("Say what should change first.")
                    st.stop()
                llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
                if not llm.is_up():
                    st.error("Local model is not reachable; start LM Studio's server.")
                    st.stop()
                with st.spinner("Redrafting locally, about a minute..."):
                    try:
                        out = tracker_draft.draft_for_role(
                            conn, r, llm=llm, guidance=feedback.strip()
                        )
                    except Exception as exc:  # noqa: BLE001 - surface any failure
                        st.error(f"Redraft failed: {exc}")
                        st.stop()
                rep = out["cv"]["honesty"]
                st.toast(
                    f"Redrafted: coverage {out['cv']['coverage']['pct']}%, "
                    f"honesty {rep.summary()}"
                )
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
_model_badge()
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

    unscored = [r for r in roles if r["status"] == "Found" and r.get("fit_score") is None]
    if unscored:
        if st.button(f"🎯 Score my fit for {len(unscored)} new role(s)", type="primary"):
            try:
                profile = load_profile()
            except FileNotFoundError:
                st.error("profile.json is needed to score fit (copy profile.example.json).")
                st.stop()
            llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
            scorer = llm if llm.is_up() else None
            if scorer is None:
                st.caption("Local model offline: scoring by keyword overlap only.")
            bar = st.progress(0.0, text="Scoring...")
            triage.score_found(
                conn, profile, scorer,
                progress=lambda i, n: bar.progress(i / n, text=f"Scoring {i} of {n}..."),
            )
            st.rerun()

    f1, f2, f3 = st.columns([3, 1.6, 1])
    selected = f1.multiselect(
        "Filter by status", tracker_db.STATUSES, default=tracker_db.STATUSES
    )
    workstyle = f2.selectbox(
        "Home working", ["Any", "Remote friendly", "Mostly home (4+ days a week)"],
        help="Read from each advert's own text (snippet or fetched JD). Adverts "
             "that do not state a split stay under Any only: unstated is not the "
             "same as not remote.",
    )
    passed = [r for r in roles if (r["status"] or "") == "Pass"]
    if passed and f3.button(f"🧹 Remove {len(passed)} Pass", help="Archive every role "
                            "marked Pass to clear the list (reversible below)"):
        tracker_db.archive_roles(conn, [r["id"] for r in passed])
        st.toast(f"Archived {len(passed)} passed role(s)")
        st.rerun()

    # Roles sitting in the To-draft queue below are hidden here to keep the list
    # clean; they return to the grid once drafted, ready to be marked Applied.
    queued_ids = {
        r["id"] for r in roles
        if (r["status"] or "") in tracker_draft.CV_QUEUE_STATUSES and not r.get("cv_file")
    }
    view = [
        r for r in roles
        if (r["status"] or "") in selected and r["id"] not in queued_ids
    ]
    if workstyle != "Any":
        def _ws_ok(r):
            texts = (r.get("title") or "", r.get("jd_text") or "", r.get("fit_notes") or "")
            days = hunt.home_days(*texts)
            if workstyle.startswith("Mostly"):
                return days is not None and days >= 4
            return days is not None or bool(hunt.workstyle_signals(*texts))
        view = [r for r in view if _ws_ok(r)]
    # Ranked triage: scored roles first, best fit at the top; unscored keep
    # their newest-first order below (the sort is stable).
    view.sort(
        key=lambda r: (r.get("fit_score") is not None, r.get("fit_score") or 0),
        reverse=True,
    )
    # Remember the displayed row ids (in order) so the edit callback maps correctly.
    st.session_state["grid_ids"] = [r["id"] for r in view]

    st.caption(
        f"Showing {len(view)} of {len(roles)} role(s), best fit first once scored; "
        f"roles in the To-draft queue appear below instead. Edit any cell; changes "
        f"save automatically. Tick rows and press Delete to archive them."
    )
    df = pd.DataFrame(view, columns=list(GRID_COLUMNS))
    df["open"] = df["link"]  # compact clickable link beside the title
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
            "open": st.column_config.LinkColumn("🔗", display_text="open", width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=tracker_db.STATUSES),
            "type": st.column_config.SelectboxColumn("Type", options=TYPE_OPTIONS),
            "fit_score": st.column_config.NumberColumn("Fit %", width="small"),
            "fit_reason": st.column_config.TextColumn("Why / why not", width="large"),
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
    _review_drafts(conn, roles)
    _followups_due(conn, due)

_archive_panel(conn)
