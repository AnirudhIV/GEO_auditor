"""Renders an AuditResult into the HTML report a business owner reads."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import AuditResult

TEMPLATES_DIR = Path(__file__).parent / "templates"

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "good": 3}


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_html(audit: AuditResult) -> str:
    all_findings = [(check, f) for check in audit.checks for f in check.findings]

    actionable = sorted(
        [(check, f) for check, f in all_findings if f.severity in ("critical", "warning")],
        key=lambda pair: -pair[1].priority_score,
    )

    wins = sorted(
        [f for f in actionable if f[1].effort <= 2 and f[1].impact >= 3],
        key=lambda pair: -pair[1].priority_score,
    )[:3]

    good_count = sum(1 for _, f in all_findings if f.severity == "good")
    issue_count = sum(1 for _, f in all_findings if f.severity in ("critical", "warning"))

    template = _env().get_template("report.html")
    return template.render(
        audit=audit,
        actionable=actionable,
        quick_wins=wins,
        good_count=good_count,
        issue_count=issue_count,
        severity_order=SEVERITY_ORDER,
    )
