"""Reed Jobs API client (Phase C, C1) — free, official, zero-cost job search.

Uses the Reed Jobseeker API (https://www.reed.co.uk/developers). It is free with a
registered key, returns structured JSON, and needs no agent, scraping or paid
service, which fits the tool's local/zero-cost ethos. Auth is HTTP Basic with your
API key as the username and an empty password.

Set your key in the environment (e.g. a gitignored .env, or `export REED_API_KEY=...`):

    REED_API_KEY=your-free-key-from-reed.co.uk/developers

Dependency-light on purpose: stdlib ``urllib`` only, matching ``local_llm``.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
JOB_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"

# Reed exposes a per-job detail endpoint, so the sweep can fetch the full JD.
HAS_JD_DETAIL = True


class ReedError(RuntimeError):
    """Raised when the Reed API is unreachable, rejects the key, or errors."""


@dataclass
class Role:
    """A role from a Reed search, in the tracker's own vocabulary."""

    job_id: str
    title: str
    company: str
    location: str
    salary: str          # human-readable, formatted from min/max + currency
    posted: str          # Reed's posting date, dd/mm/yyyy
    link: str            # canonical Reed job URL
    description: str      # search-result blurb (truncated); full via job_description()
    role_type: str = ""  # "Contract" / "Permanent" / "" (from the search context)


def _key(api_key: str | None) -> str:
    key = api_key or os.environ.get("REED_API_KEY", "")
    if not key:
        raise ReedError(
            "no REED_API_KEY set: get a free key at https://www.reed.co.uk/developers "
            "and export it (or put it in a gitignored .env)"
        )
    return key


def _get(url: str, api_key: str) -> dict:
    """GET a Reed API URL with Basic auth and return the parsed JSON."""
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    req = urllib.request.Request(
        url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ReedError("Reed API key rejected (401): check REED_API_KEY") from exc
        raise ReedError(f"Reed API error {exc.code}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ReedError(f"Reed API unreachable: {exc}") from exc


def _format_salary(item: dict) -> str:
    lo, hi = item.get("minimumSalary"), item.get("maximumSalary")
    sign = "£" if (item.get("currency") or "GBP") == "GBP" else f"{item.get('currency')} "
    if lo and hi:
        return f"{sign}{int(lo):,} to {sign}{int(hi):,}"
    if lo:
        return f"{sign}{int(lo):,}+"
    if hi:
        return f"up to {sign}{int(hi):,}"
    return ""


def _to_role(item: dict, role_type: str) -> Role:
    return Role(
        job_id=str(item.get("jobId", "")),
        title=item.get("jobTitle") or "",
        company=item.get("employerName") or "",
        location=item.get("locationName") or "",
        salary=_format_salary(item),
        posted=item.get("date") or "",
        link=item.get("jobUrl") or "",
        description=item.get("jobDescription") or "",
        role_type=role_type,
    )


def search(
    keywords: str,
    location: str | None = None,
    distance: int = 10,
    minimum_salary: int | None = None,
    permanent: bool | None = None,
    contract: bool | None = None,
    results: int = 50,
    api_key: str | None = None,
) -> list[Role]:
    """Search Reed for ``keywords`` and return the matching roles.

    ``location`` + ``distance`` (miles) narrow geographically; ``minimum_salary``
    sets a floor; ``permanent`` / ``contract`` restrict the employment type. Only the
    given filters are sent, so an unset one is left wide.
    """
    key = _key(api_key)
    params: dict[str, object] = {"keywords": keywords, "resultsToTake": results}
    if location:
        params["locationName"] = location
        params["distanceFromLocation"] = distance
    if minimum_salary:
        params["minimumSalary"] = minimum_salary
    if permanent is not None:
        params["permanent"] = str(bool(permanent)).lower()
    if contract is not None:
        params["contract"] = str(bool(contract)).lower()

    data = _get(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}", key)
    role_type = ""
    if contract and not permanent:
        role_type = "Contract"
    elif permanent and not contract:
        role_type = "Permanent"
    return [_to_role(item, role_type) for item in data.get("results", [])]


def job_description(job_id: str, api_key: str | None = None) -> str:
    """Fetch the full job description for a Reed job id (unlocks JD-from-a-link)."""
    key = _key(api_key)
    data = _get(JOB_URL.format(job_id=urllib.parse.quote(str(job_id))), key)
    return (data.get("jobDescription") or "").strip()
