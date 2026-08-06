# GEO Auditor

A tool that tells a business owner whether they're visible to AI search engines
(ChatGPT, Perplexity, Claude, Google AI Overviews) — with a scored, evidenced,
prioritized report, not generic advice.

Enter a URL. Get back: a score you can recompute by hand, a list of specific,
provable problems, and copy-pasteable fixes ordered by impact × effort.

## Quick start (under 5 minutes)

```bash
pip install -r requirements.txt

# Web app - form in, report out in the browser
python app.py
# then open http://127.0.0.1:5000

# or CLI - writes a standalone HTML report to reports/<business>.html
python -m geo_auditor.cli acmebakery.com --category "Bakery" --location "Austin, TX"
```

Requires Python 3.10+. No API keys, no database, no accounts — every check
either parses a page the tool fetched itself or runs Python's own
`robots.txt` parser against it.

Three real audit reports (Levain Bakery, Morgan & Morgan, Aspen Dental) are
already generated in [`reports/`](reports/) — open any of them directly in a
browser to see the output without running anything.

## What it checks, and why

The brief's instruction was "go deep, not wide" — three checks done properly
beat twelve that tick boxes. These three were chosen because they map to
three genuinely different failure modes, each of which alone is enough to
make a business invisible in AI answers even if the other two are perfect:

**1. AI Crawler Access** (`checks/crawler_access.py`) — *can the bot even
reach you?*
Checks `robots.txt` against the declared user-agents of the bots that
actually power AI answers: `OAI-SearchBot`/`ChatGPT-User` (OpenAI),
`PerplexityBot`/`Perplexity-User`, `Claude-Web`, `Google-Extended` (gates
Google AI Overviews/Gemini, separately from normal Google Search indexing),
plus training-only crawlers (`GPTBot`, `ClaudeBot`, `CCBot`, `Bytespider`,
`Applebot-Extended`) weighted lower since blocking those affects a future
model, not today's answers. This is the one 100%-mechanical, no-judgment-call
check — I use Python's stdlib `urllib.robotparser` for the actual
allow/deny decision instead of hand-rolling robots.txt precedence rules, and
our own code only reconstructs the matching block as evidence. It's first in
priority because it's a gating condition: perfect content behind a
`Disallow: /` for `PerplexityBot` is still invisible to Perplexity, full stop.
This check is what caught **Morgan & Morgan blocking every single major AI
crawler** in real testing (see `reports/morgan_and_morgan.html`) — a business
ranking #1 on Google that has explicitly opted out of every AI engine without,
we'd guess, realizing it.

**2. Structured Data & Entity Clarity** (`checks/structured_data.py`) — *can
the bot tell what you are?*
Before an engine decides you're relevant to a query, it has to resolve *what
you are* — a business entity with a name, category, and location. Checks
for schema.org `LocalBusiness`/`Organization` JSON-LD (the explicit,
machine-readable answer to that question), `FAQPage` schema wrapping any
existing Q&A content, the emerging `llms.txt` convention, and title/meta
description as the fallback signal most small-business sites actually rely
on. I check JSON-LD only (not Microdata/RDFa) because it's what Google's
own documentation recommends and what Shopify/Squarespace/Wix/WordPress SEO
plugins emit by default — highest signal for the least effort.

