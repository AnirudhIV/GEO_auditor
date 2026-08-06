"""Check 2: Structured Data & Entity Clarity.

Why this check exists: an LLM deciding whether to cite you has to first
resolve *what you are* - a business entity with a name, a category, and a
location - before it can decide you're relevant to a query. schema.org
JSON-LD is the explicit, machine-readable way to say "I am a LocalBusiness
named X, in city Y, doing Z" instead of making the model infer it from
prose. llms.txt is the newer, AI-specific analogue of the same idea (an
index card for what matters on the site). We also check the literal
title/meta description and opening content, because those are the fallback
signal when structured data is absent - evidence shows this is what most
small business sites actually rely on.

Scope decision: we check for JSON-LD only (script type=application/ld+json),
not Microdata or RDFa. JSON-LD is what Google's own documentation
recommends and what the overwhelming majority of modern site builders
(Shopify, Squarespace, Wix, WordPress SEO plugins) emit by default, so it's
the highest-signal, lowest-effort thing to check for.
"""
import json
import re

from ..fetch import fetch_llms_txt, fetch_url, parse_html, visible_text
from ..models import CheckResult, Finding

RELEVANT_TYPES = {"Organization", "LocalBusiness", "WebSite", "FAQPage", "Product", "BreadcrumbList", "Article"}


def _extract_json_ld(soup) -> list[dict]:
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                blocks.extend([d for d in data["@graph"] if isinstance(d, dict)])
            else:
                blocks.append(data)
    return blocks


def _types_present(blocks: list[dict]) -> set[str]:
    types: set[str] = set()
    for b in blocks:
        t = b.get("@type")
        if isinstance(t, list):
            types.update(t)
        elif isinstance(t, str):
            types.add(t)
    return types


