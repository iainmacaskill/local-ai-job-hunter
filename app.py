"""Local AI Job Hunter's tracker — a local dashboard of the roles you pursue.

Add roles (with the pasted job description), edit them inline, watch the pipeline
metrics, and draft the CV/cover letter for a role straight from its row using the
local model. Starts empty; nothing leaves your machine. Run with:
  ./.venv/bin/streamlit run app.py
"""

from __future__ import annotations

import base64
import datetime
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import adzuna
import fetch_jd
import followup
import hunt
import local_llm
import profile_builder
import reed
import settings
import source_docs
import tracker_db
import tracker_draft
import triage
from cv_profile import OUTPUT_DIR, load_profile, load_profile_or_empty, save_profile
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
    """Which model the app will use, auto-detected from what LM Studio offers.

    Re-resolved every 10s, so loading a different model in LM Studio (e.g.
    switching between the recommended qwen3.5-9b and qwen3.6-27b) is picked up
    on the next page load/refresh without editing .env or restarting the app.
    CVDRAFTER_LLM_MODEL, if set, pins a specific model and wins when it is
    still offered.
    """
    probe = LocalLLM(base_url=settings.LLM_BASE_URL)
    if not probe.is_up(connect_timeout=0.4):
        return {"state": "offline", "model": None, "available": []}
    # Prefer models actually LOADED (LM Studio's extended API); this is what
    # tells a resident model apart from one merely downloaded, which is what
    # caused auto-detect to pick an unloaded model that then failed to JIT-load.
    loaded = probe.list_loaded_models()
    available = loaded if loaded is not None else probe.list_models()
    pinned = os.environ.get("CVDRAFTER_LLM_MODEL")
    model = local_llm.resolve_model(available, preferred=pinned)
    if model is None:
        return {"state": "none", "model": None, "available": available}
    return {"state": "ready", "model": model, "available": available}


def _resolved_model() -> str:
    """Model id to use for a drafting/scoring call right now."""
    return _model_status()["model"] or settings.LLM_MODEL


def _model_badge() -> None:
    s = _model_status()
    if s["state"] == "offline":
        st.caption(f"🔴 **Local model offline.** Start LM Studio's server "
                   f"({settings.LLM_BASE_URL}) with a model loaded.")
    elif s["state"] == "none":
        st.caption("🟡 **LM Studio is up but no usable model is loaded.** Load "
                   "qwen3.5-9b or qwen3.6-27b in LM Studio.")
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
    with st.expander("🔎 Find roles (Adzuna)"):
        _saved_searches(conn)
        name = st.radio("Source", ["Adzuna"], horizontal=True, key="find_source")
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
    with st.expander("➕ Add a role manually", expanded=empty):
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
                llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=_resolved_model())
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


def _download(col, path, label, key) -> None:
    """A download button with an explicit unique key: filenames can collide
    (two drafted roles can share a title), widget keys must not."""
    if not path:
        return
    p = Path(path)
    if p.exists():
        col.download_button(label, p.read_bytes(), file_name=p.name, key=key)


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
        _download(c1, d.get("cv_path"), "⬇ Screening CV (.docx)", key="last_dl_cv")
        _download(c2, d.get("pdf_path"), "⬇ Interview CV (.pdf)", key="last_dl_pdf")
        _download(c3, d.get("cover_path"), "⬇ Cover letter (.docx)", key="last_dl_cover")


def _autoscroll_to_last_action() -> None:
    """Scroll back to whichever role card the user last clicked a button on.

    Streamlit resets scroll to the top of the page on every rerun (any button
    click anywhere triggers a rerun), which on a long list of role cards looks
    exactly like "the section I was working in closed". Each card has an
    anchor div; this restores position to it via JS in the components iframe,
    which can reach the parent page since it is served same-origin.
    """
    target = st.session_state.pop("scroll_to_role", None)
    if target is None:
        return
    components.html(
        f"""<script>
        const el = window.parent.document.getElementById('role-anchor-{target}');
        if (el) {{ el.scrollIntoView({{block: 'start'}}); }}
        </script>""",
        height=0,
    )


