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
    fit_score    INTEGER,                      -- triage: 0-100 fit vs the profile
    fit_reason   TEXT,                         -- triage: one-line why / why not
    archived     INTEGER NOT NULL DEFAULT 0,   -- 1 = hidden from the board (reversible)
    archived_at  TEXT,                         -- date last archived; cleared on restore
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_roles_status ON roles(status);

-- Saved hunt criteria, so a repeat sweep is one click (Phase D).
CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL DEFAULT 'Adzuna',  -- 'Adzuna' or 'Reed'
    keywords    TEXT NOT NULL,                    -- search terms, one per line
    location    TEXT,
    distance    INTEGER,                          -- miles
    min_salary  INTEGER,
    role_type   TEXT,                             -- '', 'Contract', 'Permanent'
    last_run_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns a caller may set/update. id and timestamps are managed here, not by callers.
_FIELDS = (
    "date_found", "title", "company", "type", "rate", "location", "link",
    "jd_text", "fit_notes", "status", "cv_file", "cover_file", "coverage",
    "date_applied", "outcome", "source_job_id",
    "contact_email", "contact_source", "followed_up_at", "fit_score", "fit_reason",
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
        ("archived", "INTEGER NOT NULL DEFAULT 0"), ("archived_at", "TEXT"),
        ("fit_score", "INTEGER"), ("fit_reason", "TEXT"),
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


def list_roles(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    """Roles newest first; archived ones are hidden unless asked for."""
    where = "" if include_archived else "WHERE archived = 0"
    rows = conn.execute(f"SELECT * FROM roles {where} ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def list_archived(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM roles WHERE archived = 1 ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def _set_archived(conn: sqlite3.Connection, role_ids, value: int) -> int:
    ids = [int(i) for i in role_ids]
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    stamp = "date('now')" if value else "NULL"
    cur = conn.execute(
        f"UPDATE roles SET archived = ?, archived_at = {stamp}, "
        f"updated_at = datetime('now') WHERE id IN ({marks})",
        [value, *ids],
    )
    conn.commit()
    return cur.rowcount


def archive_roles(conn: sqlite3.Connection, role_ids) -> int:
    """Hide roles from the board (reversible). Returns how many were archived."""
    return _set_archived(conn, role_ids, 1)


def restore_roles(conn: sqlite3.Connection, role_ids) -> int:
    """Bring archived roles back onto the board."""
    return _set_archived(conn, role_ids, 0)


def delete_roles(conn: sqlite3.Connection, role_ids) -> int:
    """Permanently remove roles. Only the Archive panel calls this, after archiving."""
    ids = [int(i) for i in role_ids]
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM roles WHERE id IN ({marks})", ids)
    conn.commit()
    return cur.rowcount


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
        i = int(idx)
        if not (0 <= i < len(ordered_ids)):  # stale/out-of-range edit index: skip, don't crash the save
            continue
        role_id = ordered_ids[i]
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


def save_search(
    conn: sqlite3.Connection, name: str, *, keywords: str, source: str = "Adzuna",
    location: str | None = None, distance: int | None = None,
    min_salary: int | None = None, role_type: str | None = None,
) -> int:
    """Create or update (by name) a saved search. Returns its id."""
    if not (name or "").strip():
        raise ValueError("a saved search needs a name")
    if not (keywords or "").strip():
        raise ValueError("a saved search needs at least one keyword")
    conn.execute(
        """INSERT INTO searches (name, source, keywords, location, distance,
                                 min_salary, role_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
             source = excluded.source, keywords = excluded.keywords,
             location = excluded.location, distance = excluded.distance,
             min_salary = excluded.min_salary, role_type = excluded.role_type""",
        (name.strip(), source, keywords.strip(), location, distance, min_salary, role_type),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM searches WHERE name = ?", (name.strip(),)).fetchone()
    return int(row[0])


def list_searches(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM searches ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_search(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM searches WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def delete_search(conn: sqlite3.Connection, search_id: int) -> None:
    conn.execute("DELETE FROM searches WHERE id = ?", (int(search_id),))
    conn.commit()


def mark_search_run(conn: sqlite3.Connection, search_id: int) -> None:
    conn.execute(
        "UPDATE searches SET last_run_at = datetime('now') WHERE id = ?", (int(search_id),)
    )
    conn.commit()


def archive_editor_deletions(conn: sqlite3.Connection, ordered_ids, deleted_rows) -> int:
    """Archive the rows the user removed from the grid (never a hard delete).

    ``deleted_rows`` is the list of row indices Streamlit's ``st.data_editor``
    reports (in the displayed order that ``ordered_ids`` mirrors). Returns how
    many roles were archived.
    """
    ids = [ordered_ids[int(i)] for i in (deleted_rows or []) if int(i) < len(ordered_ids)]
    return archive_roles(conn, ids)
