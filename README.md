# Badminton court availability scraper (Mile End + Whitechapel)

This repository contains a Playwright-based scraper and a GitHub Actions workflow that checks badminton court session availability for:

- Mile End Park Leisure Centre
- Whitechapel Sports Centre

## Run locally

1. Install Python 3.11+
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

3. Run the scraper:

```bash
python scripts/scrape_badminton_availability.py --days 7
```

Output files are written to `output/`:

- `availability.json`
- `availability.csv`

## Run from GitHub Actions

Use the **Badminton Availability Scrape** workflow in the Actions tab.

- Trigger manually with **Run workflow** and optional `days` input.
- Or let it run on the daily schedule.

The workflow uploads JSON and CSV output as artifacts.