def _draft_queue(conn, roles) -> None:
    """One card per pursued role, kept whole through the application act.

    The reference material (link, fetch, job description) never disappears:
    before drafting the card ends with the drafting controls, and after
    drafting the review block (PDF, downloads, feedback, redraft) is appended
    beneath the same material. The card leaves this section only when the role
    is marked Applied in the grid.
    """
    pursuing = [r for r in roles if (r["status"] or "") in tracker_draft.CV_QUEUE_STATUSES]
    queued = [r for r in pursuing if not r.get("cv_file")]
    drafted = [r for r in pursuing if r.get("cv_file")]
    if not pursuing:
        return
    st.subheader(f"✍️ Drafts ({len(queued)} to draft, {len(drafted)} to review)")
    st.caption(
        "Each role keeps its advert alongside its draft. Draft, review against the "
        "advert, refine and download here; mark the role Applied in the grid once "
        "you have submitted it."
    )
    # Light-blue styling for "Add to Archive" buttons, scoped via the wrapping
    # container's key -> class (st-key-archive_wrap_<id>), so Draft now (primary
    # red) is untouched.
    st.markdown(
        """<style>
        div[class*="st-key-archive_wrap_"] button {
            background-color: #cfe8fb;
            color: #06304f;
            border: 1px solid #9cc9ec;
        }
        div[class*="st-key-archive_wrap_"] button:hover {
            background-color: #b9dcf6;
            color: #06304f;
            border-color: #7fb8e8;
        }
        </style>""",
        unsafe_allow_html=True,
    )
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=_resolved_model())
    up = llm.is_up()
    if not up:
        st.warning(
            f"Local model not reachable at {settings.LLM_BASE_URL}. "
            "Start LM Studio's local server to draft or redraft."
        )
    cv_only = "Screening CV and interview PDF"
    cv_cover = "Screening CV, interview PDF and a cover letter"
    for r in pursuing:
        has_draft = bool(r.get("cv_file"))
        label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
        if has_draft:
            label = f"📄 {label} (drafted, coverage {r.get('coverage')}%)"
        st.markdown(f'<div id="role-anchor-{r["id"]}"></div>', unsafe_allow_html=True)
        # A stable key (not the label, which changes with coverage % after a
        # redraft) so the user's open/closed state survives a rerun instead
        # of resetting to collapsed every time the label text changes.
        with st.expander(label, expanded=not has_draft, key=f"exp_{r['id']}"):
            # --- reference material: always present ------------------------ #
            if r.get("link"):
                st.markdown(f"Link - [{r['link']}]({r['link']})")
                if st.button("⬇ Fetch advert text", key=f"fetch_{r['id']}",
                             help="Fetches the page at the link and drops its "
                                  "readable text into the box below for you to "
                                  "clean up. Some pages cannot be read this way."):
                    st.session_state["scroll_to_role"] = r["id"]
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

            if not has_draft:
                # --- drafting controls ------------------------------------ #
                cover = r["status"] == "Draft CV & Cover Letter"
                choice = st.selectbox(
                    "Will draft", [cv_only, cv_cover], index=1 if cover else 0,
                    key=f"will_{r['id']}",
                    help="Switch before drafting if the application unexpectedly "
                         "asks for a cover letter (or does not need one).",
                )
                dc1, dc2, _dc_spacer = st.columns([1, 1, 4])
                draft_clicked = dc1.button("Draft now", key=f"draft_{r['id']}",
                                           disabled=not up, type="primary")
                with dc2:
                    with st.container(key=f"archive_wrap_{r['id']}"):
                        archive_clicked = st.button(
                            "Add to Archive", key=f"archive_{r['id']}",
                            help="Not applying — archive it (reversible in the "
                                 "Archive panel).",
                        )
                if archive_clicked:
                    tracker_db.archive_roles(conn, [r["id"]])
                    st.toast(f"Archived: {r['title']}")
                    st.rerun()
                if draft_clicked:
                    st.session_state["scroll_to_role"] = r["id"]
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
                        except Exception as exc:  # noqa: BLE001 - surface any failure
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
                        "cover_path": str(out["cover"]["docx"]) if out.get("cover")
                                      else None,
                    }
                    st.rerun()
                continue

            # --- review block, beneath the same reference material --------- #
            st.divider()
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
            _download(c1, str(OUTPUT_DIR / r["cv_file"]), "⬇ Screening CV (.docx)",
                      key=f"dl_cv_{r['id']}")
            if pdf_path and pdf_path.exists():
                _download(c2, str(pdf_path), "⬇ Interview CV (.pdf)",
                          key=f"dl_pdf_{r['id']}")
            if r.get("cover_file"):
                _download(c3, str(OUTPUT_DIR / r["cover_file"]), "⬇ Cover letter (.docx)",
                          key=f"dl_cover_{r['id']}")

            feedback = st.text_area(
                "What should change?", key=f"fb_{r['id']}",
                placeholder="e.g. Lead with the NHS AI programme in the summary, and "
                            "make the governance experience more prominent.",
                help="Feedback steers emphasis and wording. It cannot add experience "
                     "you do not have: facts still come from your profile and every "
                     "redraft passes the honesty guard. Leave it empty to redraft "
                     "against an updated job description alone.",
            )
            if st.button("🔁 Redraft", key=f"redraft_{r['id']}", disabled=not up):
                st.session_state["scroll_to_role"] = r["id"]
                if jd.strip():
                    tracker_db.update_role(conn, r["id"], jd_text=jd.strip())
                role = dict(r)
                role["jd_text"] = jd.strip() or r.get("jd_text")
                with st.spinner("Redrafting locally, about a minute..."):
                    try:
                        out = tracker_draft.draft_for_role(
                            conn, role, llm=llm, guidance=feedback.strip() or None
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
            if st.button("✅ Applied", key=f"applied_{r['id']}",
                         help="Same as setting Applied in the grid: stamps today as "
                              "the application date and starts the follow-up clock. "
                              "The card then moves on from this section."):
                st.session_state["scroll_to_role"] = r["id"]
                fields = {"status": "Applied"}
                if not r.get("date_applied"):
                    fields["date_applied"] = datetime.date.today().isoformat()
                tracker_db.update_role(conn, r["id"], **fields)
                st.toast(f"Marked Applied: {r['title']}")
                st.rerun()
            with st.container(key=f"archive_wrap_post_{r['id']}"):
                if st.button("Add to Archive", key=f"archive_post_{r['id']}",
                             help="Decided not to pursue this one after drafting — "
                                  "archive it (reversible in the Archive panel)."):
                    tracker_db.archive_roles(conn, [r["id"]])
                    st.toast(f"Archived: {r['title']}")
                    st.rerun()

    _autoscroll_to_last_action()


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
        hc1, hc2, hc3, hc4 = st.columns([4, 1.4, 1, 1])
        hc1.caption("Role")
        hc2.caption("Archived date")
        hc3.caption("Applied for")
        for r in archived:
            c1, c2, c3, c4 = st.columns([4, 1.4, 1, 1])
            label = f"{r['title']}, {r['company']}" if r.get("company") else r["title"]
            c1.write(f"{label} ({r.get('status')})")
            c2.write(r.get("archived_at") or "—")
            c3.write("✅" if r.get("date_applied") else "❌")
            if c4.button("Restore", key=f"restore_{r['id']}"):
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

# Make the two tabs read as clearly separate pages: bigger/bolder labels, a
# thick coloured underline + coloured label on the active one, gap between
# tabs. No hardcoded backgrounds, so it holds up in both light and dark theme.
st.markdown(
    """<style>
    div[data-testid="stTabs"] button[data-baseweb="tab"] {
        gap: 0.5rem;
        margin-right: 12px;
        padding: 0.85rem 0.25rem;
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"] p {
        font-size: 1.15rem;
        font-weight: 700;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] p {
        color: #ff4b4b;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
        background-color: #ff4b4b;
        height: 4px;
        border-radius: 2px;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-border"] {
        display: none;
    }
    </style>""",
    unsafe_allow_html=True,
)
tab_search, tab_applied, tab_source = st.tabs(
    ["📋 Search & Apply", "✅ Applied for Roles", "📚 Source CV"]
)

with tab_search:
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
                llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=_resolved_model())
                scorer = llm if llm.is_up() else None
                if scorer is None:
                    st.caption("Local model offline: scoring by keyword overlap only.")
                bar = st.progress(0.0, text="Scoring...")
                triage.score_found(
                    conn, profile, scorer,
                    progress=lambda i, n: bar.progress(i / n, text=f"Scoring {i} of {n}..."),
                )
                st.rerun()

        f1, f2 = st.columns([3, 1.6])
        selected = f1.multiselect(
            "Filter by status", tracker_db.STATUSES, default=tracker_db.STATUSES
        )
        workstyle = f2.selectbox(
            "Home working", ["Any", "Remote friendly", "Mostly home (4+ days a week)"],
            help="Read from each advert's own text (snippet or fetched JD). Adverts "
                 "that do not state a split stay under Any only: unstated is not the "
                 "same as not remote.",
        )

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
        b1, b2, _spacer = st.columns([1, 1, 2])
        passed = [r for r in roles if (r["status"] or "") == "Pass"]
        if passed and b1.button(f"🧹 Remove {len(passed)} Pass",
                                help="Archive every role marked Pass to clear the list "
                                     "(reversible below)"):
            tracker_db.archive_roles(conn, [r["id"] for r in passed])
            st.toast(f"Archived {len(passed)} passed role(s)")
            st.rerun()
        if b2.button(
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

with tab_applied:
    applied_roles = [r for r in roles if (r.get("status") or "") == "Applied"]
    st.caption(f"{len(applied_roles)} role(s) marked Applied.")
    if not applied_roles:
        st.info("No roles marked Applied yet.")
    else:
        adf = pd.DataFrame(applied_roles)
        adf["open"] = adf["link"]
        adf = adf[["id", "status", "title", "open", "type", "rate", "location",
                   "company", "date_found", "date_applied", "link"]]
        st.dataframe(
            adf,
            hide_index=True,
            width="stretch",
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "title": st.column_config.TextColumn("Title"),
                "open": st.column_config.LinkColumn("Link to", display_text="open",
                                                    width="small"),
                "type": st.column_config.TextColumn("Type", width="small"),
                "rate": st.column_config.TextColumn("Rate"),
                "location": st.column_config.TextColumn("Location"),
                "company": st.column_config.TextColumn("Company"),
                "date_found": st.column_config.TextColumn("Found", width="small"),
                "date_applied": st.column_config.TextColumn("Date applied", width="small"),
                "link": st.column_config.LinkColumn("Link"),
            },
        )

