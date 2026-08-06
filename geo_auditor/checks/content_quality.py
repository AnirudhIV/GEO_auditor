"""Check 3: Answer-Extractability & Fact Density.

Why this check exists: this is the one check most directly grounded in
published research rather than our own guesswork. The GEO paper out of
Princeton/Georgia Tech/Allen Institute ("GEO: Generative Engine
Optimization", Aggarwal et al.) found that adding citations, statistics,
and quotation-style content to a page measurably increased how often
generative engines pulled from it - more than traditional keyword-style SEO
factors did. We operationalize that finding as four cheap, page-local
heuristics:

1. Fact density - concrete numbers (stats, prices, years, counts) per 100
   words. LLMs preferentially lift specific, verifiable claims over vague
   marketing copy.
2. Direct-answer opening - does the page state plainly, near the top, what
   the business is/does? Zyppy's "AI Citation Ranking Factors" analysis
   scores "answer near the top of the page" as one of the strongest
   observed factors (8.8/10) in whether an LLM cites a page, so
   front-loading the answer matters. (An oft-repeated "44% of citations
   come from the first 30% of a page" stat is widely attributed to Zyppy
   but doesn't trace back to any of their published posts under that
   number - we checked and dropped it rather than cite an unverifiable
   figure.)
3. FAQ-style content - question/answer pairs are close to a direct copy of
   how a user's prompt gets answered, making them unusually quotable.
4. Heading structure - a basic parseability signal; a page with no
   headings is harder for any extraction pipeline (including an LLM's) to
   segment into citable chunks.

Scope decision: we crawl at most 3 pages (homepage + up to 2 internal pages
matched by keyword, e.g. "about"/"faq"/"services"). This is deliberately
shallow - the brief asks for a tool that works well on a handful of real
sites, not a full-site crawler, and going deeper multiplies runtime and
messy-HTML failure modes for marginal signal.
"""
import re

from ..fetch import discover_internal_links, fetch_url, parse_html, visible_text
from ..models import CheckResult, Finding

NUMBER_PATTERN = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
OPENING_VERBS = re.compile(r"\b(is|are|provides?|offers?|specializes? in|helps?|serves?)\b", re.I)


