# Project Structure

## Runtime Core

- Root entrypoints: `main.py`, `main_test.py`, `app.py`, `server.js`
- Frontend runtime pages: `forecast_dashboard.html`, `forecast_dashboard_v2.html`, `forecast_dashboard_with_charts.html`, `index.html`
- Core packages: `src/`, `templates/`, `static/`, `config/`, `requirements/`

## Organized Support Files

- `tools/checks`: one-off verification scripts
- `tools/debug`: debugging helpers
- `tools/ad_hoc`: quick experiments and simplified scripts
- `tools/analysis`: analysis and report-preparation helper scripts
- `tests/legacy_root`: legacy test scripts previously scattered at root
- `archive/`: historical logs, diagnostics, and generated images
- `reports/`: report artifacts kept outside the root
- `reports/generated`: generated HTML outputs from analysis helper scripts
- `ui/prototypes`: prototype HTML pages not used as main entrypoints
- `docs/project`: project plans, reports, and historical documentation

## Notes

- The goal of this layout is to keep the project root focused on active runtime files.
- Historical and exploratory assets are preserved, not deleted.
