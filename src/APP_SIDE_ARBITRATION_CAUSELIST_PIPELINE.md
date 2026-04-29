# Appellate Side Arbitration Cause-List Pipeline

This is the lighter pipeline for the current scope: **Calcutta High Court Appellate Side only**, and only arbitration-related case types already curated in the old scraper: `FMAT`, `AOCOM`, `ADCOM`.

## Main idea

Do not enter 365 daily dates manually in eCourts.

Instead:

1. Crawl the official Calcutta High Court **Notices -> Cause list related** archive.
2. Download only **Appellate Side** cause-list PDFs.
3. Parse the PDFs.
4. Keep only rows containing `FMAT`, `AOCOM`, or `ADCOM`.
5. Join the resulting `case_key` with the older case-detail parser tables.

## Website location

Use the official notice archive:

```text
https://www.calcuttahighcourt.gov.in/Notices/CL
```

This page lists cause-list related PDFs such as Daily Cause List and Supplementary Cause List for the Appellate Side.

You can verify the same category through:

```text
https://www.calcuttahighcourt.gov.in/Cause-Lists
```

But for bulk collection, the notice archive route is easier.

## Install

```bash
pip install requests beautifulsoup4 pandas pymupdf
```

If `pymupdf` causes issues:

```bash
pip install pypdf
```

## Step 1: Download Appellate Side cause-list PDFs

For 2024-2026:

```bash
python scrape_chc_appellate_arbitration_pdfs.py \
  --start-date 2024-01-01 \
  --end-date 2026-12-31 \
  --out-dir raw_appellate_cl \
  --max-pages 250 \
  --download
```

Outputs:

```text
raw_appellate_cl/notice_links.csv
raw_appellate_cl/notice_links.jsonl
raw_appellate_cl/pdfs/*.pdf
```

If the archive pagination is shorter/longer, adjust:

```bash
--max-pages 100
--max-pages 500
```

## Step 2: Parse only FMAT/AOCOM/ADCOM rows

```bash
python parse_appellate_arbitration_causelists.py \
  --pdf-dir raw_appellate_cl/pdfs \
  --out-dir sched_tables \
  --case-types FMAT AOCOM ADCOM
```

Outputs:

```text
sched_tables/appellate_arbitration_cause_list.csv
sched_tables/bench_roster_from_pdfs.csv
sched_tables/pdf_text_index.csv
```

## Step 3: Join with old case-detail parser output

Old parser output gives case metadata and case history:

```text
cases.csv
case_history.csv
orders.csv
acts.csv
advocates.csv
objection.csv
```

New parser output gives actual listed cause-list entries:

```text
appellate_arbitration_cause_list.csv
bench_roster_from_pdfs.csv
```

The useful join key format is:

```text
FMAT/123/2024
AOCOM/45/2025
ADCOM/7/2026
```

This appears as `case_key` in the new output.

## Human work needed

For this cause-list pipeline: usually **none**.

You still need captcha only for the old eCourts case-detail scraper, but not for 365 daily cause-list dates.

## Why this is enough for the demo

The output gives:

- actual Appellate Side arbitration matters listed on specific dates,
- court number / bench / coram where extractable,
- list type: daily or supplementary,
- case key and surrounding context,
- bench roster proxy from PDF headers.

This is enough to compare:

- actual historical listing pattern,
- age-based hypothetical scheduling,
- gap-since-last-hearing scheduling,
- case-type balance across FMAT/AOCOM/ADCOM,
- bench/coram load concentration.