def run(base_url: str, business_name: str | None) -> CheckResult:
    findings: list[Finding] = []
    score = 100.0

    home = fetch_url(base_url)
    if not home.ok:
        return CheckResult(
            check_id="structured_data",
            name="Structured Data & Entity Clarity",
            why_it_matters="An AI engine has to resolve who you are before it can decide you're relevant to a query.",
            score=0.0,
            max_score=100.0,
            findings=[Finding(
                id="homepage-fetch-error", title="Could not load homepage", severity="warning",
                location=base_url, evidence=f"Request failed: {home.error or f'HTTP {home.status_code}'}",
                recommendation="Structured data could not be checked because the homepage did not load.",
                impact=3, effort=2,
            )],
            summary="Homepage did not load; structured data could not be checked.",
        )

    soup = parse_html(home.text)
    blocks = _extract_json_ld(soup)
    types_present = _types_present(blocks)

    # --- Organization / LocalBusiness schema (35 pts) ---
    entity_types = types_present & {"Organization", "LocalBusiness"} | {
        t for t in types_present if "LocalBusiness" in t or t.endswith("Business")
    }
    if entity_types:
        entity_block = next(
            (b for b in blocks if (b.get("@type") if isinstance(b.get("@type"), str) else "") in entity_types
             or (isinstance(b.get("@type"), list) and entity_types & set(b.get("@type")))),
            None,
        )
        evidence = json.dumps(entity_block, indent=2)[:800] if entity_block else str(entity_types)
        findings.append(Finding(
            id="schema-entity-present", title=f"Business entity schema found ({', '.join(sorted(entity_types))})",
            severity="good", location=base_url, evidence=evidence,
            recommendation="No action needed - this gives AI engines an explicit, structured answer to 'what is this business.'",
            impact=1, effort=1,
        ))
    else:
        score -= 35
        name_guess = business_name or "Your Business Name"
        fix = json.dumps({
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": name_guess,
            "url": base_url,
            "description": "One sentence describing what you do and who you serve.",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Street address",
                "addressLocality": "City",
                "addressRegion": "State/Region",
                "postalCode": "ZIP/Postal code",
                "addressCountry": "Country code, e.g. US",
            },
            "telephone": "+1-000-000-0000",
        }, indent=2)
        findings.append(Finding(
            id="schema-entity-missing",
            title="No Organization/LocalBusiness structured data found",
            severity="critical", location=base_url,
            evidence=f"Scanned {len(blocks)} JSON-LD block(s) on the homepage; none declared @type Organization or LocalBusiness.",
            recommendation=(
                "Without this, an AI engine has to *guess* your name, location, and category from prose. "
                "Adding this JSON-LD block to your homepage's <head> gives it an explicit, unambiguous answer."
            ),
            fix=f'<script type="application/ld+json">\n{fix}\n</script>',
            impact=5, effort=1,
        ))

    # --- FAQPage schema (15 pts) ---
    page_text_lower = visible_text(soup).lower()
    has_faq_content = "faq" in page_text_lower or bool(re.search(r"\?\s*</?(h[1-6]|strong|b)>", home.text, re.I)) or page_text_lower.count("?") >= 3
    if "FAQPage" in types_present:
        findings.append(Finding(
            id="schema-faq-present", title="FAQPage schema found", severity="good",
            location=base_url, evidence="Found a JSON-LD block with @type FAQPage.",
            recommendation="No action needed.", impact=1, effort=1,
        ))
    elif has_faq_content:
        score -= 15
        findings.append(Finding(
            id="schema-faq-missing-but-content-exists",
            title="Page has FAQ-style content but no FAQPage schema wrapping it",
            severity="warning", location=base_url,
            evidence="Detected question-style content (multiple '?' occurrences or FAQ-labeled section) on the homepage, but no matching JSON-LD FAQPage block.",
            recommendation="Wrapping existing Q&A content in FAQPage schema is one of the highest-leverage, lowest-effort changes for AI citation - it hands the exact question/answer pairs to the engine in a format it can lift directly.",
            fix=(
                '<script type="application/ld+json">\n'
                '{\n  "@context": "https://schema.org",\n  "@type": "FAQPage",\n  "mainEntity": [\n'
                '    {\n      "@type": "Question",\n      "name": "Replace with your actual first FAQ question",\n'
                '      "acceptedAnswer": {"@type": "Answer", "text": "Replace with your actual answer text"}\n    }\n'
                "  ]\n}\n</script>"
            ),
            impact=4, effort=2,
        ))
    else:
        score -= 7  # smaller penalty: no FAQ content to begin with, so this is a content gap, not just a markup gap
        findings.append(Finding(
            id="schema-faq-absent",
            title="No FAQ content or FAQPage schema found",
            severity="info", location=base_url,
            evidence="No question-style content or FAQPage schema detected on the homepage.",
            recommendation="Consider adding a short FAQ section answering the 3-5 questions customers actually ask before buying - this is one of the most directly quotable formats for AI answers.",
            impact=3, effort=3,
        ))

    # --- llms.txt (15 pts) ---
    llms = fetch_llms_txt(base_url)
    if llms.ok and llms.text and len(llms.text.strip()) > 20:
        findings.append(Finding(
            id="llms-txt-present", title="llms.txt found", severity="good",
            location=f"{base_url.rstrip('/')}/llms.txt", evidence=llms.text[:400],
            recommendation="No action needed.", impact=1, effort=1,
        ))
    else:
        score -= 15
        title_text = soup.title.string.strip() if soup.title and soup.title.string else (business_name or "Your Business")
        fix = (
            f"# {title_text}\n\n"
            f"> One or two sentences describing what this business does and who it serves.\n\n"
            f"## Key pages\n"
            f"- [Homepage]({base_url}): overview of the business\n"
            f"- [About](#): who we are\n"
            f"- [Services/Products](#): what we offer\n"
        )
        findings.append(Finding(
            id="llms-txt-missing", title="No llms.txt found", severity="warning",
            location=f"{base_url.rstrip('/')}/llms.txt",
            evidence=f"Request to /llms.txt returned {'HTTP ' + str(llms.status_code) if llms.status_code else (llms.error or 'no content')}.",
            recommendation=(
                "llms.txt is an emerging, plain-text convention (analogous to robots.txt) that tells AI "
                "engines what your site is and which pages matter most. It's new and not universally "
                "adopted yet, so treat this as a cheap, additive signal rather than a must-have."
            ),
            fix=fix, impact=2, effort=1,
        ))

    # --- Title & meta description (20 pts) ---
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = (meta_desc_tag.get("content") or "").strip() if meta_desc_tag else ""

    title_ok = 10 <= len(title) <= 70
    desc_ok = 50 <= len(meta_desc) <= 160

    if title_ok and desc_ok:
        findings.append(Finding(
            id="meta-ok", title="Title and meta description are present and well-formed", severity="good",
            location=base_url, evidence=f'<title>: "{title}"\n<meta name="description">: "{meta_desc}"',
            recommendation="No action needed.", impact=1, effort=1,
        ))
    else:
        penalty = 0
        problems = []
        if not title:
            problems.append("missing <title>"); penalty += 10
        elif not title_ok:
            problems.append(f"<title> is {len(title)} characters (recommended 10-70)"); penalty += 5
        if not meta_desc:
            problems.append("missing meta description"); penalty += 10
        elif not desc_ok:
            problems.append(f"meta description is {len(meta_desc)} characters (recommended 50-160)"); penalty += 5
        score -= penalty
        first_p = soup.find("p")
        derived_desc = (first_p.get_text().strip() if first_p else visible_text(soup)[:200])
        derived_desc = (derived_desc[:155] + "...") if len(derived_desc) > 155 else derived_desc
        findings.append(Finding(
            id="meta-issue", title="Title/meta description missing or poorly sized",
            severity="warning", location=base_url,
            evidence=f'{"; ".join(problems)}.\nCurrent <title>: "{title or "(none)"}"\nCurrent meta description: "{meta_desc or "(none)"}"',
            recommendation="These are often the exact snippet Google AI Overviews and ChatGPT search pull from directly - a vague or missing one is a missed one-line summary of your business.",
            fix=f'<title>{title or (business_name or "Your Business")} | What you do, where you are</title>\n<meta name="description" content="{derived_desc}">',
            impact=3, effort=1,
        ))

    score = max(0.0, min(100.0, score))
    summary = ", ".join(f.title for f in findings if f.severity in ("critical", "warning")) or "All structured data checks passed."

    return CheckResult(
        check_id="structured_data",
        name="Structured Data & Entity Clarity",
        why_it_matters=(
            "Before an AI engine can decide you're relevant to a query, it has to resolve what you are - "
            "a business entity with a name, category, and location. schema.org JSON-LD and llms.txt give "
            "it that answer explicitly instead of forcing it to infer from prose."
        ),
        score=round(score, 1),
        max_score=100.0,
        findings=findings,
        summary=summary,
    )
