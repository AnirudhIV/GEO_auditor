"""Convenience launcher so `python app.py` works from the repo root without
needing to know the package's internal module path."""
from geo_auditor.webapp import app

if __name__ == "__main__":
    app.run(debug=True, port=5000)