def _fact_density(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    matches = NUMBER_PATTERN.findall(text)
    return round(len(matches) / len(words) * 100, 2)


def _has_direct_answer_opening(text: str, business_name: str | None) -> tuple[bool, str]:
    opening = text[:350]
    if business_name and business_name.lower() in opening.lower():
        idx = opening.lower().find(business_name.lower())
        snippet = opening[idx: idx + 160]
        if OPENING_VERBS.search(opening[idx: idx + 200]):
            return True, snippet
    # fallback: any strong declarative sentence near the very top
    first_sentence_match = re.split(r"(?<=[.!?])\s", opening)
    if first_sentence_match and OPENING_VERBS.search(first_sentence_match[0]):
        return True, first_sentence_match[0]
    return False, opening[:160]


def _faq_signal(text: str, html: str) -> tuple[bool, str]:
    q_count = text.count("?")
    faq_heading = bool(re.search(r"<h[1-6][^>]*>[^<]*(faq|frequently asked)", html, re.I))
    if faq_heading:
        return True, "Found a heading containing 'FAQ' / 'Frequently Asked Questions'."
    if q_count >= 3:
        return True, f"Found {q_count} question marks in body content, suggesting Q&A-style content."
    return False, f"Only {q_count} question mark(s) found; no FAQ heading detected."


def _heading_structure(soup) -> tuple[int, int, list[str]]:
    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    sample = [h.get_text().strip() for h in (h1s + h2s)[:5] if h.get_text().strip()]
    return len(h1s), len(h2s), sample


def run(base_url: str, business_name: str | None) -> CheckResult:
    home = fetch_url(base_url)
    if not home.ok:
        return CheckResult(
            check_id="content_quality", name="Answer-Extractability & Fact Density",
            why_it_matters="LLMs preferentially lift specific, front-loaded, quotable content over vague marketing copy.",
            score=0.0, max_score=100.0,
            findings=[Finding(
                id="content-fetch-error", title="Could not load homepage", severity="warning",
                location=base_url, evidence=f"Request failed: {home.error or f'HTTP {home.status_code}'}",
                recommendation="Content quality could not be checked because the homepage did not load.",
                impact=3, effort=2,
            )],
            summary="Homepage did not load; content quality could not be checked.",
        )

    soup = parse_html(home.text)
    pages = [(base_url, soup, home.text)]

    extra_urls = discover_internal_links(soup, base_url, keywords=["about", "faq", "service", "product", "pricing"], limit=2)
    for u in extra_urls:
        r = fetch_url(u)
        if r.ok:
            s = parse_html(r.text)
            pages.append((u, s, r.text))

    findings: list[Finding] = []
    score = 100.0

    combined_text = " ".join(visible_text(s) for _, s, _ in pages)
    home_text = visible_text(soup)

    # --- Fact density (30 pts) ---
    density = _fact_density(combined_text)
    if density >= 1.0:
        findings.append(Finding(
            id="fact-density-good", title=f"Fact density: {density} numeric facts per 100 words",
            severity="good", location=", ".join(u for u, _, _ in pages),
            evidence=f"Counted {len(NUMBER_PATTERN.findall(combined_text))} numeric tokens across {len(combined_text.split())} words on {len(pages)} page(s).",
            recommendation="Above the ~1-per-100-words benchmark associated with higher AI citation rates. No action needed.",
            impact=1, effort=1,
        ))
    else:
        score -= 30
        findings.append(Finding(
            id="fact-density-low", title=f"Low fact density: {density} numeric facts per 100 words",
            severity="warning" if density > 0.3 else "critical",
            location=", ".join(u for u, _, _ in pages),
            evidence=f"Counted only {len(NUMBER_PATTERN.findall(combined_text))} numeric tokens across {len(combined_text.split())} words. Research on generative engine citation (Princeton/GT/AI2's GEO study) associates roughly 1+ verifiable stat/fact per 100 words with meaningfully higher citation rates.",
            recommendation="Add concrete, verifiable numbers: years in business, number of customers served, response times, prices, sizes, counts. Vague claims like 'high quality service' are not citable; '4.9 stars from 210 reviews' is.",
            fix="Example rewrite: \"We're a local bakery\" -> \"We're a family-run bakery that has served [City] since 2011, baking 300+ loaves a day.\"",
            impact=4, effort=3,
        ))

    # --- Direct-answer opening (25 pts) ---
    has_opening, opening_evidence = _has_direct_answer_opening(home_text, business_name)
    if has_opening:
        findings.append(Finding(
            id="opening-good", title="Homepage states what the business does near the top",
            severity="good", location=base_url, evidence=f'"{opening_evidence.strip()}"',
            recommendation="No action needed - this is exactly the kind of sentence an AI engine can lift directly as an answer.",
            impact=1, effort=1,
        ))
    else:
        score -= 25
        name = business_name or "[Business Name]"
        findings.append(Finding(
            id="opening-missing", title="No clear, direct statement of what the business does near the top of the homepage",
            severity="warning", location=base_url, evidence=f'First ~350 characters of visible content: "{opening_evidence.strip()}"',
            recommendation=(
                "Zyppy's analysis of AI citation ranking factors scores 'answer near the top of the page' "
                "as one of the strongest observed factors in whether an LLM cites a page. If the opening is "
                "a slogan or hero image caption instead of a plain statement, the engine has to work harder "
                "to confirm what you do - and may just cite a competitor whose homepage says it plainly."
            ),
            fix=f"{name} is a [category] based in [location] that [what you do / who you serve] since [year].",
            impact=4, effort=2,
        ))

    # --- FAQ-style content (25 pts) ---
    has_faq, faq_evidence = _faq_signal(combined_text, " ".join(html for _, _, html in pages))
    if has_faq:
        findings.append(Finding(
            id="faq-content-good", title="FAQ-style content detected", severity="good",
            location=", ".join(u for u, _, _ in pages), evidence=faq_evidence,
            recommendation="No action needed - question/answer content is unusually quotable for AI answers.",
            impact=1, effort=1,
        ))
    else:
        score -= 25
        findings.append(Finding(
            id="faq-content-missing", title="No FAQ-style question/answer content found",
            severity="warning", location=", ".join(u for u, _, _ in pages), evidence=faq_evidence,
            recommendation="Q&A content mirrors how users actually phrase prompts to AI engines, making it easy to lift verbatim. Add a short FAQ answering the 3-5 questions customers ask most before buying.",
            fix=(
                "Example structure:\nQ: [Question a customer actually asks]\n"
                "A: [Direct, one-to-two sentence answer - no marketing fluff.]"
            ),
            impact=4, effort=3,
        ))

    # --- Heading structure (20 pts) ---
    h1_count, h2_count, sample_headings = _heading_structure(soup)
    if h1_count >= 1 and h2_count >= 1:
        findings.append(Finding(
            id="headings-good", title=f"Homepage has {h1_count} H1 and {h2_count} H2 heading(s)",
            severity="good", location=base_url, evidence=f"Sample headings found: {sample_headings}",
            recommendation="No action needed - clear headings help any extraction pipeline (including an LLM's) segment your content into citable chunks.",
            impact=1, effort=1,
        ))
    else:
        score -= 20
        problem = "no H1 tag" if h1_count == 0 else "no H2 tags (page is likely one undifferentiated block of text)"
        findings.append(Finding(
            id="headings-missing", title=f"Weak heading structure on homepage ({problem})",
            severity="warning", location=base_url, evidence=f"H1 count: {h1_count}, H2 count: {h2_count}. Sample headings found: {sample_headings or 'none'}",
            recommendation="Add a single, clear H1 stating the business + category, and H2s to break up sections (Services, About, FAQ, Contact). This is a basic parseability signal for both search engines and LLM content extraction.",
            impact=3, effort=2,
        ))

    score = max(0.0, min(100.0, score))
    summary = f"Checked {len(pages)} page(s): {', '.join(u for u, _, _ in pages)}"

    return CheckResult(
        check_id="content_quality",
        name="Answer-Extractability & Fact Density",
        why_it_matters=(
            "Published research on generative engine citation found that fact density, front-loaded direct "
            "answers, and quotable Q&A content measurably increase how often an LLM pulls from a page - "
            "more than traditional keyword SEO factors. This check operationalizes those findings."
        ),
        score=round(score, 1), max_score=100.0, findings=findings, summary=summary,
    )
