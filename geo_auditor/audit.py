"""Top-level orchestrator: runs every check against one business and rolls
the results up into a single AuditResult.

Scoring: the three checks are weighted equally (each is 1/3 of the overall
score). We considered weighting Crawler Access higher since it's a gating
check ("nothing else matters if the bot is blocked"), but a straight
average is easier for a business owner to audit by hand - overall_score is
always exactly the mean of the numbers shown directly below it, no hidden
weighting to take on faith. If a check is mocked, it's excluded from the
average (see score_excludes) rather than silently dragging the score down
with fake data.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .checks import content_quality, crawler_access, structured_data
from .fetch import fetch_url, parse_html
from .models import AuditResult, CheckResult

URL_SCHEME_RE = re.compile(r"^https?://", re.I)
TITLE_SEPARATORS = [" | ", " – ", " — ", " - ", " :: "]
# Titles that are generic UI labels rather than the business name - seen in
# the wild (e.g. a major law firm's <title> is literally "Homepage | Morgan
# & Morgan"), so picking title.split(sep)[0] blindly gets it wrong.
GENERIC_TITLE_SEGMENTS = {"home", "homepage", "welcome", "index", "main page", "main"}
# Trademark/registered/copyright symbols and the variation-selector-16
# codepoint that often rides along with an emoji-fied trademark glyph.
_STRIP_CODEPOINTS = [0x2122, 0xAE, 0xA9, 0xFE0F]
TRADEMARK_CHARS = str.maketrans("", "", "".join(chr(c) for c in _STRIP_CODEPOINTS))


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not URL_SCHEME_RE.match(url):
        url = "https://" + url
    return url


def _clean_name(name: str) -> str:
    return name.translate(TRADEMARK_CHARS).strip()


def _pick_title_segment(title: str) -> str:
    """Titles are usually 'Brand | Tagline', but some sites (e.g. a large
    law firm whose homepage <title> is literally 'Homepage | Morgan &
    Morgan') put a generic UI label first instead. Prefer the first segment
    that isn't a known generic word over blindly taking segment [0]."""
    for sep in TITLE_SEPARATORS:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            non_generic = [p for p in parts if p.lower() not in GENERIC_TITLE_SEGMENTS]
            return non_generic[0] if non_generic else parts[0]
    return title


def _guess_business_name(url: str) -> str:
    """Best-effort name for use inside findings/fixes before checks run.
    Prefers the homepage's og:site_name or <title>, falls back to the
    domain. This is a guess, not a claim - it's only used to make generated
    fix snippets read naturally; every finding's evidence still comes from
    the actual page content, not from this guess."""
    home = fetch_url(url)
    if home.ok and home.text:
        soup = parse_html(home.text)
        og = soup.find("meta", property="og:site_name")
        if og and og.get("content", "").strip():
            return _clean_name(og["content"])
        if soup.title and soup.title.string and soup.title.string.strip():
            return _clean_name(_pick_title_segment(soup.title.string.strip()))
    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0].replace("-", " ").title()


def run_audit(
    url: str,
    business_name: str | None = None,
    category: str | None = None,
    location: str | None = None,
) -> AuditResult:
    url = normalize_url(url)

    if not business_name:
        business_name = _guess_business_name(url)

    checks: list[CheckResult] = [
        crawler_access.run(url),
        structured_data.run(url, business_name),
        content_quality.run(url, business_name),
    ]

    score_excludes = [c.check_id for c in checks if c.mocked]
    scored_checks = [c for c in checks if c.check_id not in score_excludes]
    overall_score = round(sum(c.score for c in scored_checks) / len(scored_checks), 1) if scored_checks else 0.0

    return AuditResult(
        url=url,
        business_name=business_name,
        category=category,
        location=location,
        overall_score=overall_score,
        score_excludes=score_excludes,
        checks=checks,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
