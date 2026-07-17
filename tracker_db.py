"""Local SQLite store for the roles you are pursuing (Phase B, story B1).

Deliberately slim: a single ``roles`` table and small CRUD helpers, no ORM. It
holds the roles you enter by hand and, later, the drafting outcomes (CV filename,
coverage) stamped back onto each row by the drafter. The sweep/contact/follow-up
machinery from the companion tracker is intentionally out of scope until Phase C.

The database lives beside this file as ``tracker.db`` (gitignored) unless
``CVDRAFTER_DB`` overrides it — nothing leaves your machine.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CVDRAFTER_DB", REPO / "tracker.db"))

# Search-and-application statuses, in order. This tool tracks the front of the funnel
# (find, decide, draft, apply) and hands off after "Applied": interviews, offers and
# outcomes are a human relationship with the recruiter, managed off-tool.
# "Draft CV" / "Draft CV & Cover Letter" also trigger drafting: while a role has one of
# these and no CV yet it sits in the "to draft" queue; drafting fills in the CV file and
# the role stays put until you move it to "Applied".
STATUSES = ["Found", "Pass", "Draft CV", "Draft CV & Cover Letter", "Applied"]

# The two statuses that mean "pursuing this role, draft its documents".
DRAFT_STATUSES = ("Draft CV", "Draft CV & Cover Letter")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date_found   TEXT NOT NULL DEFAULT (date('now')),
    title        TEXT NOT NULL,
    company      TEXT,
    type         TEXT,                       -- Contract / Permanent
    rate         TEXT,
    location     TEXT,
    link         TEXT,
    jd_text      TEXT,                        -- pasted advert, so B4 can draft from the row
    fit_notes    TEXT,
    status       TEXT NOT NULL DEFAULT 'Found',
    cv_file      TEXT,                        -- last drafted screening CV filename
    cover_file   TEXT,                        -- last drafted cover letter filename
    coverage     INTEGER,                     -- last draft's keyword coverage %
    date_applied TEXT,
    outcome      TEXT,
    source_job_id TEXT,                        -- Reed job id, for sweep dedupe (C2)
    contact_email TEXT,                        -- recruiter contact for the follow-up
    contact_source TEXT,                       -- provenance: 'advert' (parsed) or 'manual'
    followed_up_at TEXT,                       -- date the user sent their follow-up
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_roles_status ON roles(status);
"""

# Columns a caller may set/update. id and timestamps are managed here, not by callers.
_FIELDS = (
    "date_found", "title", "company", "type", "rate", "location", "link",
    "jd_text", "fit_notes", "status", "cv_file", "cover_file", "coverage",
    "date_applied", "outcome", "source_job_id",
    "contact_email", "contact_source", "followed_up_at",
)


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    # check_same_thread=False: Streamlit reruns the script on different threads and
    # reuses one cached connection, so the connection must not be pinned to its
    # creating thread. Safe here — this is a single-user local app, and WAL plus
    # busy_timeout below serialise the occasional concurrent write.
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL lets the Streamlit app keep reading while a draft writes, rather than
    # taking a whole-file lock; busy_timeout makes a writer wait its turn.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add any columns a newer version introduced to an already-existing table."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(roles)")}
    new_columns = [
        ("source_job_id", "TEXT"),
        ("contact_email", "TEXT"), ("contact_source", "TEXT"), ("followed_up_at", "TEXT"),
    ]
    for col, ddl in new_columns:
        if col not in have:
            conn.execute(f"ALTER TABLE roles ADD COLUMN {col} {ddl}")


# Statuses from the old (pre-slim) pipeline mapped onto the current set, so a DB from
# an earlier version never holds a value that has since been retired.
_LEGACY_STATUS = {
    "CV Drafted": "Draft CV",   # it was drafted; keep it in the pursuing state
    "Interview": "Applied",
    "Offer": "Applied",
    "Rejected": "Pass",
    "Expired": "Pass",
}


def _migrate_statuses(conn: sqlite3.Connection) -> None:
    for old, new in _LEGACY_STATUS.items():
        conn.execute("UPDATE roles SET status = ? WHERE status = ?", (new, old))


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_columns(conn)  # migrate DBs created before a column was added
    _migrate_statuses(conn)  # map any retired status values onto the current set
    conn.execute("CREATE INDEX IF NOT EXISTS idx_roles_source_job_id ON roles(source_job_id)")
    conn.commit()


def add_role(conn: sqlite3.Connection, **fields) -> int:
    """Insert a role. Only known columns are accepted; ``title`` is required."""
    if not (fields.get("title") or "").strip():
        raise ValueError("a role needs a title")
    cols = [f for f in _FIELDS if f in fields]
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO roles ({', '.join(cols)}) VALUES ({placeholders})",
        [fields[c] for c in cols],
    )
    conn.commit()
    return int(cur.lastrowid)


def list_roles(conn: sqlite3.Connection) -> list[dict]:
    """All roles, newest first."""
    rows = conn.execute("SELECT * FROM roles ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_role(conn: sqlite3.Connection, role_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    return dict(row) if row else None


def update_role(conn: sqlite3.Connection, role_id: int, **fields) -> None:
    """Update the given known columns on a role and bump ``updated_at``."""
    cols = [f for f in _FIELDS if f in fields]
    if not cols:
        return
    assignments = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols]
    conn.execute(
        f"UPDATE roles SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        [*values, role_id],
    )
    conn.commit()


def summarise(roles) -> dict:
    """Dashboard counts for the search funnel: to-triage, pursuing, applied, passed."""
    statuses = [(r.get("status") or "") for r in roles]
    return {
        "total": len(statuses),
        "to_triage": sum(s == "Found" for s in statuses),
        "pursuing": sum(s in DRAFT_STATUSES for s in statuses),
        "applied": sum(s == "Applied" for s in statuses),
        "passed": sum(s == "Pass" for s in statuses),
    }


def apply_editor_changes(conn: sqlite3.Connection, ordered_ids, edited_rows) -> int:
    """Persist inline-grid edits back to the roles.

    ``ordered_ids`` is the list of role ids exactly as displayed (same order as the
    grid rows, so this stays correct even when the grid is filtered), and
    ``edited_rows`` maps a row index to ``{column: new_value}`` (the shape Streamlit's
    ``st.data_editor`` stores in session state). Unknown columns are ignored. Returns
    how many roles were updated.
    """
    updated = 0
    for idx, changes in (edited_rows or {}).items():
        role_id = ordered_ids[int(idx)]
        clean = {k: v for k, v in changes.items() if k in _FIELDS}
        # Moving a role to Applied stamps date_applied (unless set), so the
        # follow-up due date works without the user typing dates by hand.
        if clean.get("status") == "Applied" and "date_applied" not in clean:
            current = get_role(conn, int(role_id)) or {}
            if not current.get("date_applied"):
                clean["date_applied"] = datetime.date.today().isoformat()
        if clean:
            update_role(conn, int(role_id), **clean)
            updated += 1
    return updated
