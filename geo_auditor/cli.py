"""Command-line entry point - runs one audit and writes an HTML report to
disk. Used to generate the standalone report files for submission; the
Flask app (webapp.py) covers the interactive "enter a URL, see a report"
flow the brief describes.
"""
import argparse
import sys
from pathlib import Path

from .audit import run_audit
from .report import render_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a GEO (AI search visibility) audit and write an HTML report.")
    parser.add_argument("url", help="Website URL to audit, e.g. acmebakery.com")
    parser.add_argument("--name", dest="business_name", default=None, help="Business name (guessed from the site if omitted)")
    parser.add_argument("--category", default=None, help="Business category, shown in the report header only")
    parser.add_argument("--location", default=None, help="Business location, shown in the report header only")
    parser.add_argument("-o", "--output", default=None, help="Output HTML file path (default: reports/<business>.html)")
    args = parser.parse_args()

    print(f"Auditing {args.url} ...", file=sys.stderr)
    result = run_audit(args.url, args.business_name, args.category, args.location)

    slug = "".join(c if c.isalnum() else "_" for c in result.business_name.lower()).strip("_")
    out_path = Path(args.output) if args.output else Path("reports") / f"{slug}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(result), encoding="utf-8")

    print(f"Overall score: {result.overall_score}/100", file=sys.stderr)
    for check in result.checks:
        print(f"  {check.name}: {check.score}/{check.max_score}", file=sys.stderr)
    print(f"Report written to {out_path.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
