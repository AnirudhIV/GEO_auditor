"""Check 1: AI Crawler Access.

Why this check exists (see README for the full defense): if an AI engine's
bot can't fetch a page, nothing else in this audit matters - the business is
invisible by construction, not by ranking. This is the one gating check we
run first, and it's 100% mechanical (no LLM judgment call, no heuristic
guessing) which makes it the cheapest possible thing to get exactly right.

We distinguish two bot categories because they have different real-world
consequences:
- RETRIEVAL bots fetch pages live to answer a specific user question right
  now. Blocking these means "invisible in AI answers today."
- TRAINING bots crawl content to bake it into a future model's weights.
  Blocking these means "invisible in whatever the *next* model already
  knows," which is a slower, less urgent problem - so it's weighted lower.

Bot list and categorization is our own synthesis from published crawler
documentation (OpenAI, Anthropic, Perplexity, Google, Common Crawl) as of
2026 - see README for sources. We rely on Python's stdlib
`urllib.robotparser` for the actual allow/deny decision (it implements the
robots.txt precedence rules correctly) rather than hand-rolling that logic;
our own code only extracts the matching block for display as evidence.
"""
from urllib.robotparser import RobotFileParser

from ..fetch import fetch_robots_txt
from ..models import CheckResult, Finding

RETRIEVAL_BOTS = {
    "ChatGPT-User": "OpenAI - fetches a page live when a user asks ChatGPT to browse it or a ChatGPT search answer cites it in real time.",
    "OAI-SearchBot": "OpenAI - indexes pages for ChatGPT's search feature; this is what populates the citations you see in ChatGPT search answers.",
    "PerplexityBot": "Perplexity - crawls and indexes pages so Perplexity can cite them in answers.",
    "Perplexity-User": "Perplexity - fetches a page live when a user's question triggers a real-time browse.",
    "Claude-Web": "Anthropic - fetches pages live for Claude's web search tool, the feature behind Claude's cited answers.",
    "Google-Extended": "Google - controls whether your content can appear in Google AI Overviews and Gemini answers (separate from normal Googlebot search indexing, which is never affected by this).",
}

TRAINING_BOTS = {
    "GPTBot": "OpenAI - crawls content to train future GPT models.",
    "ClaudeBot": "Anthropic - crawls content to train future Claude models.",
    "anthropic-ai": "Anthropic - legacy crawler identifier, also used for AI training access.",
    "CCBot": "Common Crawl - a public web dataset most major LLMs (GPT, Claude, Llama, Mistral, and others) are trained on. Blocking this affects many models' future knowledge of you at once.",
    "Bytespider": "ByteDance - crawls content to train Doubao and other ByteDance AI models.",
    "Applebot-Extended": "Apple - controls use of your content for Apple Intelligence features.",
}

ALL_BOTS = {**RETRIEVAL_BOTS, **TRAINING_BOTS}


def _group_robots_txt(text: str) -> list[tuple[set[str], list[tuple[str, str]]]]:
    """Split robots.txt into (agents, directives) groups per the standard
    grouping rule: consecutive User-agent lines share the directives that
    follow them, until the next User-agent line after a directive starts a
    new group."""
    groups: list[tuple[set[str], list[tuple[str, str]]]] = []
    current_agents: set[str] = set()
    current_lines: list[tuple[str, str]] = []
    seen_directive_since_agent = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if seen_directive_since_agent:
                groups.append((current_agents, current_lines))
                current_agents, current_lines = set(), []
                seen_directive_since_agent = False
            current_agents.add(value.lower())
        elif field in ("allow", "disallow"):
            current_lines.append((field, value))
            seen_directive_since_agent = True

    if current_agents:
        groups.append((current_agents, current_lines))
    return groups


def _evidence_block(groups, bot_lower: str) -> tuple[str, str]:
    """Return (matched_agent_label, reconstructed robots.txt block text)."""
    for agents, lines in groups:
        if bot_lower in agents:
            body = "\n".join(f"{f.capitalize()}: {v}" for f, v in lines) or "(no rules)"
            return bot_lower, f"User-agent: {bot_lower}\n{body}"
    for agents, lines in groups:
        if "*" in agents:
            body = "\n".join(f"{f.capitalize()}: {v}" for f, v in lines) or "(no rules)"
            return "*", f"User-agent: *\n{body}"
    return "", "(no matching or wildcard rule found - implicitly allowed)"


