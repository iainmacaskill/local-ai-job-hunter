"""Adzuna Jobs API client (Phase C) — a second free, official job source.

Adzuna (https://developer.adzuna.com) is free with an app id + key, returns JSON,
and like Reed needs no agent, scraping or paid service. It shares reed.py's ``Role``
shape so ``hunt.sweep`` can pull from either source. One difference: Adzuna's free
API returns a description *snippet*, not the full advert (no detail endpoint), so
``HAS_JD_DETAIL`` is False — paste the full JD before drafting if you need it.

Set both keys in the environment (free at https://developer.adzuna.com):

    ADZUNA_APP_ID=...
    ADZUNA_APP_KEY=...

Dependency-light on purpose: stdlib ``urllib`` only, matching ``reed``.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from reed import Role  # shared shape across sources

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
HAS_JD_DETAIL = False           # no free per-job detail endpoint; only a snippet
_MILES_TO_KM = 1.60934


class AdzunaError(RuntimeError):
    """Raised when the Adzuna API is unreachable, rejects the keys, or errors."""


def _creds(app_id: str | None, app_key: str | None) -> tuple[str, str]:
    aid = app_id or os.environ.get("ADZUNA_APP_ID", "")
    key = app_key or os.environ.get("ADZUNA_APP_KEY", "")
    if not (aid and key):
        raise AdzunaError(
            "no Adzuna credentials: get a free app id + key at "
            "https://developer.adzuna.com and set ADZUNA_APP_ID and ADZUNA_APP_KEY"
        )
    return aid, key


def _get(url: str) -> dict:
    """GET an Adzuna API URL and return the parsed JSON (URL carries the keys)."""
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not echo the URL: it carries the app key.
        if exc.code in (401, 403):
            raise AdzunaError("Adzuna keys rejected: check ADZUNA_APP_ID/KEY") from exc
        raise AdzunaError(f"Adzuna API error {exc.code}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AdzunaError(f"Adzuna API unreachable: {exc}") from exc


def _clean(text: str | None) -> str:
    """Strip the light HTML markup Adzuna puts in titles/descriptions."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _format_salary(item: dict) -> str:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo and hi:
        return f"£{int(lo):,} to £{int(hi):,}"
    if lo:
        return f"£{int(lo):,}+"
    if hi:
        return f"up to £{int(hi):,}"
    return ""


def _to_role(item: dict, role_type: str) -> Role:
    # Prefer Adzuna's own contract_type; fall back to the search context.
    resolved = {"contract": "Contract", "permanent": "Permanent"}.get(
        item.get("contract_type"), role_type
    )
    return Role(
        job_id=str(item.get("id", "")),
        title=_clean(item.get("title")),
        company=(item.get("company") or {}).get("display_name", ""),
        location=(item.get("location") or {}).get("display_name", ""),
        salary=_format_salary(item),
        posted=(item.get("created") or "")[:10],   # ISO date part
        link=item.get("redirect_url") or "",
        description=_clean(item.get("description")),
        role_type=resolved,
    )


def search(
    keywords: str,
    location: str | None = None,
    distance: int = 10,
    minimum_salary: int | None = None,
    permanent: bool | None = None,
    contract: bool | None = None,
    results: int = 50,
    country: str = "gb",
    app_id: str | None = None,
    app_key: str | None = None,
) -> list[Role]:
    """Search Adzuna for ``keywords`` and return matching roles (same shape as reed).

    ``distance`` is given in miles (matching reed) and converted to Adzuna's km.
    Only the filters you set are sent.
    """
    aid, key = _creds(app_id, app_key)
    params: dict[str, object] = {
        "app_id": aid,
        "app_key": key,
        "what": keywords,
        "results_per_page": min(results, 50),
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
        params["distance"] = round(distance * _MILES_TO_KM)
    if minimum_salary:
        params["salary_min"] = minimum_salary
    if permanent:
        params["permanent"] = 1
    if contract:
        params["contract"] = 1

    url = SEARCH_URL.format(country=country, page=1) + "?" + urllib.parse.urlencode(params)
    data = _get(url)
    role_type = ""
    if contract and not permanent:
        role_type = "Contract"
    elif permanent and not contract:
        role_type = "Permanent"
    return [_to_role(item, role_type) for item in data.get("results", [])]
