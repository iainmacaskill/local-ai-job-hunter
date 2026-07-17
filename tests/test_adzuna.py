"""Cover the Adzuna client (Phase C): mapping, salary, query, errors. Offline."""

import pytest

import adzuna

SEARCH_JSON = {
    "count": 2,
    "results": [
        {
            "id": "4001", "title": "AI Delivery <strong>Manager</strong>",
            "company": {"display_name": "Acme Digital"},
            "location": {"display_name": "London, UK", "area": ["UK", "London"]},
            "salary_min": 90000, "salary_max": 110000, "created": "2026-07-17T09:00:00Z",
            "redirect_url": "https://www.adzuna.co.uk/jobs/details/4001",
            "description": "Lead AI &amp; data delivery.", "contract_type": "permanent",
        },
        {
            "id": "4002", "title": "Programme Manager",
            "company": {"display_name": "Beta Ltd"}, "location": {"display_name": "Remote"},
            "salary_min": 600, "created": "2026-07-16T00:00:00Z",
            "redirect_url": "https://www.adzuna.co.uk/jobs/details/4002",
            "description": "Run programmes.", "contract_type": "contract",
        },
    ],
}


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    def fake_get(url):
        calls["url"] = url
        return calls["response"]

    monkeypatch.setattr(adzuna, "_get", fake_get)
    return calls


def test_search_maps_fields_cleans_html_and_formats_salary(captured):
    captured["response"] = SEARCH_JSON
    roles = adzuna.search("ai delivery manager", app_id="id", app_key="key")
    assert len(roles) == 2
    r = roles[0]
    assert r.job_id == "4001"
    assert r.title == "AI Delivery Manager"          # <strong> stripped
    assert r.company == "Acme Digital" and r.location == "London, UK"
    assert r.salary == "£90,000 to £110,000"
    assert r.posted == "2026-07-17"                  # ISO date part only
    assert r.role_type == "Permanent"                # from contract_type
    assert r.description == "Lead AI & data delivery."   # entity unescaped
    assert roles[1].role_type == "Contract" and roles[1].salary == "£600+"


def test_search_builds_query_with_keys_and_km_distance(captured):
    captured["response"] = {"results": []}
    adzuna.search("scrum master", location="Fareham", distance=15, minimum_salary=550,
                  contract=True, app_id="id", app_key="key")
    url = captured["url"]
    assert "app_id=id" in url and "app_key=key" in url
    assert "what=scrum+master" in url and "where=Fareham" in url
    assert "distance=24" in url                       # 15 miles -> 24 km
    assert "salary_min=550" in url and "contract=1" in url
    assert "permanent" not in url


def test_search_without_credentials_raises(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(adzuna.AdzunaError):
        adzuna.search("anything", app_id="", app_key="")


def test_has_no_jd_detail_endpoint():
    assert adzuna.HAS_JD_DETAIL is False
