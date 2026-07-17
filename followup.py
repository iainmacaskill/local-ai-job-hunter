"""Follow-up nudges for applied roles (Phase D).

Once a role has sat at 'Applied' for two working days, it is due a short, polite
follow-up. This module finds the recruiter's address honestly, works out what is
due, and drafts the note; the app renders it with a mailto link that opens the
user's own email client. Nothing is ever sent from here.

Contact addresses come from exactly two places, in trust order:
- parsed out of the advert text itself (provenance 'advert'), or
- typed in by the user (provenance 'manual').
Addresses are never guessed or pattern-generated: a follow-up to a wrong guess is
worse than no follow-up at all.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse

import honesty
import tracker_db

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Addresses that are clearly not a person to follow up with.
_SKIP_PREFIXES = ("noreply", "no-reply", "no_reply", "donotreply", "privacy", "unsubscribe")

WORKING_DAYS_BEFORE_DUE = 2

STYLE = (
    "Write in British English. Do not use em dashes (use commas, colons or "
    "parentheses instead). Do not invent claims, names or details that are not "
    "in the facts provided. Warm and professional, never pushy."
)


# --- contact discovery (honest sources only) ------------------------------- #

def find_advert_email(text: str | None) -> str | None:
    """First plausible contact address published in the advert text, if any."""
    for match in EMAIL_RE.findall(text or ""):
        local = match.split("@")[0].lower()
        if not any(local.startswith(p) for p in _SKIP_PREFIXES):
            return match
    return None


def scan_contacts(conn) -> int:
    """Stamp advert-published emails onto roles missing a contact. Returns count.

    Never touches a role that already has a contact_email (a manual entry always
    wins over a re-parse).
    """
    stamped = 0
    for role in tracker_db.list_roles(conn):
        if role.get("contact_email"):
            continue
        email = find_advert_email(role.get("jd_text"))
        if email:
            tracker_db.update_role(
                conn, role["id"], contact_email=email, contact_source="advert"
            )
            stamped += 1
    return stamped


# --- due-date logic --------------------------------------------------------- #

def add_working_days(day: dt.date, n: int) -> dt.date:
    """``day`` plus ``n`` working days (weekends skipped)."""
    while n > 0:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:  # Mon-Fri
            n -= 1
    return day


def due_date(date_applied: str) -> dt.date | None:
    try:
        applied = dt.date.fromisoformat(str(date_applied)[:10])
    except ValueError:
        return None
    return add_working_days(applied, WORKING_DAYS_BEFORE_DUE)


def list_due(conn, today: dt.date | None = None) -> list[dict]:
    """Applied roles, 2+ working days old, not yet followed up. Oldest first."""
    today = today or dt.date.today()
    due: list[dict] = []
    for role in tracker_db.list_roles(conn):
        if role.get("status") != "Applied" or role.get("followed_up_at"):
            continue
        when = due_date(role.get("date_applied") or "")
        if when and today >= when:
            due.append(role)
    due.sort(key=lambda r: r.get("date_applied") or "")
    return due


# --- drafting (never sending) ----------------------------------------------- #

def template_followup(role: dict, profile: dict | None = None) -> dict:
    """A deterministic short follow-up, used when the local model is not running."""
    name = (profile or {}).get("name", "")
    title = role.get("title") or "the role"
    body = (
        f"Hello,\n\n"
        f"I applied for the {title} position on {role.get('date_applied', 'recently')} "
        f"and wanted to confirm my continued interest. I would welcome the chance to "
        f"discuss how my experience fits what you are looking for.\n\n"
        f"Please let me know if you need anything further from me.\n\n"
        f"Kind regards,\n{name}".rstrip()
    )
    return {"subject": f"Following up on my application: {title}", "body": body,
            "honesty": None}


def draft_followup(role: dict, profile: dict, llm) -> dict:
    """Draft a short follow-up with the local model; verified, with a safe fallback."""
    from local_llm import LocalLLMError  # local import keeps module load light

    facts = (
        f"Candidate name: {profile.get('name', '')}\n"
        f"Role applied for: {role.get('title')}\n"
        f"Organisation: {role.get('company') or '(not stated)'}\n"
        f"Date applied: {role.get('date_applied')}"
    )
    try:
        out = llm.complete_json(
            system=(
                "Write a brief follow-up email for a job application: 2 to 3 short "
                "sentences confirming continued interest and offering to provide "
                "anything further. Use ONLY the facts given. "
                'Return JSON: {"subject": string, "body": string ending "Kind regards" '
                "and the candidate name}. " + STYLE
            ),
            user=facts,
            max_tokens=400,
        )
        body = str(out.get("body") or "").strip()
        subject = str(out.get("subject") or "").strip()
        if not body:
            return template_followup(role, profile)
        report = honesty.verify_text(body, profile, what="follow-up email")
        return {"subject": subject or template_followup(role)["subject"],
                "body": body, "honesty": report}
    except LocalLLMError:
        return template_followup(role, profile)


def mailto_link(email: str, subject: str, body: str) -> str:
    """A mailto URL that opens the user's own email client, prefilled."""
    query = urllib.parse.urlencode({"subject": subject, "body": body},
                                   quote_via=urllib.parse.quote)
    return f"mailto:{email}?{query}"


def mark_followed_up(conn, role_id: int, when: dt.date | None = None) -> None:
    tracker_db.update_role(
        conn, role_id, followed_up_at=(when or dt.date.today()).isoformat()
    )
