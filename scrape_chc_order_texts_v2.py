#!/usr/bin/env python3
"""
Download Calcutta High Court order PDFs/text from already-scraped eCourts case-detail JSONL files.

Designed for the user's current raw layout:
  output/raw/<year>/<case_type>/calcutta_<year>_<case_type>_<pending|disposed>.jsonl

It does NOT require manually opening Case Orders/Judgement pages. It reuses the order links
embedded in raw_html from the old Case Status scraper.

Outputs:
  <out-dir>/order_manifest.jsonl
  <out-dir>/order_manifest.csv
  <out-dir>/download_errors.csv
  <out-dir>/files/<case_type>/<case_year>/<case_key_slug>/order_*.pdf|html|bin
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://hcservices.ecourts.gov.in/"
DEFAULT_CASE_TYPES = {"FMAT", "AOCOM", "ADCOM"}
DEFAULT_YEARS = {2024, 2025, 2026}


def safe_text(x: Any) -> str:
    if x is None:
        return ""
    x = html.unescape(str(x)).replace("\u00a0", " ").replace("\ufffe", "")
    return re.sub(r"\s+", " ", x).strip()


def slugify(x: str, max_len: int = 140) -> str:
    x = safe_text(x)
    x = re.sub(r"[^A-Za-z0-9_.-]+", "_", x).strip("_")
    return (x[:max_len] or "unknown")


def read_jsonl_files(input_dir: Path) -> Iterable[Tuple[Path, Dict[str, Any]]]:
    for path in sorted(input_dir.rglob("*.jsonl")):
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


def infer_from_path(path: Path) -> Tuple[str, str, str]:
    """Return (year, case_type, status) from paths like raw/2024/FMAT/calcutta_2024_FMAT_disposed.jsonl."""
    s = str(path)
    year = ""
    case_type = ""
    status = ""
    m = re.search(r"(?:^|/)(20\d{2})(?:/|$)", s)
    if m:
        year = m.group(1)
    m = re.search(r"(?:^|/)(FMAT|AOCOM|ADCOM)(?:/|_|$)", s, flags=re.I)
    if m:
        case_type = m.group(1).upper()
    m = re.search(r"_(pending|disposed)\.jsonl$", path.name, flags=re.I)
    if m:
        status = m.group(1).lower()
    return year, case_type, status


def normalize_case_type(raw: str) -> str:
    raw = safe_text(raw).upper()
    for ct in ["AOCOM", "ADCOM", "FMAT"]:
        if re.search(rf"\b{ct}\b", raw):
            return ct
    return ""


def infer_case_type_number_year(rec: Dict[str, Any], source_path: Path) -> Tuple[str, str, str, str, str]:
    """Return case_type, case_no, case_year, case_key, status_filter.

    Prefer actual registration/filing values and source path over old scraper's rec['year']/status_filter,
    because the uploaded raw files contain some stale metadata inside records.
    """
    path_year, path_ct, path_status = infer_from_path(source_path)
    parsed = rec.get("parsed", {}) or {}
    cd = parsed.get("case_details", {}) or {}

    candidates = [
        safe_text(cd.get("Registration Number")),
        safe_text(cd.get("Filing Number")),
        safe_text(rec.get("row_preview")),
        safe_text(parsed.get("text_blob"))[:2500],
    ]
    joined = " | ".join([c for c in candidates if c])

    # Handles:
    #   FMAT (ARBAWARD) /24/2024
    #   FMAT/24/2024
    #   AOCOM / 7 / 2025
    #   ADCOM NO. 8 OF 2026
    pats = [
        r"\b(FMAT|AOCOM|ADCOM)\b(?:\s*\([^)]*\))?\s*/\s*(\d+)\s*/\s*(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\b(?:\s*\([^)]*\))?\s+NO\.?\s*(\d+)\s+OF\s+(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\b(?:\s*\([^)]*\))?\s+(\d+)\s*/\s*(20\d{2})\b",
        r"\b(FMAT|AOCOM|ADCOM)\b(?:\s*\([^)]*\))?\s+(\d+)\s+OF\s+(20\d{2})\b",
    ]
    for pat in pats:
        m = re.search(pat, joined, flags=re.I)
        if m:
            ct, no, yr = m.group(1).upper(), str(int(m.group(2))), m.group(3)
            return ct, no, yr, f"{ct}/{no}/{yr}", path_status or safe_text(rec.get("status_filter")).lower()

    ct = normalize_case_type(joined) or path_ct
    yr = path_year or safe_text(rec.get("year"))
    no = ""
    case_key = f"{ct}/unknown/{yr}" if ct and yr else ""
    return ct, no, yr, case_key, path_status or safe_text(rec.get("status_filter")).lower()


def infer_case_id(rec: Dict[str, Any], case_key: str) -> str:
    parsed = rec.get("parsed", {}) or {}
    cd = parsed.get("case_details", {}) or {}
    for k in ["CNR Number", "Registration Number", "Filing Number"]:
        val = safe_text(cd.get(k))
        if val:
            return val
    return case_key or safe_text(rec.get("row_preview"))[:180]


def extract_urls_from_onclick(onclick: str, base_url: str) -> List[str]:
    out: List[str] = []
    onclick = html.unescape(onclick or "")
    # window.open('...'), window.location='...', viewDoc('...')
    for m in re.finditer(r"['\"]([^'\"]+(?:display_pdf|\.pdf|order|Order|judg|Judg|download|view)[^'\"]*)['\"]", onclick):
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
        urls.extend(extract_urls_from_onclick(tag.get("onclick") or "", base_url))
    seen = set()
    dedup = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup


def find_order_tables(soup: BeautifulSoup) -> List[Any]:
    out = []
    for table in soup.find_all("table"):
        txt = safe_text(table.get_text(" ", strip=True)).lower()
        if "order number" in txt and ("order date" in txt or "order on" in txt) and ("view" in txt or "order details" in txt):
            out.append(table)
    return out


def extract_orders_from_html(raw_html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    rows_out: List[Dict[str, Any]] = []

    for t_index, table in enumerate(find_order_tables(soup), start=1):
        header_seen = False
        headers: List[str] = []
        for tr_index, tr in enumerate(table.find_all("tr"), start=1):
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
            rows_out.append({
                "table_index": t_index,
                "tr_index": tr_index,
                "order_number": vals[0] if len(vals) >= 1 else "",
                "order_on": vals[1] if len(vals) >= 2 else "",
                "judge": vals[2] if len(vals) >= 3 else "",
                "order_date": vals[3] if len(vals) >= 4 else "",
                "order_details_text": vals[4] if len(vals) >= 5 else "",
                "row_text": safe_text(tr.get_text(" | ", strip=True)),
                "urls": urls,
                "headers": headers,
            })

    # Fallback: any likely order/PDF links in the page
    if not rows_out:
        candidates = []
        for u in links_from_node(soup, base_url):
            lu = u.lower()
            if any(k in lu for k in ["display_pdf", "order", "judg", "pdf", "download"]):
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


def choose_extension(content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct or ".pdf" in url.lower() or "display_pdf" in url.lower():
        return ".pdf"
    if "html" in ct:
        return ".html"
    ext = mimetypes.guess_extension(ct.split(";")[0].strip()) if ct else None
    return ext or ".bin"


def download_url(session: requests.Session, url: str, out_path_no_ext: Path, timeout: int = 60) -> Tuple[Path, str, int, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Referer": BASE_URL,
    }
    r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    ext = choose_extension(ct, url)
    out_path = out_path_no_ext.with_suffix(ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return out_path, ct, len(r.content), r.url


def write_csv_from_jsonl(jsonl_path: Path, csv_path: Path) -> None:
    rows = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        csv_path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for r in rows for k in r.keys()})
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-jsonl-dir", required=True, help="Directory containing old raw JSONL files, e.g. output/raw")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--case-types", nargs="*", default=sorted(DEFAULT_CASE_TYPES))
    ap.add_argument("--years", nargs="*", type=int, default=sorted(DEFAULT_YEARS))
    ap.add_argument("--limit", type=int, default=None, help="Limit number of case records processed for testing")
    ap.add_argument("--no-download", action="store_true", help="Only extract order links/metadata, do not download files")
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    input_dir = Path(args.case_jsonl_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files_dir = out_dir / "files"

    wanted_ct = {x.upper() for x in args.case_types}
    wanted_years = {int(y) for y in args.years}

    manifest_path = out_dir / "order_manifest.jsonl"
    errors_path = out_dir / "download_errors.csv"
    session = requests.Session()

    processed_cases = 0
    order_rows = 0
    downloads = 0

    with manifest_path.open("w", encoding="utf-8") as mf, errors_path.open("w", encoding="utf-8", newline="") as ef:
        err_writer = csv.DictWriter(ef, fieldnames=["case_id", "case_key", "source_jsonl", "order_url", "error"])
        err_writer.writeheader()

        for source_path, rec in read_jsonl_files(input_dir):
            ct, no, yr_s, case_key, status_filter = infer_case_type_number_year(rec, source_path)
            if not ct or ct not in wanted_ct:
                continue
            try:
                yr = int(yr_s)
            except Exception:
                continue
            if yr not in wanted_years:
                continue

            processed_cases += 1
            if args.limit is not None and processed_cases > args.limit:
                break

            raw_html = rec.get("raw_html") or ""
            parsed = rec.get("parsed", {}) or {}
            if not raw_html and parsed.get("text_blob"):
                # Metadata only fallback; no links usually possible.
                raw_html = parsed.get("text_blob")

            case_id = infer_case_id(rec, case_key)
            detail_url = safe_text(rec.get("detail_url"))
            orders = extract_orders_from_html(raw_html, BASE_URL)

            if not orders:
                # Still emit a no_orders marker so coverage can be audited.
                row = {
                    "case_id": case_id,
                    "case_key": case_key,
                    "case_type": ct,
                    "case_no": no,
                    "case_year": yr_s,
                    "status_filter": status_filter,
                    "court": safe_text(rec.get("court")),
                    "source_jsonl": str(source_path),
                    "detail_url": detail_url,
                    "order_seq": "",
                    "order_number": "",
                    "order_on": "",
                    "judge": "",
                    "order_date": "",
                    "order_details_text": "",
                    "row_text": "",
                    "order_url": "",
                    "download_status": "no_orders_found",
                    "download_path": "",
                    "content_type": "",
                    "bytes": "",
                    "final_url": "",
                }
                mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                continue

            for i, order in enumerate(orders, start=1):
                urls = order.get("urls") or []
                if not urls:
                    urls = [""]
                for u_idx, url in enumerate(urls, start=1):
                    order_rows += 1
                    base_row = {
                        "case_id": case_id,
                        "case_key": case_key,
                        "case_type": ct,
                        "case_no": no,
                        "case_year": yr_s,
                        "status_filter": status_filter,
                        "court": safe_text(rec.get("court")),
                        "source_jsonl": str(source_path),
                        "detail_url": detail_url,
                        "order_seq": i,
                        "order_number": safe_text(order.get("order_number")),
                        "order_on": safe_text(order.get("order_on")),
                        "judge": safe_text(order.get("judge")),
                        "order_date": safe_text(order.get("order_date")),
                        "order_details_text": safe_text(order.get("order_details_text")),
                        "row_text": safe_text(order.get("row_text")),
                        "order_url": url,
                        "download_status": "",
                        "download_path": "",
                        "content_type": "",
                        "bytes": "",
                        "final_url": "",
                    }
                    if not url:
                        base_row["download_status"] = "no_url"
                        mf.write(json.dumps(base_row, ensure_ascii=False) + "\n")
                        continue
                    if args.no_download:
                        base_row["download_status"] = "link_only"
                        mf.write(json.dumps(base_row, ensure_ascii=False) + "\n")
                        continue

                    try:
                        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
                        case_dir = files_dir / ct / str(yr_s) / slugify(case_key.replace("/", "_"))
                        out_no_ext = case_dir / f"order_{i:03d}_{u_idx:02d}_{h}"
                        path, content_type, nbytes, final_url = download_url(session, url, out_no_ext)
                        base_row.update({
                            "download_status": "downloaded",
                            "download_path": str(path),
                            "content_type": content_type,
                            "bytes": nbytes,
                            "final_url": final_url,
                        })
                        downloads += 1
                        time.sleep(args.sleep)
                    except Exception as e:
                        base_row["download_status"] = "error"
                        err_writer.writerow({
                            "case_id": case_id,
                            "case_key": case_key,
                            "source_jsonl": str(source_path),
                            "order_url": url,
                            "error": str(e),
                        })
                    mf.write(json.dumps(base_row, ensure_ascii=False) + "\n")

    write_csv_from_jsonl(manifest_path, out_dir / "order_manifest.csv")
    print(f"Processed cases: {processed_cases}")
    print(f"Extracted order rows/links: {order_rows}")
    print(f"Downloaded files: {downloads}")
    print(f"Manifest: {manifest_path}")
    print(f"Errors: {errors_path}")


if __name__ == "__main__":
    main()