**3. Answer-Extractability & Fact Density** (`checks/content_quality.py`) —
*if the bot reads you, can it actually quote you?*
This is the check most directly grounded in published research rather than
our own guesswork: [Aggarwal et al., "GEO: Generative Engine Optimization"
(arXiv 2311.09735, KDD 2024)](https://arxiv.org/abs/2311.09735) — authors
from Princeton, Georgia Tech, and the Allen Institute for AI — ran a
10,000-query benchmark and found that adding citations, statistics, and
quotation-style content to a page produced the largest gains (~30–40%+) in
how often a Bing-Chat-style generative engine cited it, beating traditional
keyword-SEO tactics; keyword stuffing actually hurt. I operationalize that
as four page-local heuristics: numeric fact density (concrete numbers per
100 words), a direct-answer opening near the top of the page (also
supported by Zyppy's separate AI-citation-ranking-factors analysis, which
scores "answer near the top" as one of the strongest observed factors), FAQ
-style Q&A content (a near-literal match for how a user's prompt gets
answered), and basic heading structure (a parseability signal for any
extraction pipeline, including an LLM's). *Note: an oft-repeated "44% of
citations come from the first 30% of a page" stat is widely attributed to
Zyppy online — I went looking for the source, couldn't trace it to
anything they actually published, and dropped it rather than cite a number
I couldn't verify. Citing research I can't stand behind would undermine
the entire premise of an evidence-based tool.*

### What I deliberately did not build, and why

- **Actually querying ChatGPT/Perplexity/Claude live and checking if the
  business gets mentioned.** This is the most obvious thing to build, and we
  cut it on purpose. It's non-deterministic (the same prompt can return
  different answers minutes apart, which is corrosive for a tool whose whole
  pitch is "here's the *evidence*"), it requires guessing which query a real
  customer would type — guess wrong and you get exactly the "generic advice
  that would be identical for any website" failure mode the brief calls out
  as an instant no — and it needs paid API keys per engine, which breaks
  "running in under 5 minutes" with zero setup. The three checks I built are
  proxies for *why* a business would or wouldn't get cited, derived from
  page evidence that's stable and re-checkable; a live-query check measures
  a symptom, not a cause, and isn't reproducible evidence in the way the
  brief asks for ("name the exact page, show what you found"). This is the
  single highest-value thing to add with more time — see below.
- **Backlink/authority analysis.** Real signal, but it requires a paid
  third-party index (Ahrefs/Semrush/Moz) I don't have API access to build
  around, and it's a classic-SEO signal already well covered by existing
  tools — it doesn't teach us anything GEO-specific.
- **Page speed / Core Web Vitals.** Same reasoning — already exhaustively
  covered by free tools (Google PageSpeed Insights), not AI-visibility-
  specific, and adding it would be "easy to build" without being the right
  thing to build.
- **Full-site crawl.** Each check touches at most 2–3 pages (homepage plus
  same-domain links matched by keyword like "about"/"faq"/"services"). This
  is a spot-check tool for the 3–5 real businesses the brief asks for, not a
  sitemap crawler — going deeper multiplies runtime and messy-HTML failure
  modes for marginal extra signal.
- **Review/reputation signals (Google Business Profile, Yelp rating, etc).**
  Genuinely relevant to whether an LLM trusts a business, but pulling it
  reliably needs either a paid API or scraping a platform's ToS in a way we
  weren't comfortable shipping in a take-home; flagged as a "build next"
  item instead of building a fragile or borderline version of it.

## The score

Each check scores 0–100 independently, with the exact point deductions
visible in that check's code and in the finding evidence itself (e.g. "-35
points: no Organization/LocalBusiness schema found"). The overall score is
the **plain average of the three check scores** — no hidden weighting. The
report's score card shows all three bars plus the arithmetic; add them up
and divide by 3, and you get the number shown. I considered weighting
Crawler Access higher, since it's the one gating check, but decided a
business owner being able to audit the math themselves mattered more than a
theoretically "more correct" weighting scheme.

Fixes are ranked by `impact × (6 − effort)` (both 1–5 scales set per
finding) so a high-impact, low-effort fix always outranks a high-impact,
high-effort one — "what to do Monday morning."

## What's real vs. mocked

**Nothing in this tool is mocked.** Every finding comes from a live HTTP
fetch of the actual site (`fetch.py`) at run time — real `robots.txt`,
real HTML, real JSON-LD, parsed with BeautifulSoup/lxml and Python's own
robots-parser. The `CheckResult.mocked` field and the score-exclusion logic
in `audit.py` exist in the data model specifically so that *if* a future
check needs a stubbed/mocked data source (e.g. a paid API I don't have
credentials for), it's structurally impossible for it to silently blend
fake data into a real score — it'd show up labeled "(mocked)" in the report
and be excluded from the average. No check currently uses that path.

## Known limitations / assumptions

- English-language, roughly-standard-HTML sites. Heavily JS-rendered SPAs
  (client-side-only React/Vue with no server-rendered content) will show as
  having thin content, because I don't run a headless browser — this is a
  real product decision, not a bug: most AI retrieval bots also don't
  execute JavaScript, so a JS-only page genuinely *is* less visible to them,
  and the finding is accurate even though the root cause (needs SSR) isn't
  explicitly named.
- One locale/market at a time — no multi-language or multi-location
  handling beyond whatever the `--location` flag puts in the report header.
- The business-name guess (used to phrase fix snippets naturally) is a
  best-effort heuristic (`og:site_name`, then `<title>`, skipping generic
  segments like "Homepage" — a real bug I caught testing against Morgan &
  Morgan, whose `<title>` is literally "Homepage | Morgan & Morgan"). It's
  never used as evidence, only as phrasing.

## What we'd build next with a week

1. **A live-query cross-check, done carefully.** Run a small, fixed set of
   representative prompts (seeded from the business's own category/location,
   optionally overridden by the user) against 2–3 real engines via their
   APIs, cache the raw responses as evidence, and present results as a
   clearly-separate "spot check" panel — not blended into the deterministic
   score — with an explicit "results can vary by the minute" disclaimer.
   This directly measures the outcome the other three checks only predict.
2. **Share one fetch of the homepage across all three checks.** Right now
   `structured_data` and `content_quality` each fetch the homepage
   independently (simplicity while checks were being built one at a time);
   an orchestrator-level fetch-once-and-pass-down would roughly halve
   network round-trips per audit.
3. **A PDF export** of the same report, since a business owner may want to
   forward it to a web developer as a work order rather than a link.
4. **Historical tracking** — re-run the same audit weekly and show score
   deltas, so a fix's impact is visible, not just its existence. (Deliberately
   out of scope now — the brief explicitly says skip a database unless
   actually needed, and one audit in time doesn't need persistence.)
5. **Category-aware benchmarks** — "restaurants in your fact-density bracket
   average X" — would need a corpus of prior audits I don't have yet.

## Project structure

```
geo_auditor/
  fetch.py         # shared HTTP + HTML parsing layer (timeouts, encoding, error handling)
  models.py         # Finding / CheckResult / AuditResult dataclasses
  audit.py           # orchestrator: runs all checks, guesses business name, computes overall score
  report.py          # renders an AuditResult to HTML via Jinja2
  webapp.py          # Flask app (form -> report)
  cli.py              # CLI (URL in -> HTML file out)
  checks/
    crawler_access.py     # Check 1
    structured_data.py    # Check 2
    content_quality.py    # Check 3
  templates/
    index.html       # web form
    report.html       # the report itself
app.py                # `python app.py` launcher for the web app
reports/               # 3 real audit reports (Levain Bakery, Morgan & Morgan, Aspen Dental)
```
