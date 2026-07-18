"""Fetch the readable text of one job advert from its link, on the user's click.

This is reader-mode, not scraping: a single, user-initiated fetch of the advert
the user is actively drafting against, so they can avoid retyping what is already
on their screen in a browser. It makes one plain GET, follows the link's own
redirects, and extracts the page's visible text for the user to clean up.

Honest limits, surfaced as clear errors rather than worked around:
- pages that render their text with JavaScript return little or no readable text;
- pages behind bot protection may refuse the request. No evasion is attempted.

Dependency-light on purpose: stdlib urllib + html.parser only.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

# Honest, standard-format identification: this is the tool asking, once.
_USER_AGENT = "Mozilla/5.0 (compatible; LocalAIJobHunter/1.0)"

# Anything inside these elements is chrome or code, not advert text.
_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer",
              "header", "form", "button", "iframe"}
_BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "section", "article", "ul", "ol"}

MIN_READABLE_CHARS = 400  # below this the page almost certainly did not carry the advert


class FetchError(RuntimeError):
    """Raised when the advert text could not be fetched or read."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def extract_text(html: str) -> str:
    """The page's visible text, block tags becoming line breaks."""
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_advert_text(url: str, timeout: int = 20) -> str:
    """Fetch ``url`` and return its readable text, or raise FetchError honestly."""
    if not (url or "").startswith(("http://", "https://")):
        raise FetchError("the role has no usable link")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                raise FetchError(f"the link returned {ctype or 'no content type'}, not a page")
            html = resp.read(2_000_000).decode(
                resp.headers.get_content_charset() or "utf-8", "replace"
            )
    except urllib.error.HTTPError as exc:
        raise FetchError(
            f"the site refused the request (HTTP {exc.code}); open the link and "
            f"paste the advert manually"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"could not reach the link: {exc}") from exc

    text = extract_text(html)
    if len(text) < MIN_READABLE_CHARS:
        raise FetchError(
            "the page returned too little readable text (it is probably rendered "
            "by JavaScript); open the link and paste the advert manually"
        )
    return text
