# MTP 2026 Court Scraper

## Why this structure
The PDF slides say the original project scraped **eCourts** cause-list/case-detail data, and specifically mention using `https://ecourts.gov.in/` and collecting data from Supreme Court plus multiple High Courts and district/taluka courts. For a 2026 rebuild, the current official front doors are the e-Courts portals for general services and High Court services.

## Directory structure

```text
mtp_2026_scraper/
├── config/
│   └── courts.yaml
├── src/
│   ├── scrape_ecourts_2026.py
│   └── parse_raw_to_tables.py
├── output/
│   ├── raw/
│   ├── parsed/
│   └── logs/
├── requirements.txt
└── README.md
```

## Core idea

1. `scrape_ecourts_2026.py`
   - opens the official High Court e-Courts site in a browser
   - lets you solve captcha manually
   - searches by **Case Type** + **Year** + **Pending/Disposed**
   - opens each case detail page
   - stores raw HTML plus parsed sections in JSONL

2. `parse_raw_to_tables.py`
   - converts the raw JSONL into flat CSV tables
   - these are the starting point for plotting and further metric-building

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python src/scrape_ecourts_2026.py --court calcutta --config config/courts.yaml --out-dir output/raw --statuses disposed
python src/parse_raw_to_tables.py --input-dir output/raw --out-dir output/parsed
```

## Notes
- You will likely need to tweak selectors once in your browser because these portals can vary a bit across courts.
- Start with **Calcutta** because your archived project already used that heavily.
- Do not try all courts first.
