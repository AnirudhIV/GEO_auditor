"""Shared data structures used across all checks and the report renderer."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Finding:
    """A single, evidenced observation. Every field that claims something
    is true about the site must be backed by `evidence` — no unverified claims.
    """
    id: str
    title: str
    severity: str  # "critical" | "warning" | "good" | "info"
    location: str  # exact page/file the evidence came from, e.g. "robots.txt" or homepage URL
    evidence: str  # what we actually found, verbatim where possible
    recommendation: str  # plain-English explanation of what to change and why
    fix: Optional[str] = None  # copy-pasteable snippet, if the fix allows one
    impact: int = 3  # 1 (low) - 5 (high) business impact if fixed
    effort: int = 3  # 1 (trivial) - 5 (heavy lift) to implement the fix

    @property
    def priority_score(self) -> float:
        """Higher = do this first. Impact matters more than effort, but a
        5-effort task with impact 3 still loses to a 1-effort task with
        impact 3, matching the brief's 'impact x effort' request."""
        return self.impact * (6 - self.effort)


@dataclass
class CheckResult:
    check_id: str
    name: str
    why_it_matters: str  # the defensible reasoning for why this check exists
    score: float  # 0-100, this check only
    max_score: float
    findings: list[Finding] = field(default_factory=list)
    mocked: bool = False
    mock_reason: Optional[str] = None
    summary: str = ""


@dataclass
class AuditResult:
    url: str
    business_name: str
    category: Optional[str]
    location: Optional[str]
    overall_score: float
    score_excludes: list[str]  # check_ids excluded from overall score (e.g. mocked)
    checks: list[CheckResult]
    generated_at: str
