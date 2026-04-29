#!/usr/bin/env python3
"""
Scrape/download Calcutta High Court order documents for already-scraped case detail JSONL files.

Primary use case:
  You already scraped Appellate Side FMAT/AOCOM/ADCOM pending/disposed cases using
  scrape_ecourts_2026.py. Those JSONL records include raw_html for the detail page.
  This script extracts the order-table links from that raw_html and downloads the
  linked order/judgement PDFs/HTML files.

Human work required:
  None, if the order links are present in raw_html and publicly downloadable.
  If no links are present, re-run the old case-detail scraper with raw_html enabled.

Outputs:
  out-dir/order_manifest.jsonl
  out-dir/order_manifest.csv
  out-dir/files/<case_type>/<case_year>/<case_key_slug>/order_*.pdf|html|bin
  out-dir/download_errors.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://hcservices.ecourts.gov.in/"
DEFAULT_CASE_TYPES = {"FMAT", "AOCOM", "ADCOM"}
DEFAULT_YEARS = {2024, 2025, 2026}


def safe_text(x: Any) -> str:
    if x is None:
        return ""
    x = html.unescape(str(x)).replace("\u00a0", " ").replace("\ufffe", "")
    return re.sub(r"\s+", " ", x).strip()


def slugify(x: str, max_len: int = 120) -> str:
    x = safe_text(x)
    x = re.sub(r"[^A-Za-z0-9_.-]+", "_", x).strip("_")
    return (x[:max_len] or "unknown")


def read_jsonl_files(input_dir: Path) -> Iterable[Tuple[Path, Dict[str, Any]]]:
    for path in sorted(input_dir.rglob("*.jsonl")):
        # ignore macOS metadata if zip was extracted on macOS
        if "__MACOSX" in path.parts or path.name.startswith("._"):
            continue
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield path, json.loads(line)
                except Exception as e:
                    print(f"WARN: bad JSON {path}:{line_no}: {e}", file=sys.stderr)


def infer_case_type_number_year(rec: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """Return case_type, case_no, case_year, case_key from parsed fields or row text."""
    parsed = rec.get("parsed", {}) or {}
    case_details = parsed.get("case_details", {}) or {}
    candidates = [
        safe_text(case_details.get("Registration Number")),
        safe_text(case_details.get("Filing Number")),
        safe_text(case_details.get("CNR Number")),
        safe_text(rec.get("row_preview")),
        safe_text(parsed.get("text_blob"))[:2000],
    ]
    joined = " | ".join([c for c in candidates if c])

    # Common forms: FMAT/345/2024, FMAT 345/2024, FMAT 345 of 2024
    pats = [
        r"\b(FMAT|AOCOM|ADCOM)\s*/\s*(\d+)\s*/\s*(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\s+NO\.?\s*(\d+)\s+OF\s+(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\s+(\d+)\s*/\s*(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\s+(\d+)\s+OF\s+(20\d{2})\b",
    ]
    for pat in pats:
        m = re.search(pat, joined, flags=re.I)
        if m:
            ct, no, yr = m.group(1).upper(), m.group(2), m.group(3)
            return ct, no, yr, f"{ct}/{int(no)}/{yr}"

    # Sometimes the scraper folder/file has year and the row preview has case type.
    year = str(rec.get("year") or "")
    mct = re.search(r"\b(FMAT|AOCOM|ADCOM)\b", joined, flags=re.I)
    if mct and re.fullmatch(r"20\d{2}", year):
        ct = mct.group(1).upper()
        return ct, "", year, f"{ct}/unknown/{year}"

    return "", "", year, ""


def infer_case_id(rec: Dict[str, Any], case_key: str) -> str:
    parsed = rec.get("parsed", {}) or {}
    case_details = parsed.get("case_details", {}) or {}
    for k in ["CNR Number", "Registration Number", "Filing Number"]:
        val = safe_text(case_details.get(k))
        if val:
            return val
    return case_key or safe_text(rec.get("row_preview"))[:180]


def extract_url_from_onclick(onclick: str, base_url: str) -> List[str]:
    out: List[str] = []
    if not onclick:
        return out
    onclick = html.unescape(onclick)
    # window.open('...'), window.location='...', ViewDocument('...') etc.
    for m in re.finditer(r"['\"]([^'\"]+(?:\.pdf|order|Order|judg|Judg|display|download|view)[^'\"]*)['\"]", onclick):
        u = m.group(1).strip()
        if u and not u.lower().startswith("javascript"):
            out.append(urljoin(base_url, u))
    return out


def links_from_node(node, base_url: str) -> List[str]:
    urls: List[str] = []
    if node is None:
        return urls
    for tag in node.find_all(["a", "button", "input", "iframe"], recursive=True):
        for attr in ["href", "src", "data-url", "data-href"]:
            val = tag.get(attr)
            if val:
                urls.append(urljoin(base_url, html.unescape(val)))
        onclick = tag.get("onclick") or ""
        urls.extend(extract_url_from_onclick(onclick, base_url))
    # Deduplicate keeping order
    seen = set(); dedup = []
    for u in urls:
        if u and u not in seen:
            seen.add(u); dedup.append(u)
    return dedup


def find_order_tables(soup: BeautifulSoup) -> List[Any]:
    tables = []
    for table in soup.find_all("table"):
        txt = safe_text(table.get_text(" ", strip=True)).lower()
        if (
            "order number" in txt
            and ("order date" in txt or "date" in txt)
            and ("order details" in txt or "view" in txt or "order on" in txt)
        ):
            tables.append(table)
    return tables


def extract_orders_from_html(raw_html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    rows_out: List[Dict[str, Any]] = []
    order_tables = find_order_tables(soup)

    for t_index, table in enumerate(order_tables, start=1):
        trs = table.find_all("tr")
        header_seen = False
        headers: List[str] = []
        for tr_index, tr in enumerate(trs, start=1):
            cells = tr.find_all(["th", "td"])
            vals = [safe_text(c.get_text(" ", strip=True)) for c in cells]
            vals = [v for v in vals if v]
            low = [v.lower() for v in vals]
            if not vals:
                continue
            if "order number" in low and ("order date" in low or "order on" in low):
                headers = vals
                header_seen = True
                continue
            if not header_seen:
                continue

            urls = links_from_node(tr, base_url)
            # Be conservative: keep row even if URL missing, useful as metadata.
            row_text = safe_text(tr.get_text(" | ", strip=True))
            order_number = vals[0] if len(vals) >= 1 else ""
            order_on = vals[1] if len(vals) >= 2 else ""
            judge = vals[2] if len(vals) >= 3 else ""
            order_date = vals[3] if len(vals) >= 4 else ""
            order_details = vals[4] if len(vals) >= 5 else ""
            rows_out.append({
                "table_index": t_index,
                "tr_index": tr_index,
                "order_number": order_number,
                "order_on": order_on,
                "judge": judge,
                "order_date": order_date,
                "order_details_text": order_details,
                "row_text": row_text,
                "urls": urls,
                "headers": headers,
            })

    # Fallback: scan all links with likely order/judgement/pdf names.
    if not rows_out:
        candidates = []
        for u in links_from_node(soup, base_url):
            lu = u.lower()
            if any(k in lu for k in ["order", "judg", "pdf", "display", "download"]):
                candidates.append(u)
        for idx, u in enumerate(candidates, start=1):
            rows_out.append({
                "table_index": "fallback",
                "tr_index": idx,
                "order_number": "",
                "order_on": "",
                "judge": "",
                "order_date": "",
                "order_details_text": "",
                "row_text": "",
                "urls": [u],
                "headers": [],
            })

    return rows_out


def guess_ext(resp: requests.Response, url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return ".pdf"
    ct = (resp.headers.get("content-type") or "").lower().split(";")[0].strip()
    if "pdf" in ct:
        return ".pdf"
    if "html" in ct:
        return ".html"
    ext = mimetypes.guess_extension(ct) or ""
    return ext if ext else ".bin"


def download_file(session: requests.Session, url: str, out_path_base: Path, timeout: int = 45) -> Tuple[str, str, int, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome Safari",
        "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    status = resp.status_code
    ct = resp.headers.get("content-type", "")
    if status >= 400:
        raise RuntimeError(f"HTTP {status} content-type={ct}")
    ext = guess_ext(resp, url)
    out_path = out_path_base.with_suffix(ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return str(out_path), ct, len(resp.content), resp.url


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-jsonl-dir", required=True, help="Directory containing old eCourts case-detail JSONL files.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--case-types", nargs="+", default=sorted(DEFAULT_CASE_TYPES))
    ap.add_argument("--years", nargs="+", type=int, default=sorted(DEFAULT_YEARS))
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--no-download", action="store_true", help="Only extract order links/metadata; do not download files.")
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0, help="Debug limit on records processed.")
    args = ap.parse_args()

    input_dir = Path(args.case_jsonl_dir)
    out_dir = Path(args.out_dir)
    files_dir = out_dir / "files"
    out_dir.mkdir(parents=True, exist_ok=True)

    case_types = {x.upper() for x in args.case_types}
    years = set(args.years)

    manifest_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    session = requests.Session()
    processed_cases = 0
    extracted_orders = 0
    downloaded = 0

    for source_path, rec in read_jsonl_files(input_dir):
        ct, no, yr_s, case_key = infer_case_type_number_year(rec)
        try:
            yr = int(yr_s) if yr_s else None
        except Exception:
            yr = None
        if ct not in case_types:
            continue
        if yr not in years:
            continue
        raw_html = rec.get("raw_html") or ""
        if not raw_html:
            continue

        processed_cases += 1
        if args.limit and processed_cases > args.limit:
            break

        case_id = infer_case_id(rec, case_key)
        status_filter = safe_text(rec.get("status_filter"))
        court = safe_text(rec.get("court"))
        detail_url = safe_text(rec.get("detail_url"))
        base_url = detail_url or args.base_url
        orders = extract_orders_from_html(raw_html, base_url=base_url)

        for oi, order in enumerate(orders, start=1):
            extracted_orders += 1
            urls = order.get("urls") or []
            if not urls:
                manifest_rows.append({
                    "case_id": case_id,
                    "case_key": case_key,
                    "case_type": ct,
                    "case_no": no,
                    "case_year": yr_s,
                    "status_filter": status_filter,
                    "court": court,
                    "source_jsonl": str(source_path),
                    "detail_url": detail_url,
                    "order_seq": oi,
                    "order_number": order.get("order_number", ""),
                    "order_on": order.get("order_on", ""),
                    "judge": order.get("judge", ""),
                    "order_date": order.get("order_date", ""),
                    "order_details_text": order.get("order_details_text", ""),
                    "row_text": order.get("row_text", ""),
                    "order_url": "",
                    "download_path": "",
                    "download_status": "no_url",
                    "content_type": "",
                    "bytes": "",
                    "final_url": "",
                })
                continue

            for ui, url in enumerate(urls, start=1):
                url_hash = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:10]
                base_name = f"order_{oi:03d}_{ui:02d}_{url_hash}"
                case_dir = files_dir / ct / str(yr_s) / slugify(case_key.replace('/', '_'))
                download_path = ""
                status = "link_only"
                content_type = ""
                nbytes: Any = ""
                final_url = ""
                if not args.no_download:
                    try:
                        download_path, content_type, nbytes, final_url = download_file(
                            session, url, case_dir / base_name
                        )
                        status = "downloaded"
                        downloaded += 1
                        time.sleep(args.sleep)
                    except Exception as e:
                        status = "error"
                        error_rows.append({
                            "case_key": case_key,
                            "case_id": case_id,
                            "order_url": url,
                            "error": str(e),
                            "source_jsonl": str(source_path),
                        })

                manifest_rows.append({
                    "case_id": case_id,
                    "case_key": case_key,
                    "case_type": ct,
                    "case_no": no,
                    "case_year": yr_s,
                    "status_filter": status_filter,
                    "court": court,
                    "source_jsonl": str(source_path),
                    "detail_url": detail_url,
                    "order_seq": oi,
                    "order_number": order.get("order_number", ""),
                    "order_on": order.get("order_on", ""),
                    "judge": order.get("judge", ""),
                    "order_date": order.get("order_date", ""),
                    "order_details_text": order.get("order_details_text", ""),
                    "row_text": order.get("row_text", ""),
                    "order_url": url,
                    "download_path": download_path,
                    "download_status": status,
                    "content_type": content_type,
                    "bytes": nbytes,
                    "final_url": final_url,
                })

    # Write JSONL + CSV manifest
    jsonl_path = out_dir / "order_manifest.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in manifest_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_csv(out_dir / "order_manifest.csv", manifest_rows)
    write_csv(out_dir / "download_errors.csv", error_rows)

    print(f"Processed cases: {processed_cases}")
    print(f"Extracted order rows/links: {extracted_orders}")
    print(f"Downloaded files: {downloaded}")
    print(f"Manifest: {jsonl_path}")
    print(f"Errors: {out_dir / 'download_errors.csv'}")


if __name__ == "__main__":
    main()