@st.cache_data(show_spinner=False)
def _extract_cached(path_str: str, mtime: float) -> str:
    """Cached per (path, mtime): a rerun does not re-parse an unchanged file.

    Streamlit reruns the whole script on any interaction anywhere in the app,
    so without this, every saved source (PDFs especially) gets re-parsed on
    every click, which is the actual cause of the tab greying out, not just
    the upload step itself.
    """
    return source_docs.extract_text(Path(path_str))


def _sources_with_progress() -> list[dict]:
    """Saved sources with their extracted text, showing real progress on any
    file not yet cached (first read of a new/changed file only)."""
    paths = source_docs.list_source_paths()
    if not paths:
        return []
    out = []
    bar = st.progress(0.0, text=f"Reading 0 of {len(paths)} source file(s)...")
    for i, path in enumerate(paths, start=1):
        text = _extract_cached(str(path), path.stat().st_mtime)
        out.append({"path": path, "name": path.name, "chars": len(text), "text": text})
        bar.progress(i / len(paths), text=f"Reading {i} of {len(paths)} source file(s)...")
    bar.empty()
    return out


with tab_source:
    st.caption(
        "Upload old CVs, LinkedIn exports or notes below. More material than you "
        "strictly need is fine on purpose: extraction only pulls facts that are "
        "literally stated in what you upload, so extra source text just gives it "
        "more true detail to draw from, never anything to invent."
    )

    uploads = st.file_uploader(
        "Add source CVs (.docx, .pdf, .txt)", type=["docx", "pdf", "txt"],
        accept_multiple_files=True, key="source_uploader",
    )
    if uploads:
        # file_uploader keeps returning the same files on every rerun (it does
        # not clear itself just because we rerun elsewhere), so track what has
        # already been saved by (name, size) or this would resave forever.
        saved_ids = st.session_state.setdefault("source_uploaded_ids", set())
        new_files = [f for f in uploads if (f.name, f.size) not in saved_ids]
        if new_files:
            bar = st.progress(0.0, text=f"Saving 0 of {len(new_files)} file(s)...")
            for i, f in enumerate(new_files, start=1):
                source_docs.save_upload(f.name, f.getvalue())
                saved_ids.add((f.name, f.size))
                bar.progress(i / len(new_files), text=f"Saving {i} of {len(new_files)} file(s)...")
            st.toast(f"Saved {len(new_files)} file(s)")
            st.rerun()

    sources = _sources_with_progress()
    if sources:
        st.markdown(f"**{len(sources)} source document(s)**")
        for s in sources:
            sc1, sc2, sc3 = st.columns([4, 1, 1])
            sc1.write(s["name"])
            sc2.caption(f"{s['chars']:,} chars")
            if sc3.button("🗑", key=f"del_src_{s['name']}"):
                source_docs.delete_source(s["path"])
                st.rerun()
    else:
        st.info("No source documents yet. Upload at least one to extract from.")

    st.divider()
    st.subheader("Extract profile content")
    source_llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=_resolved_model())
    source_up = source_llm.is_up()
    if not source_up:
        st.warning("Local model not reachable; start LM Studio's server to extract.")
    if st.button("🔍 Extract from uploaded sources", type="primary",
                 disabled=not source_up or not sources):
        with st.spinner("Reading source documents locally..."):
            extracted = profile_builder.extract_profile(
                source_docs.combined_text(), source_llm
            )
        if not extracted or not extracted.get("jobs"):
            st.warning("Nothing extractable found in the uploaded sources.")
        else:
            st.session_state["profile_draft"] = extracted
        st.rerun()

    profile_draft = st.session_state.get("profile_draft")
    if profile_draft:
        st.success(
            f"Extracted {len(profile_draft.get('jobs', []))} role(s), "
            f"{len(profile_draft.get('competencies', []))} competencies, "
            f"{len(profile_draft.get('achievements', []))} achievement(s)."
        )
        st.json(profile_draft, expanded=False)
        st.caption(
            "Review above. Merging never removes anything already in your "
            "profile: it only adds new roles and new bullets not already there."
        )
        if st.button("✅ Merge into profile.json", type="primary", key="merge_draft"):
            merged = profile_builder.merge_profile(load_profile_or_empty(), profile_draft)
            save_profile(merged)
            st.session_state.pop("profile_draft", None)
            st.toast("profile.json updated")
            st.rerun()

    st.divider()
    st.subheader("Interview: fill the gaps")
    current_profile = load_profile_or_empty()
    if not current_profile:
        st.info("Extract from a source CV first (above), then come back to fill gaps.")
    else:
        if st.button("💬 Find what's missing and ask", disabled=not source_up):
            with st.spinner("Reviewing your profile locally..."):
                st.session_state["gap_qs"] = profile_builder.gap_questions(
                    current_profile, source_llm
                )
            st.rerun()

        gap_qs = st.session_state.get("gap_qs")
        if gap_qs:
            for gi, gq in enumerate(gap_qs):
                st.text_input(gq["question"], key=f"gapans_{gi}")
            if st.button("Save my answers", type="primary"):
                fresh_profile = load_profile_or_empty()
                saved_n = 0
                for gi, gq in enumerate(gap_qs):
                    answer = st.session_state.get(f"gapans_{gi}", "").strip()
                    if not answer:
                        continue
                    target = gq["target"]
                    if target == "achievements":
                        fresh_profile.setdefault("achievements", []).append(answer)
                        saved_n += 1
                    elif isinstance(target, int) and target < len(fresh_profile.get("jobs", [])):
                        fresh_profile["jobs"][target].setdefault("bullets", []).append(answer)
                        saved_n += 1
                if saved_n:
                    save_profile(fresh_profile)
                    st.toast(f"Added {saved_n} answer(s) to profile.json")
                st.session_state.pop("gap_qs", None)
                st.rerun()
        elif gap_qs is not None:
            st.success("No gaps found — profile looks solid.")