def run(base_url: str) -> CheckResult:
    result = fetch_robots_txt(base_url)

    if not result.ok:
        # No robots.txt (404) means no restrictions exist at all - genuinely good news.
        if result.status_code == 404:
            return CheckResult(
                check_id="crawler_access",
                name="AI Crawler Access",
                why_it_matters=(
                    "If an AI engine's bot can't fetch your pages, it doesn't matter how good your "
                    "content is - it never enters the answer. This checks whether your robots.txt "
                    "blocks the bots that power ChatGPT, Claude, Perplexity, and Google AI Overviews."
                ),
                score=100.0,
                max_score=100.0,
                findings=[
                    Finding(
                        id="robots-missing",
                        title="No robots.txt found - nothing is blocking AI crawlers",
                        severity="good",
                        location=f"{base_url.rstrip('/')}/robots.txt (HTTP 404)",
                        evidence="Request to /robots.txt returned 404 Not Found.",
                        recommendation="No action needed for crawler access. Note: adding an llms.txt file is a separate, additive step covered in the Structured Data check.",
                        impact=1,
                        effort=1,
                    )
                ],
                summary="No robots.txt exists, so by default every AI crawler is free to fetch this site.",
            )
        # Any other fetch failure (timeout, DNS, 5xx) - degrade, don't crash.
        return CheckResult(
            check_id="crawler_access",
            name="AI Crawler Access",
            why_it_matters="If an AI engine's bot can't fetch your pages, nothing else in this audit matters.",
            score=0.0,
            max_score=100.0,
            findings=[
                Finding(
                    id="robots-fetch-error",
                    title="Could not retrieve robots.txt",
                    severity="warning",
                    location=f"{base_url.rstrip('/')}/robots.txt",
                    evidence=f"Request failed: {result.error or f'HTTP {result.status_code}'}",
                    recommendation="Could not verify crawler access. Check manually that your server responds to requests for /robots.txt.",
                    impact=3,
                    effort=2,
                )
            ],
            summary="robots.txt could not be retrieved, so crawler access could not be verified.",
        )

    text = result.text or ""
    groups = _group_robots_txt(text)
    findings: list[Finding] = []
    score = 100.0

    parser = RobotFileParser()
    parser.parse(text.splitlines())

    blocked_retrieval, blocked_training = [], []

    for bot, description in ALL_BOTS.items():
        allowed = parser.can_fetch(bot, "/")
        if allowed:
            continue
        matched_agent, block_text = _evidence_block(groups, bot.lower())
        is_retrieval = bot in RETRIEVAL_BOTS
        penalty = 25 if is_retrieval else 10
        score -= penalty
        (blocked_retrieval if is_retrieval else blocked_training).append(bot)
        findings.append(
            Finding(
                id=f"blocked-{bot.lower()}",
                title=f"{bot} is blocked in robots.txt",
                severity="critical" if is_retrieval else "warning",
                location=f"{base_url.rstrip('/')}/robots.txt",
                evidence=f"{description}\n\nMatched rule block:\n{block_text}",
                recommendation=(
                    f"{bot} is currently disallowed, which means "
                    f"{'this bot cannot fetch your pages to answer live user questions' if is_retrieval else 'this bot cannot crawl your content for model training'}. "
                    "Remove or narrow this rule if you want this engine to be able to see your site."
                ),
                fix=(
                    f"User-agent: {bot}\nAllow: /\n"
                    f"\n# Add this block to robots.txt (or remove the conflicting Disallow rule under "
                    f"the '{matched_agent or '*'}' section shown above)."
                ),
                impact=5 if is_retrieval else 3,
                effort=1,
            )
        )

    score = max(0.0, score)

    if not findings:
        findings.append(
            Finding(
                id="robots-all-allowed",
                title="All known AI crawlers are allowed",
                severity="good",
                location=f"{base_url.rstrip('/')}/robots.txt",
                evidence=f"robots.txt exists but contains no Disallow rules matching any of {len(ALL_BOTS)} known AI bots.",
                recommendation="No action needed.",
                impact=1,
                effort=1,
            )
        )

    summary_parts = []
    if blocked_retrieval:
        summary_parts.append(f"{len(blocked_retrieval)} live-answer bot(s) blocked ({', '.join(blocked_retrieval)})")
    if blocked_training:
        summary_parts.append(f"{len(blocked_training)} training bot(s) blocked ({', '.join(blocked_training)})")
    summary = "; ".join(summary_parts) if summary_parts else "No AI crawlers are blocked."

    return CheckResult(
        check_id="crawler_access",
        name="AI Crawler Access",
        why_it_matters=(
            "If an AI engine's bot can't fetch your pages, it doesn't matter how good your content is - "
            "it never enters the answer. This checks whether your robots.txt blocks the bots that power "
            "ChatGPT, Claude, Perplexity, and Google AI Overviews, using Python's standard robots.txt "
            "parser against each bot's declared name."
        ),
        score=round(score, 1),
        max_score=100.0,
        findings=findings,
        summary=summary,
    )
