#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


@dataclass
class CourtConfig:
    name: str
    label: str
    home_url: str
    high_court_name: str
    benches: List[str]
    preferred_case_type_keywords: List[str]
    years: List[int]
    statuses: List[str]
    max_pages: int
    slow_mo_ms: int
    headless: bool
    captcha_mode: str


def load_config(path: Path, court_name: str) -> CourtConfig:
    cfg = yaml.safe_load(path.read_text())
    defaults = cfg.get("defaults", {})
    court = cfg["courts"][court_name]
    return CourtConfig(
        name=court_name,
        label=court["label"],
        home_url=court["home_url"],
        high_court_name=court["high_court_name"],
        benches=court.get("benches", []),
        preferred_case_type_keywords=court.get("preferred_case_type_keywords", []),
        years=defaults.get("years", [2026]),
        statuses=defaults.get("statuses", ["disposed"]),
        max_pages=int(defaults.get("max_pages", 100)),
        slow_mo_ms=int(defaults.get("slow_mo_ms", 50)),
        headless=bool(defaults.get("headless", False)),
        captcha_mode=str(defaults.get("captcha_mode", "manual")),
    )


def dump_jsonl(records: List[Dict[str, Any]], out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def safe_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def normalize_header(h: str) -> str:
    return safe_text(h).lower().replace(":", "")


def wait_for_manual_results_ready() -> None:
    print(
        "\nIn the browser:\n"
        "1. Open Case Status -> Case Type\n"
        "2. Choose court / bench / case type / year / status\n"
        "3. Solve captcha\n"
        "4. Click Go\n"
        "5. Wait until the results table is visible\n"
        "6. Then press Enter here\n"
    )
    input()


def wait_overlay_to_clear(page: Page, timeout_ms: int = 15000) -> None:
    overlay_candidates = [
        "text=Please Wait",
        "text=Please wait",
        "text=Loading",
    ]
    end_time = time.time() + timeout_ms / 1000.0
    while time.time() < end_time:
        visible = False
        for sel in overlay_candidates:
            try:
                if page.locator(sel).first.is_visible(timeout=150):
                    visible = True
                    break
            except Exception:
                pass
        if not visible:
            return
        page.wait_for_timeout(150)


def find_result_table(page: Page):
    tables = page.locator("table")
    count = tables.count()
    best = None
    best_score = -1

    for i in range(count):
        t = tables.nth(i)
        try:
            txt = safe_text(t.inner_text())
        except Exception:
            continue

        low = txt.lower()
        score = 0
        if "view" in low:
            score += 3
        if "case type" in low:
            score += 2
        if "petitioner" in low or "respondent" in low:
            score += 2
        if "sr no" in low or "case year" in low:
            score += 1

        if score > best_score:
            best_score = score
            best = t

    return best if best_score >= 3 else None


def wait_for_results_table(page: Page, timeout_ms: int = 20000) -> None:
    end_time = time.time() + timeout_ms / 1000.0
    while time.time() < end_time:
        wait_overlay_to_clear(page, timeout_ms=1000)
        try:
            if find_result_table(page) is not None:
                return
        except Exception:
            pass
        page.wait_for_timeout(200)
    raise PlaywrightTimeoutError("Timed out waiting for results table.")


def wait_for_detail_page(page: Page, timeout_ms: int = 20000) -> None:
    detail_candidates = [
        "text=Case Details",
        "text=Case Status",
        "text=History of Case Hearing",
        "text=Orders",
        "text=Document Details",
        "button:has-text('Back')",
        "input[value='Back']",
        "a:has-text('Back')",
        "text=Filing Number",
        "text=CNR Number",
        "text=Registration Number",
    ]
    end_time = time.time() + timeout_ms / 1000.0
    while time.time() < end_time:
        wait_overlay_to_clear(page, timeout_ms=1000)
        hits = 0
        for sel in detail_candidates:
            try:
                if page.locator(sel).first.count() > 0:
                    hits += 1
            except Exception:
                pass
        if hits >= 2:
            return
        page.wait_for_timeout(200)
    raise PlaywrightTimeoutError("Timed out waiting for detail page.")


def scroll_element_into_center(page: Page, locator) -> None:
    try:
        locator.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        handle = locator.element_handle()
        if handle is not None:
            page.evaluate(
                """el => {
                    const r = el.getBoundingClientRect();
                    window.scrollBy(0, r.top - window.innerHeight / 2);
                }""",
                handle,
            )
    except Exception:
        pass
    page.wait_for_timeout(100)


def slow_scroll_page(page: Page, step: int = 700, pause_ms: int = 100) -> None:
    try:
        height = page.evaluate("() => document.body.scrollHeight")
    except Exception:
        return
    y = 0
    while y < height:
        try:
            page.evaluate("(yy) => window.scrollTo(0, yy)", y)
        except Exception:
            break
        page.wait_for_timeout(pause_ms)
        y += step
    page.wait_for_timeout(150)


def slow_scroll_detail_content(page: Page) -> None:
    slow_scroll_page(page, step=900, pause_ms=100)
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(100)
        slow_scroll_page(page, step=1000, pause_ms=80)
    except Exception:
        pass


def parse_key_value_rows(table, skip_title: bool = True) -> Dict[str, str]:
    kv: Dict[str, str] = {}
    rows = table.find_all("tr")

    start_idx = 0
    if skip_title and rows:
        first_cells = rows[0].find_all(["td", "th"])
        first_texts = [safe_text(c.get_text(" ", strip=True)) for c in first_cells if safe_text(c.get_text(" ", strip=True))]
        # If the first row is just a section title row, skip it.
        if len(first_texts) == 1 and len(first_cells) == 1:
            start_idx = 1

    for tr in rows[start_idx:]:
        cells = tr.find_all(["td", "th"])
        texts = [safe_text(c.get_text(" ", strip=True)) for c in cells]
        texts = [t for t in texts if t]

        if not texts:
            continue

        # 2-column KV row
        if len(texts) == 2:
            left = texts[0].rstrip(":")
            if left:
                kv[left] = texts[1]

        # 4-column KV row: k1 v1 k2 v2
        elif len(texts) == 4:
            left1, val1, left2, val2 = texts
            if left1:
                kv[left1.rstrip(":")] = val1
            if left2:
                kv[left2.rstrip(":")] = val2

    return kv


def detect_inline_table_title(table) -> str:
    """
    Many ecourts sections have the section title as the first row of the same table,
    e.g. 'Case Details', 'Case Status', 'Category Details'.
    """
    rows = table.find_all("tr")
    if not rows:
        return ""

    # Check first 2 rows for a single-cell title row
    for tr in rows[:2]:
        cells = tr.find_all(["td", "th"])
        texts = [safe_text(c.get_text(" ", strip=True)) for c in cells if safe_text(c.get_text(" ", strip=True))]
        if len(cells) == 1 and len(texts) == 1:
            return texts[0].lower()

    return ""

def extract_table_dicts(table, skip_title: bool = True) -> List[Dict[str, str]]:
    rows = table.find_all("tr")
    if not rows:
        return []

    start_idx = 0
    if skip_title:
        first_cells = rows[0].find_all(["td", "th"])
        first_texts = [safe_text(c.get_text(" ", strip=True)) for c in first_cells if safe_text(c.get_text(" ", strip=True))]
        if len(first_cells) == 1 and len(first_texts) == 1:
            start_idx = 1

    if start_idx >= len(rows):
        return []

    header_cells = rows[start_idx].find_all(["th", "td"])
    headers = [safe_text(c.get_text(" ", strip=True)) for c in header_cells]
    headers = [h for h in headers if h]
    if not headers:
        return []

    out = []
    for tr in rows[start_idx + 1:]:
        vals = [safe_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        vals = [v for v in vals if v]
        if not vals:
            continue

        if len(vals) == len(headers):
            out.append(dict(zip(headers, vals)))
        else:
            row_dict = {headers[j]: vals[j] if j < len(vals) else "" for j in range(len(headers))}
            out.append(row_dict)

    return out

def extract_orders_rows_strict(table) -> List[Dict[str, str]]:
    expected = [
        "Order Number",
        "Order on",
        "Judge",
        "Order Date",
        "Order Details",
    ]

    rows = table.find_all("tr")
    if not rows:
        return []

    out = []
    header_found = False

    for tr in rows:
        vals = [safe_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        vals = [v for v in vals if v]
        if not vals:
            continue

        low = [v.lower() for v in vals]
        if (
            "order number" in low
            and "order on" in low
            and "judge" in low
            and "order date" in low
        ):
            header_found = True
            continue

        if not header_found:
            continue

        # Typical shape is 5 columns
        if len(vals) < 5:
            vals = vals + [""] * (5 - len(vals))
        elif len(vals) > 5:
            vals = vals[:4] + [" ".join(vals[4:])]

        row = dict(zip(expected, vals))
        out.append(row)

    return out


def extract_objection_rows_strict(table) -> List[Dict[str, str]]:
    expected = [
        "Sr.No.",
        "Scrutiny Date",
        "OBJECTION",
        "OBJECTION Compliance Date",
        "Receipt Date",
    ]

    rows = table.find_all("tr")
    if not rows:
        return []

    out = []
    header_found = False

    for tr in rows:
        vals = [safe_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        vals = [v for v in vals if v]
        if not vals:
            continue

        low = [v.lower() for v in vals]
        if (
            ("sr.no." in low or "sr no" in low or "sr.no" in low)
            and "scrutiny date" in low
            and "objection" in low
        ):
            header_found = True
            continue

        if not header_found:
            continue

        if len(vals) < 5:
            vals = vals + [""] * (5 - len(vals))
        elif len(vals) > 5:
            vals = vals[:4] + [" ".join(vals[4:])]

        row = dict(zip(expected, vals))
        out.append(row)

    return out



def extract_history_rows_strict(table) -> List[Dict[str, str]]:
    expected = [
        "Cause List Type",
        "Judge",
        "Business On Date",
        "Hearing Date",
        "Purpose of hearing",
    ]

    rows = table.find_all("tr")
    if not rows:
        return []

    out = []
    header_found = False

    for tr in rows:
        vals = [safe_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        vals = [v for v in vals if v]
        if not vals:
            continue

        low = [v.lower() for v in vals]
        if (
            "cause list type" in low
            and "judge" in low
            and "business on date" in low
            and "hearing date" in low
        ):
            header_found = True
            continue

        if not header_found:
            continue

        if len(vals) < 5:
            vals = vals + [""] * (5 - len(vals))
        elif len(vals) > 5:
            vals = vals[:4] + [" ".join(vals[4:])]

        row = dict(zip(expected, vals))

        # fix common shift: Hearing Date accidentally contains purpose text
        hd = row["Hearing Date"]
        ph = row["Purpose of hearing"]
        if hd and not re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", hd) and ph == "":
            row["Purpose of hearing"] = hd
            row["Hearing Date"] = ""
        out.append(row)

    return out

def parse_single_row_block(table) -> Dict[str, str]:
    text = safe_text(table.get_text("\n", strip=True))
    lines = [x for x in [safe_text(l) for l in text.split("\n")] if x]
    return {"raw_block_text": " | ".join(lines)}


def classify_table(headers: List[str], table_text: str) -> str:
    hs = {normalize_header(h) for h in headers}
    low = table_text.lower()

    history_markers = {
        "cause list type",
        "judge",
        "business on date",
        "hearing date",
        "purpose of hearing",
        "next date",
    }

    ia_markers = {
        "ia number",
        "party",
        "date of filing",
        "next date",
        "ia status",
    }

    order_markers = {
        "order number",
        "order on",
        "order date",
        "order details",
    }

    document_markers = {
        "document no.",
        "date of receiving",
        "filed by",
        "name of advocate",
        "document filed",
    }

    objection_markers = {
        "scrutiny date",
        "objection",
        "objection compliance date",
        "receipt date",
    }

    subordinate_markers = {
        "court number and name",
        "case number and year",
        "case decision date",
        "state",
        "district",
    }

    category_markers = {"category", "sub category"}
    acts_markers = {"under act(s)", "under section(s)"}

    if "history of case hearing" in low or len(hs.intersection(history_markers)) >= 2:
        return "history"
    if "ia details" in low or len(hs.intersection(ia_markers)) >= 2:
        return "ia_details"
    if "orders" in low or len(hs.intersection(order_markers)) >= 2:
        return "orders"
    if "document details" in low or len(hs.intersection(document_markers)) >= 2:
        return "document_details"
    if "objection" in low and len(hs.intersection(objection_markers)) >= 2:
        return "objection"
    if "subordinate court information" in low or len(hs.intersection(subordinate_markers)) >= 2:
        return "subordinate_court_information"
    if "category details" in low or len(hs.intersection(category_markers)) >= 1:
        return "category_details"
    if "acts" in low or len(hs.intersection(acts_markers)) >= 1:
        return "acts"
    if "petitioner and advocate" in low:
        return "petitioner_advocate"
    if "respondent and advocate" in low:
        return "respondent_advocate"
    if "case details" in low:
        return "case_details"
    if "case status" in low:
        return "case_status"
    return "other"


def parse_detail_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    all_tables = soup.find_all("table")

    parsed: Dict[str, Any] = {
        "case_details": {},
        "case_status": {},
        "petitioners": [],
        "respondents": [],
        "acts": [],
        "category_details": {},
        "subordinate_court_information": {},
        "ia_details": [],
        "history": [],
        "orders": [],
        "document_details": [],
        "objection": [],
        "other_tables": [],
        "kv": {},
    }

    for idx, table in enumerate(all_tables):
        table_text = safe_text(table.get_text(" ", strip=True))
        table_low = table_text.lower()
        inline_title = detect_inline_table_title(table)

        headers = [safe_text(th.get_text(" ", strip=True)) for th in table.find_all("th")]
        headers_low = {normalize_header(h) for h in headers}

        kv_rows = parse_key_value_rows(table, skip_title=True)
        extracted = extract_table_dicts(table, skip_title=True)

        listing_markers = {
            "sr no",
            "case type / case number / case year",
            "petitioner name versus respondent name",
            "view",
        }
        if len(headers_low.intersection(listing_markers)) >= 2:
            continue

        # Case Details
        if inline_title == "case details" or (
            kv_rows and {"filing number", "registration number", "cnr number"}.intersection({normalize_header(k) for k in kv_rows})
        ):
            parsed["case_details"].update(kv_rows)
            parsed["kv"].update(kv_rows)
            continue

        # Case Status
        if inline_title == "case status" or (
            kv_rows and {"first hearing date", "stage of case", "coram", "bench type"}.intersection({normalize_header(k) for k in kv_rows})
        ):
            parsed["case_status"].update(kv_rows)
            parsed["kv"].update(kv_rows)
            continue

        # Category Details
        if inline_title == "category details" or (
            kv_rows and {"category", "sub category"}.intersection({normalize_header(k) for k in kv_rows})
        ):
            parsed["category_details"].update(kv_rows)
            continue

        # Subordinate Court Information
        if inline_title == "subordinate court information" or (
            kv_rows and {"court number and name", "case number and year", "case decision date"}.intersection({normalize_header(k) for k in kv_rows})
        ):
            parsed["subordinate_court_information"].update(kv_rows)
            continue

        # Petitioner and Advocate
        if inline_title == "petitioner and advocate":
            if extracted:
                parsed["petitioners"].extend(extracted)
            elif kv_rows:
                parsed["petitioners"].append(kv_rows)
            else:
                parsed["petitioners"].append({"raw_block_text": table_text})
            continue

        # Respondent and Advocate
        if inline_title == "respondent and advocate":
            if extracted:
                parsed["respondents"].extend(extracted)
            elif kv_rows:
                parsed["respondents"].append(kv_rows)
            else:
                parsed["respondents"].append({"raw_block_text": table_text})
            continue

        # Acts
        if inline_title == "acts" or "under act(s)" in table_low or "under section(s)" in table_low:
            if extracted:
                parsed["acts"].extend(extracted)
            elif kv_rows:
                parsed["acts"].append(kv_rows)
            continue

        # IA Details
        if inline_title == "ia details" or {"ia number", "party", "date of filing", "ia status"}.intersection(headers_low):
            if extracted:
                parsed["ia_details"].extend(extracted)
            continue

        # History of Case Hearing
        if inline_title == "history of case hearing" or (
            {"cause list type", "judge", "business on date", "hearing date"}.intersection(headers_low)
        ):
            hist = extract_history_rows_strict(table)
            if hist:
                parsed["history"].extend(hist)
            elif extracted:
                parsed["history"].extend(extracted)
            continue

        # Orders
        if inline_title == "orders" or {"order number", "order on", "judge", "order date", "order details"}.intersection(headers_low):
            rows = extract_orders_rows_strict(table)
            if rows:
                parsed["orders"].extend(rows)
            elif extracted:
                parsed["orders"].extend(extracted)
            continue

        # Document Details
        if inline_title == "document details" or {"document no.", "date of receiving", "filed by", "name of advocate", "document filed"}.intersection(headers_low):
            if extracted:
                parsed["document_details"].extend(extracted)
            continue

        # Objection
        if inline_title == "objection" or {"scrutiny date", "objection", "objection compliance date", "receipt date"}.intersection(headers_low):
            rows = extract_objection_rows_strict(table)
            if rows:
                parsed["objection"].extend(rows)
            elif extracted:
                parsed["objection"].extend(extracted)
            continue

        # Fallback
        if extracted or kv_rows:
            parsed["other_tables"].append(
                {
                    "table_index": idx,
                    "inline_title": inline_title,
                    "headers": headers,
                    "kv_rows": kv_rows,
                    "rows": extracted,
                    "table_text": table_text[:1500],
                }
            )

    merged_kv = {}
    merged_kv.update(parsed["case_details"])
    merged_kv.update(parsed["case_status"])

    if parsed["category_details"]:
        merged_kv.update({f"Category::{k}": v for k, v in parsed["category_details"].items()})

    if parsed["subordinate_court_information"]:
        merged_kv.update({f"Subordinate::{k}": v for k, v in parsed["subordinate_court_information"].items()})

    parsed["kv"].update(merged_kv)
    parsed["text_blob"] = soup.get_text("\n", strip=True)
    return parsed


def detail_marker_score(page: Page, parsed: Dict[str, Any]) -> Tuple[int, List[str]]:
    body_text = safe_text(page.inner_text("body"))
    body_low = body_text.lower()

    case_details = parsed.get("case_details", {})
    case_status = parsed.get("case_status", {})

    checks = {
        "case_details_text": "case details" in body_low,
        "case_status_text": "case status" in body_low,
        "history_of_case_hearing_text": "history of case hearing" in body_low,
        "orders_text": "orders" in body_low,
        "document_details_text": "document details" in body_low,
        "back_button": any(
            [
                page.locator("button:has-text('Back')").count() > 0,
                page.locator("input[value='Back']").count() > 0,
                page.locator("a:has-text('Back')").count() > 0,
            ]
        ),
        "filing_number": bool(case_details.get("Filing Number")),
        "registration_number": bool(case_details.get("Registration Number")),
        "cnr_number": bool(case_details.get("CNR Number")),
        "first_hearing_date": bool(case_status.get("First Hearing Date")),
        "stage_of_case": bool(case_status.get("Stage of Case")),
        "coram": bool(case_status.get("Coram")),
        "history_rows": len(parsed.get("history", [])) > 0,
    }

    matched = [k for k, v in checks.items() if v]
    return len(matched), matched


def assert_real_detail_page(page: Page, parsed: Dict[str, Any]) -> None:
    score, matched = detail_marker_score(page, parsed)
    body_text = safe_text(page.inner_text("body")).lower()

    listing_markers = [
        "total number of cases",
        "petitioner name versus respondent name",
        "select case type",
    ]
    listing_hits = sum(m in body_text for m in listing_markers)

    if listing_hits >= 2 and score < 5 and len(parsed.get("history", [])) == 0:
        raise RuntimeError(f"Refusing to save listing page. detail_score={score}, matched={matched}")

    case_details = parsed.get("case_details", {})
    has_core_kv = any(
        [
            bool(case_details.get("Filing Number")),
            bool(case_details.get("Registration Number")),
            bool(case_details.get("CNR Number")),
        ]
    )

    if not has_core_kv and score < 4:
        raise RuntimeError(f"Not a real detail page. detail_score={score}, matched={matched}")


def get_case_key(parsed: Dict[str, Any], fallback: str) -> str:
    case_details = parsed.get("case_details", {})
    candidates = [
        case_details.get("CNR Number"),
        case_details.get("Registration Number"),
        case_details.get("Filing Number"),
        parsed.get("kv", {}).get("CNR Number"),
        fallback,
    ]
    for c in candidates:
        c = safe_text(c)
        if c:
            return c
    return fallback


def click_back_to_results(page: Page) -> None:
    back_selectors = [
        "button:has-text('Back')",
        "input[value='Back']",
        "a:has-text('Back')",
        "text=Back",
    ]

    clicked = False
    for sel in back_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                scroll_element_into_center(page, loc.first)
                loc.first.click(timeout=4000)
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        page.go_back(wait_until="domcontentloaded")

    wait_overlay_to_clear(page, timeout_ms=15000)
    wait_for_results_table(page, timeout_ms=15000)
    page.wait_for_timeout(1200)


def collect_result_rows(page: Page) -> List[Tuple[int, str]]:
    table = find_result_table(page)
    if table is None:
        raise RuntimeError("Could not find results table for row collection.")

    row_locator = table.locator("tr")
    row_count = row_locator.count()

    rows: List[Tuple[int, str]] = []
    for i in range(row_count):
        row = row_locator.nth(i)
        try:
            txt = safe_text(row.inner_text())
        except Exception:
            continue
        if not txt:
            continue
        if "view" not in txt.lower():
            continue
        if "case type" in txt.lower() and "petitioner" in txt.lower():
            continue
        rows.append((i, txt[:500]))
    return rows


def get_view_button_for_row(page: Page, row_index: int):
    table = find_result_table(page)
    if table is None:
        raise RuntimeError("Could not find results table while reacquiring row.")
    row = table.locator("tr").nth(row_index)

    candidates = [
        row.locator("input[value='View']"),
        row.locator("button:has-text('View')"),
        row.locator("a:has-text('View')"),
    ]
    for loc in candidates:
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    raise RuntimeError(f"No View button found for row index {row_index}.")


def scrape_current_results_page(
    page: Page,
    court_cfg: CourtConfig,
    year: int,
    status: str,
    records: List[Dict[str, Any]],
    seen_case_keys: set,
) -> int:
    wait_for_results_table(page)
    wait_overlay_to_clear(page)

    rows = collect_result_rows(page)
    print(f"Found {len(rows)} row(s) on current results page.")

    scraped_now = 0

    for row_index, row_preview in rows:
        try:
            wait_overlay_to_clear(page)
            wait_for_results_table(page)

            view_btn = get_view_button_for_row(page, row_index)
            scroll_element_into_center(page, view_btn)
            view_btn.click(timeout=5000)

            wait_overlay_to_clear(page, timeout_ms=20000)
            wait_for_detail_page(page, timeout_ms=20000)

            # Extra settle time so late-rendered sections fully appear.
            page.wait_for_timeout(2000)

            # Scroll through the full page so all tables get rendered.
            slow_scroll_detail_content(page)

            # Small extra wait after scroll for lazy/delayed DOM updates.
            page.wait_for_timeout(500)

            detail_html = page.content()
            parsed = parse_detail_html(detail_html)

            try:
                assert_real_detail_page(page, parsed)
            except Exception:
                # One retry after extra settle time
                page.wait_for_timeout(1200)
                slow_scroll_detail_content(page)
                page.wait_for_timeout(500)
                detail_html = page.content()
                parsed = parse_detail_html(detail_html)
                assert_real_detail_page(page, parsed)

            key = get_case_key(parsed, fallback=f"row_{row_index}_{int(time.time())}")

            if key not in seen_case_keys:
                seen_case_keys.add(key)
                records.append(
                    {
                        "court": court_cfg.name,
                        "year": year,
                        "status_filter": status,
                        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "detail_url": page.url,
                        "row_preview": row_preview,
                        "parsed": parsed,
                        "raw_html": detail_html,
                    }
                )
                scraped_now += 1
                print(f"Saved record {len(records)}: {key}")
            else:
                print(f"Skipping duplicate: {key}")

            click_back_to_results(page)

        except Exception as e:

            print(f"Skipping row index {row_index}: {e}")
            try:
                debug_dir = Path("output/debug_failed_rows")
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_file = debug_dir / f"{court_cfg.name}_{year}_{status}_row_{row_index}.html"
                debug_file.write_text(page.content(), encoding="utf-8")
            except Exception:
                pass

    return scraped_now


def maybe_click_next(page: Page) -> bool:
    selectors = [
        "a:has-text('Next')",
        "button:has-text('Next')",
        "text=Next",
        "text=>",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            scroll_element_into_center(page, loc.first)
            loc.first.click(timeout=4000)
            wait_overlay_to_clear(page, timeout_ms=15000)
            wait_for_results_table(page, timeout_ms=15000)
            page.wait_for_timeout(300)
            return True
        except Exception:
            continue
    return False


def scrape_case_results(page: Page, court_cfg: CourtConfig, year: int, status: str, out_dir: Path) -> Path:
    page.goto(court_cfg.home_url, wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    wait_for_manual_results_ready()

    records: List[Dict[str, Any]] = []
    seen_case_keys = set()

    wait_for_results_table(page, timeout_ms=30000)
    wait_overlay_to_clear(page, timeout_ms=20000)

    page_no = 1
    while page_no <= court_cfg.max_pages:
        print(f"\nScraping results page {page_no}...")
        scraped_now = scrape_current_results_page(page, court_cfg, year, status, records, seen_case_keys)

        if scraped_now == 0:
            print("No new valid detail records scraped on this page.")

        if not maybe_click_next(page):
            break
        page_no += 1

    out_file = out_dir / f"{court_cfg.name}_{year}_{status}.jsonl"
    if not records:
        print(f"No rows found or no valid detail pages detected. Writing empty file: {out_file}")
    dump_jsonl(records, out_file)
    return out_file


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--court", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--statuses", nargs="*", default=None)
    args = ap.parse_args()

    court_cfg = load_config(Path(args.config), args.court)
    if args.statuses:
        court_cfg.statuses = args.statuses

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=court_cfg.headless,
            slow_mo=court_cfg.slow_mo_ms,
        )
        context = browser.new_context()
        page = context.new_page()

        for year in court_cfg.years:
            for status in court_cfg.statuses:
                try:
                    print(f"\n=== {court_cfg.name=} {year=} {status=} ===")
                    out_file = scrape_case_results(page, court_cfg, year, status, out_dir)
                    print(f"Saved: {out_file}")
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"Failed for {court_cfg.name=} {year=} {status=}: {e}", file=sys.stderr)

        context.close()
        browser.close()


if __name__ == "__main__":
    main()