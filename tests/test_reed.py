"""Cover the Reed client (C1): query construction, field mapping, errors. Offline."""

import pytest

import reed

SEARCH_JSON = {
    "totalResults": 2,
    "results": [
        {
            "jobId": 54501111, "employerName": "Acme Digital", "jobTitle": "AI Delivery Manager",
            "locationName": "London", "minimumSalary": 600, "maximumSalary": 700,
            "currency": "GBP", "date": "17/07/2026",
            "jobDescription": "Lead AI and data delivery.",
            "jobUrl": "https://www.reed.co.uk/jobs/ai-delivery-manager/54501111",
        },
        {
            "jobId": 54502222, "employerName": "Beta Ltd", "jobTitle": "Programme Manager",
            "locationName": "Remote", "minimumSalary": 90000, "maximumSalary": 110000,
            "currency": "GBP", "date": "16/07/2026", "jobDescription": "Run programmes.",
            "jobUrl": "https://www.reed.co.uk/jobs/programme-manager/54502222",
        },
    ],
}


@pytest.fixture
def captured(monkeypatch):
    """Patch reed._get to record the URL and return canned data."""
    calls = {}

    def fake_get(url, api_key):
        calls["url"] = url
        calls["api_key"] = api_key
        return calls["response"]

    monkeypatch.setattr(reed, "_get", fake_get)
    return calls


def test_search_maps_fields_and_formats_salary(captured):
    captured["response"] = SEARCH_JSON
    roles = reed.search("ai delivery manager", location="London", contract=True, api_key="k")
    assert len(roles) == 2
    r = roles[0]
    assert r.job_id == "54501111" and r.title == "AI Delivery Manager"
    assert r.company == "Acme Digital" and r.location == "London"
    assert r.salary == "£600 to £700"
    assert r.link.endswith("/54501111")
    assert r.role_type == "Contract"          # contract=True, permanent unset
    assert roles[1].salary == "£90,000 to £110,000"


def test_search_builds_query_with_only_given_filters(captured):
    captured["response"] = {"results": []}
    reed.search("scrum master", location="Fareham", distance=15, minimum_salary=550,
                contract=True, api_key="k")
    url = captured["url"]
    assert url.startswith(reed.SEARCH_URL + "?")
    assert "keywords=scrum+master" in url
    assert "locationName=Fareham" in url and "distanceFromLocation=15" in url
    assert "minimumSalary=550" in url and "contract=true" in url
    assert "permanent" not in url            # unset filter is not sent


def test_search_without_key_raises(monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)   # no key anywhere
    with pytest.raises(reed.ReedError):
        reed.search("anything", api_key="")


def test_job_description_returns_full_text(captured):
    captured["response"] = {"jobDescription": "  Full JD body.  "}
    assert reed.job_description("54501111", api_key="k") == "Full JD body."
    assert "/jobs/54501111" in captured["url"]


def test_permanent_only_search_marks_type(captured):
    captured["response"] = SEARCH_JSON
    roles = reed.search("programme manager", permanent=True, api_key="k")
    assert all(r.role_type == "Permanent" for r in roles)
