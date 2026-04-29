#!/usr/bin/env python3
"""
scrape_chc_scheduling_inputs.py

Human-captcha assisted scraper for Calcutta High Court scheduling inputs.

It intentionally avoids captcha automation. The human opens the required page,
selects options / enters captcha / clicks Go, then presses Enter in terminal.
The script captures the rendered result page, all visible tables, links and
option lists into JSONL/HTML, so a parser can normalize it later.

Modes:
  1) ecourts-causelist: capture eCourts Cause List Report pages.
  2) ecourts-orders: capture eCourts Case Orders/Judgement result pages.
  3) official-cause-pdfs: download cause-list PDFs from calcuttahighcourt.gov.in.
  4) capture-page: generic manual page capture for roster/determination/calendar.

Examples:
  python scrape_chc_scheduling_inputs.py ecourts-causelist --side appellate --out-dir raw_sched
  python scrape_chc_scheduling_inputs.py ecourts-orders --side original --out-dir raw_sched
  python scrape_chc_scheduling_inputs.py official-cause-pdfs --out-dir raw_sched --contains "Daily Cause List" --contains "Appellate Side"
  python scrape_chc_scheduling_inputs.py capture-page --url https://www.calcuttahighcourt.gov.in/Cause-Lists --label cause_lists --out-dir raw_sched
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

EC_URLS = {
    "original": "https://hcservices.ecourts.gov.in/ecourtindiaHC/index_highcourt.php?dist_cd=1&stateNm=Calcutta&state_cd=16",
    "appellate": "https://hcservices.ecourts.gov.in/ecourtindiaHC/index_highcourt.php?court_code=3&dist_cd=1&stateNm=Calcutta&state_cd=16",
    "original_causelist": "https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/highcourt_causelist.php?dist_cd=1&stateNm=Calcutta&state_cd=16",
    "appellate_causelist": "https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/highcourt_causelist.php?court_code=3&dist_cd=1&stateNm=Calcutta&state_cd=16",
}

OFFICIAL_CAUSE_URLS = [
    "https://www.calcuttahighcourt.gov.in/Cause-Lists",
    "https://www.calcuttahighcourt.gov.in/Notices/CL",
]


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def file_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def safe_text(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def slug(s: str, max_len: int = 80) -> str:
    s = safe_text(s).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s[:max_len] or "page")


def dump_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_tables_from_html(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for ti, table in enumerate(soup.find_all("table")):
        rows = []
        headers: List[str] = []
        trs = table.find_all("tr")
        for ri, tr in enumerate(trs):
            cells = tr.find_all(["th", "td"])
            vals = [safe_text(c.get_text(" ", strip=True)) for c in cells]
            vals = [v for v in vals if v]
            if not vals:
                continue
            if not headers and (tr.find_all("th") or ri == 0):
                headers = vals
            else:
                rows.append(vals)
        text = safe_text(table.get_text(" ", strip=True))
        out.append({"table_index": ti, "headers": headers, "rows": rows, "table_text": text[:5000]})
    return out


def extract_links_from_html(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = safe_text(a.get_text(" ", strip=True))
        href = urljoin(base_url, a.get("href"))
        links.append({"text": text, "href": href})
    return links


def extract_options_from_html(html: str) -> Dict[str, List[Dict[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, List[Dict[str, str]]] = {}
    for si, sel in enumerate(soup.find_all("select")):
        name = sel.get("name") or sel.get("id") or f"select_{si}"
        opts = []
        for opt in sel.find_all("option"):
            opts.append({"value": safe_text(opt.get("value")), "text": safe_text(opt.get_text(" ", strip=True))})
        out[name] = opts
    return out


def capture_rendered_page(page, *, label: str, out_dir: Path, meta: Optional[Dict[str, Any]] = None) -> Path:
    page.wait_for_timeout(800)
    html = page.content()
    body_text = safe_text(page.inner_text("body"))
    rec = {
        "label": label,
        "captured_at": now_stamp(),
        "url": page.url,
        "title": page.title(),
        "meta": meta or {},
        "tables": parse_tables_from_html(html),
        "links": extract_links_from_html(html, page.url),
        "options": extract_options_from_html(html),
        "body_text": body_text,
        "raw_html_file": "",
    }
    raw_dir = out_dir / "html"
    raw_dir.mkdir(parents=True, exist_ok=True)
    html_file = raw_dir / f"{slug(label)}_{file_stamp()}.html"
    html_file.write_text(html, encoding="utf-8")
    rec["raw_html_file"] = str(html_file)

    jsonl_file = out_dir / "raw_pages.jsonl"
    dump_jsonl(jsonl_file, [rec])
    print(f"Saved capture: {jsonl_file}")
    print(f"Saved HTML: {html_file}")
    return jsonl_file


def manual_prompt(kind: str) -> None:
    print("\nIn the browser:")
    if kind == "causelist":
        print("1. Open/choose Cause List if not already there.")
        print("2. Select High Court/Bench if prompted.")
        print("3. Select the cause-list date.")
        print("4. Enter captcha.")
        print("5. Click Go / Submit and wait until Cause List Report is visible.")
    elif kind == "orders":
        print("1. Open Case Orders/Judgement.")
        print("2. Choose Order Date, Court Number/Judge Wise, or Case Number search.")
        print("3. Enter captcha.")
        print("4. Click Go and wait until the result table/order links are visible.")
    else:
        print("1. Navigate/select whatever page you want captured.")
        print("2. Enter captcha if present.")
        print("3. Wait until the required table/PDF links are visible.")
    input("\nThen press Enter here to capture the rendered page... ")


def run_manual_capture(args: argparse.Namespace, kind: str) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.url:
        start_url = args.url
    elif kind == "causelist":
        start_url = EC_URLS[f"{args.side}_causelist"]
    else:
        start_url = EC_URLS[args.side]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless, slow_mo=args.slow_mo)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        for i in range(args.repeat):
            manual_prompt(kind)
            label_parts = [kind, getattr(args, "side", "manual"), args.label or "capture", str(i + 1)]
            capture_rendered_page(
                page,
                label="_".join(label_parts),
                out_dir=out_dir,
                meta={"kind": kind, "side": getattr(args, "side", None), "iteration": i + 1},
            )
            if i + 1 < args.repeat:
                print("\nYou can now change date/search options in the same browser window for the next capture.")
        context.close()
        browser.close()


def get_pdf_links_from_official_page(url: str, contains: List[str]) -> List[Dict[str, str]]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        text = safe_text(a.get_text(" ", strip=True))
        href = urljoin(url, a.get("href"))
        joined = f"{text} {href}".lower()
        if contains and not all(c.lower() in joined for c in contains):
            continue
        # include direct PDFs and likely document routes
        if ".pdf" in href.lower() or "download" in href.lower() or "uploads" in href.lower() or text:
            out.append({"source_page": url, "text": text, "href": href})
    return out


def download_file(url: str, path: Path) -> bool:
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        print(f"Downloaded: {path} ({ctype}, {len(r.content)} bytes)")
        return True
    except Exception as e:
        print(f"Failed download {url}: {e}", file=sys.stderr)
        return False


def run_official_cause_pdfs(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    pdf_dir = out_dir / "official_cause_pdfs"
    records = []
    seen = set()
    for url in (args.url or OFFICIAL_CAUSE_URLS):
        try:
            links = get_pdf_links_from_official_page(url, args.contains or [])
        except Exception as e:
            print(f"Failed page {url}: {e}", file=sys.stderr)
            continue
        for link in links:
            href = link["href"]
            if href in seen:
                continue
            seen.add(href)
            ext = ".pdf" if ".pdf" in href.lower() else Path(urlparse(href).path).suffix or ".bin"
            fname = f"{slug(link['text'] or Path(urlparse(href).path).name)}_{len(records)+1}{ext}"
            local = pdf_dir / fname
            ok = download_file(href, local)
            rec = {**link, "downloaded": ok, "local_file": str(local), "captured_at": now_stamp()}
            records.append(rec)
    dump_jsonl(out_dir / "official_cause_pdf_links.jsonl", records)
    print(f"Saved metadata: {out_dir / 'official_cause_pdf_links.jsonl'}")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Calcutta HC scheduling-input scraper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_manual_common(p):
        p.add_argument("--out-dir", required=True)
        p.add_argument("--side", choices=["original", "appellate"], default="appellate")
        p.add_argument("--url", default=None, help="Override start URL")
        p.add_argument("--label", default="")
        p.add_argument("--repeat", type=int, default=1, help="Number of manual captures in same browser session")
        p.add_argument("--headless", action="store_true")
        p.add_argument("--slow-mo", type=int, default=60)

    p = sub.add_parser("ecourts-causelist", help="Human-captcha capture of eCourts cause-list result pages")
    add_manual_common(p)

    p = sub.add_parser("ecourts-orders", help="Human-captcha capture of eCourts orders/judgement result pages")
    add_manual_common(p)

    p = sub.add_parser("capture-page", help="Generic manual capture of rendered page/tables/links")
    add_manual_common(p)

    p = sub.add_parser("official-cause-pdfs", help="Download visible official cause-list PDFs from Calcutta HC pages")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--url", action="append", default=None, help="Official page URL; can repeat. Defaults to Cause-Lists and Notices/CL")
    p.add_argument("--contains", action="append", default=[], help="Only keep links containing this text; can repeat")
    return ap


def main() -> None:
    args = build_argparser().parse_args()
    if args.cmd == "ecourts-causelist":
        run_manual_capture(args, "causelist")
    elif args.cmd == "ecourts-orders":
        run_manual_capture(args, "orders")
    elif args.cmd == "capture-page":
        run_manual_capture(args, "manual")
    elif args.cmd == "official-cause-pdfs":
        run_official_cause_pdfs(args)
    else:
        raise SystemExit(f"Unknown command {args.cmd}")


if __name__ == "__main__":
    main()
