"""Minimal Flask front end. One form, one result page - no auth, no DB,
no accounts, per the brief. The audit runs synchronously in the request;
for the 3-5 sites this tool targets that's a 5-20s wait, which the form
warns about, rather than adding background jobs/polling for a take-home."""
from flask import Flask, render_template, request

from .audit import run_audit
from .report import render_html

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/audit")
def audit():
    url = (request.form.get("url") or "").strip()
    business_name = (request.form.get("business_name") or "").strip() or None
    location = (request.form.get("location") or "").strip() or None

    if not url:
        return render_template("index.html", error="Enter a website URL to audit."), 400

    try:
        result = run_audit(url, business_name=business_name, location=location)
    except Exception as exc:  # noqa: BLE001 - surface any failure as a friendly form error, not a 500
        return render_template(
            "index.html",
            error=f"Couldn't audit that URL: {exc}",
            prev_url=url,
            prev_name=business_name,
            prev_location=location,
        ), 400

    return render_html(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
