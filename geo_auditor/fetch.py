"""Network + parsing layer. Every check goes through here so error handling
(timeouts, non-200s, garbage HTML) is handled once instead of in every check.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# A real browser UA. We want to see what a normal visitor (and, by proxy,
# most AI retrieval bots that render like a browser) actually sees -
# robots.txt itself is checked separately, against its declared bot names,
# not against this UA.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 GEOAuditor/1.0"
)
TIMEOUT = 12


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int]
    text: Optional[str]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300


def fetch_url(url: str) -> FetchResult:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        # requests decodes based on headers/guessing; force apparent encoding
        # fallback for sites with broken charset headers rather than crashing.
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or resp.encoding
        return FetchResult(url=resp.url, status_code=resp.status_code, text=resp.text)
    except requests.exceptions.RequestException as e:
        return FetchResult(url=url, status_code=None, text=None, error=str(e))


def fetch_robots_txt(base_url: str) -> FetchResult:
    return fetch_url(urljoin(base_url, "/robots.txt"))


def fetch_llms_txt(base_url: str) -> FetchResult:
    return fetch_url(urljoin(base_url, "/llms.txt"))


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def discover_internal_links(soup: BeautifulSoup, base_url: str, keywords: list[str], limit: int = 2) -> list[str]:
    """Find a small number of same-domain links whose href/anchor text
    matches keywords (e.g. 'about', 'faq'). Deliberately shallow - this is
    a spot-check tool, not a full-site crawler."""
    domain = urlparse(base_url).netloc
    seen: set[str] = set()
    candidates: list[str] = []
    base_clean = base_url.rstrip("/")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(full)
        if parsed.netloc != domain or full.rstrip("/") == base_clean:
            continue
        haystack = (href + " " + (a.get_text() or "")).lower()
        if any(k in haystack for k in keywords) and full not in seen:
            seen.add(full)
            candidates.append(full)
        if len(candidates) >= limit:
            break
    return candidates


def visible_text(soup: BeautifulSoup) -> str:
    """Strip script/style/nav/footer/header chrome and return the text a
    reader (or an LLM summarizing the page) would actually see as content."""
    clone = BeautifulSoup(str(soup), "lxml")
    for tag in clone(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    text = clone.get_text(separator=" ")
    return " ".join(text.split())
