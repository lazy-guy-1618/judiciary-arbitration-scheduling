# Calcutta High Court Scheduling Scraper Pipeline

This mini-pipeline collects the high/medium-priority inputs needed for the arbitration scheduling demo/report:

1. Daily cause-list captures from eCourts, with human captcha entry.
2. Official Calcutta High Court cause-list PDFs, where available.
3. Orders/judgement result-page captures, with human captcha entry.
4. Parser output: `daily_cause_list.csv`, `bench_roster.csv`, `order_links.csv`, `raw_cause_tables.csv`.

The scraper does **not** automate captcha. You solve captcha manually in the browser, click Go, then press Enter in terminal.

## Install

```bash
pip install playwright beautifulsoup4 requests pandas pyyaml
python -m playwright install chromium

# Optional, only for parsing downloaded cause-list PDFs:
pip install pymupdf
# or:
pip install pypdf
```

## A. Capture eCourts daily cause lists

Use these pages through the scraper:

- Original Side Cause List: `https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/highcourt_causelist.php?dist_cd=1&stateNm=Calcutta&state_cd=16`
- Appellate Side Cause List: `https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/highcourt_causelist.php?court_code=3&dist_cd=1&stateNm=Calcutta&state_cd=16`

Run:

```bash
python scrape_chc_scheduling_inputs.py ecourts-causelist \
  --side appellate \
  --out-dir raw_sched \
  --repeat 5
```

What you do in the browser:

1. Select the cause-list date.
2. Enter captcha.
3. Click Go / Submit.
4. Wait until the cause-list report/table is visible.
5. Press Enter in the terminal.
6. For the next repeat, change the date and repeat.

For Original Side:

```bash
python scrape_chc_scheduling_inputs.py ecourts-causelist \
  --side original \
  --out-dir raw_sched \
  --repeat 5
```

## B. Download official cause-list PDFs

No captcha usually needed.

```bash
python scrape_chc_scheduling_inputs.py official-cause-pdfs \
  --out-dir raw_sched \
  --contains "Daily Cause List" \
  --contains "Appellate Side"
```

For Original Side:

```bash
python scrape_chc_scheduling_inputs.py official-cause-pdfs \
  --out-dir raw_sched \
  --contains "Daily Cause List" \
  --contains "Original Side"
```

## C. Capture orders/judgement result pages

This is medium-priority. Use it after cause-list scraping.

```bash
python scrape_chc_scheduling_inputs.py ecourts-orders \
  --side appellate \
  --out-dir raw_sched \
  --repeat 3
```

What you do in browser:

1. Open Case Orders/Judgement from the left menu if needed.
2. Use Order Date, Court Number/Judge Wise, or Case Number search.
3. Enter captcha.
4. Click Go.
5. Wait until order links/results are visible.
6. Press Enter in terminal.

## D. Parse scraped scheduling inputs

Without PDFs:

```bash
python parse_chc_scheduling_inputs.py \
  --raw-dir raw_sched \
  --out-dir sched_tables
```

With downloaded PDFs:

```bash
python parse_chc_scheduling_inputs.py \
  --raw-dir raw_sched \
  --out-dir sched_tables \
  --parse-pdfs
```

Outputs:

- `sched_tables/daily_cause_list.csv`
- `sched_tables/bench_roster.csv`
- `sched_tables/order_links.csv`
- `sched_tables/raw_cause_tables.csv`
- `sched_tables/official_pdf_links.csv`, if official PDFs were downloaded

## E. How this fits with the existing case-detail parser

Existing scraper/parser gives case-level tables:

- `cases.csv`
- `case_history.csv`
- `acts.csv`
- `orders.csv`
- `objection.csv`
- `advocates.csv`

This scheduling scraper adds schedule-level tables:

- `daily_cause_list.csv`
- `bench_roster.csv`
- `order_links.csv`

Join key:

```text
case_type/case_number/case_year
```

For example:

```text
FMAT/123/2024
AOCOM/45/2025
ADCOM/7/2026
```

