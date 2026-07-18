"""Cover the advert-text fetcher: extraction, and honest failures. Offline."""

import io
import urllib.error

import pytest

import fetch_jd

PAGE = """
<html><head><title>Job</title><script>var x = 1;</script>
<style>.a {color: red}</style></head>
<body>
<nav>Home | Jobs | Sign in</nav>
<article>
  <h1>Programme Manager</h1>
  <p>Lead the delivery of a major AI transformation programme.</p>
  <ul><li>Agile at scale</li><li>Stakeholder management</li></ul>
  <p>""" + ("Detail. " * 60) + """</p>
</article>
<footer>Cookie policy</footer>
</body></html>
"""


def test_extract_text_keeps_content_drops_chrome_and_code():
    text = fetch_jd.extract_text(PAGE)
    assert "Programme Manager" in text
    assert "Agile at scale" in text and "Stakeholder management" in text
    assert "var x" not in text          # script dropped
    assert "color: red" not in text     # style dropped
    assert "Sign in" not in text        # nav dropped
    assert "Cookie policy" not in text  # footer dropped
    assert "\n" in text                 # block tags became line breaks


class _FakeResp:
    def __init__(self, body, ctype="text/html; charset=utf-8"):
        self._body = body.encode("utf-8")
        self.headers = _FakeHeaders(ctype)

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeHeaders:
    def __init__(self, ctype):
        self._ctype = ctype

    def get(self, name, default=""):
        return self._ctype if name == "Content-Type" else default

    def get_content_charset(self):
        return "utf-8"


def test_boilerplate_lines_are_dropped_but_content_mentioning_them_is_kept():
    text = "\n".join([
        "❮ back to last search",
        "Programme Manager",
        "No thanks, take me to the job",
        "You will apply for this job through our governance process.",  # content, kept
        "Apply for this job",
        "By creating an alert, you agree to our T&Cs and Privacy Notice, and Cookie Use.",
        "Country selection",
        "AustraliaAustriaBelgiumBrazilCanadaFrance",
        "Lead the delivery of the AI programme.",
    ])
    cleaned = fetch_jd._drop_boilerplate(text)
    assert "back to last search" not in cleaned
    assert "No thanks" not in cleaned
    assert "By creating an alert" not in cleaned
    assert "Country selection" not in cleaned
    assert "AustraliaAustria" not in cleaned
    assert "governance process" in cleaned          # full sentences survive
    assert "Lead the delivery" in cleaned
    assert "Programme Manager" in cleaned


def test_fetch_returns_text_for_a_real_looking_page(monkeypatch):
    monkeypatch.setattr(fetch_jd.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(PAGE))
    text = fetch_jd.fetch_advert_text("https://example.com/job")
    assert "AI transformation programme" in text


def test_fetch_rejects_thin_js_rendered_pages(monkeypatch):
    monkeypatch.setattr(fetch_jd.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp("<html><body>Loading...</body></html>"))
    with pytest.raises(fetch_jd.FetchError) as err:
        fetch_jd.fetch_advert_text("https://example.com/job")
    assert "JavaScript" in str(err.value)


def test_fetch_surfaces_a_block_honestly(monkeypatch):
    def blocked(req, timeout=0):
        raise urllib.error.HTTPError("http://x", 403, "Forbidden", None, io.BytesIO(b""))

    monkeypatch.setattr(fetch_jd.urllib.request, "urlopen", blocked)
    with pytest.raises(fetch_jd.FetchError) as err:
        fetch_jd.fetch_advert_text("https://example.com/job")
    assert "HTTP 403" in str(err.value) and "paste the advert manually" in str(err.value)


def test_fetch_rejects_non_pages(monkeypatch):
    monkeypatch.setattr(fetch_jd.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp("x" * 500, ctype="application/pdf"))
    with pytest.raises(fetch_jd.FetchError):
        fetch_jd.fetch_advert_text("https://example.com/job.pdf")
    with pytest.raises(fetch_jd.FetchError):
        fetch_jd.fetch_advert_text("not-a-url")
