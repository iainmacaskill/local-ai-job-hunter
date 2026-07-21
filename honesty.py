"""S3: honesty guard for locally-drafted CV payloads.

Deterministic verification of a drafted screening payload against profile.json,
the single source of truth. It can't read minds, so it guarantees what a machine
CAN check and flags the rest for the human:

  ERRORS (block):    an employer, role title or date not in profile.json
                     (invented, renamed or reordered experience)
  WARNINGS (review): a figure in a bullet or summary that appears nowhere in the
                     profile (a likely fabricated metric); em dashes (house style)

What it deliberately does NOT do: verify qualitative claims semantically. A
weaker local model can still phrase an unsupported soft claim, so human review
stays the final gate. Structure + figures + style are the machine-checkable net.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EM_DASH = "—"

_STOP = {"and", "the", "of", "for", "with", "to", "in", "on", "an", "a", "or"}

_WORDNUM = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}

_NUM_RE = re.compile(r"£?\d[\d,]*\.?\d*\s?(?:%|k|m|bn|\+|million|billion)?", re.I)


@dataclass
class HonestyReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.errors:
            head = f"FAIL: {len(self.errors)} error(s)"
        elif self.warnings:
            head = f"review: {len(self.warnings)} warning(s)"
        else:
            head = "clean"
        return head


class HonestyError(RuntimeError):
    """Raised when a payload fails the block-tier structural check.

    Carries the full report so a caller can surface the offending errors (an
    invented, renamed or reordered employer/title/date) rather than emit a CV
    that misrepresents the candidate's history.
    """

    def __init__(self, report: "HonestyReport") -> None:
        self.report = report
        detail = "; ".join(report.errors) or report.summary()
        super().__init__(f"honesty guard blocked render: {detail}")


def _key(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _norm_num(tok: str) -> str:
    t = tok.strip().lower().replace(",", "").replace(" ", "").replace("£", "")
    return t.replace("million", "m").replace("billion", "bn")


def _numbers(text: str | None) -> set[str]:
    text = text or ""
    out = {_norm_num(m) for m in _NUM_RE.findall(text)}
    for word, digit in _WORDNUM.items():
        if re.search(rf"\b{word}\b", text, re.I):
            out.add(digit)
    return {x for x in out if x and any(c.isdigit() for c in x)}


def _profile_numbers(profile: dict) -> set[str]:
    allowed: set[str] = set()
    for job in profile.get("jobs", []):
        for bullet in job.get("bullets", []):
            allowed |= _numbers(bullet)
    for ach in profile.get("achievements", []):
        allowed |= _numbers(ach)
    allowed |= _numbers(" ".join(profile.get("competencies", [])))
    allowed |= _numbers(profile.get("summary", ""))
    return allowed


def _all_prose(payload: dict) -> str:
    parts = [payload.get("summary", ""), *payload.get("core_skills", [])]
    for exp in payload.get("experience", []):
        if exp.get("intro"):
            parts.append(exp["intro"])
        parts.extend(exp.get("bullets", []))
    return "\n".join(str(p) for p in parts)


def _words(text: str | None) -> set[str]:
    """Content words (len >= 2, stopwords dropped) for coarse grounding checks."""
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(w) >= 2 and w not in _STOP
    }


def _profile_vocab(profile: dict) -> set[str]:
    """Every content word the profile actually contains (the source of truth)."""
    vocab: set[str] = set()
    for comp in profile.get("competencies", []):
        vocab |= _words(comp)
    for job in profile.get("jobs", []):
        vocab |= _words(job.get("title"))
        for bullet in job.get("bullets", []):
            vocab |= _words(bullet)
    for ach in profile.get("achievements", []):
        vocab |= _words(ach)
    vocab |= _words(profile.get("summary", ""))
    vocab |= _words(profile.get("certifications", ""))
    vocab |= _words(profile.get("education", ""))
    return vocab


def verify(payload: dict, profile: dict) -> HonestyReport:
    """Check a drafted payload against the profile. Never mutates either."""
    errors: list[str] = []
    warnings: list[str] = []

    jobs_by_company = {_key(j.get("company")): j for j in profile.get("jobs", [])}

    # 1. structure — employers / titles / dates must come from the profile
    for exp in payload.get("experience", []):
        job = jobs_by_company.get(_key(exp.get("company")))
        if job is None:
            errors.append(f"employer not in profile: {exp.get('company')!r}")
            continue
        if (exp.get("title") or "").strip() != (job.get("title") or "").strip():
            errors.append(
                f"title altered for {job['company']}: "
                f"{exp.get('title')!r} != {job.get('title')!r}"
            )
        if (exp.get("dates") or "").strip() != (job.get("dates") or "").strip():
            errors.append(
                f"dates altered for {job['company']}: "
                f"{exp.get('dates')!r} != {job.get('dates')!r}"
            )

    # 2. figures — any number not found anywhere in the profile is suspect.
    # Scans every model-authored line, including a role's optional intro.
    allowed = _profile_numbers(profile)
    for exp in payload.get("experience", []):
        lines = list(exp.get("bullets", []))
        if exp.get("intro"):
            lines.append(exp["intro"])
        for line in lines:
            for num in _numbers(line) - allowed:
                warnings.append(f"unverified figure {num!r} in {exp.get('company')} line")
    for num in _numbers(payload.get("summary", "")) - allowed:
        warnings.append(f"unverified figure {num!r} in summary")

    # 3. core skills — each mirrored advert term should share vocabulary with the
    # profile; one that shares none is a likely fabricated skill (JD-injected).
    vocab = _profile_vocab(profile)
    for skill in payload.get("core_skills", []):
        toks = _words(skill)
        if toks and not (toks & vocab):
            warnings.append(f"core skill not grounded in profile: {str(skill)!r}")

    # 4. house style
    if EM_DASH in _all_prose(payload):
        warnings.append("em dash present (house style: use none)")

    return HonestyReport(ok=not errors, errors=errors, warnings=warnings)


def verify_text(text: str, profile: dict, what: str = "text") -> HonestyReport:
    """Guard free prose (e.g. a cover letter) that has no structure to verify.

    Only figure and style checks apply: any number not present anywhere in the
    profile is flagged for review, as are em dashes. Warnings only, never a block.
    """
    warnings: list[str] = []
    allowed = _profile_numbers(profile)
    for num in _numbers(text) - allowed:
        warnings.append(f"unverified figure {num!r} in {what}")
    if EM_DASH in (text or ""):
        warnings.append(f"em dash present in {what} (house style: use none)")
    return HonestyReport(ok=True, warnings=warnings)
