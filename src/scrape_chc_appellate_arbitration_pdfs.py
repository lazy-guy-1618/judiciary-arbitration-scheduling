#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, json, re, time
from dataclasses import asdict, dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.calcuttahighcourt.gov.in"
START_URL = f"{BASE}/Notices/CL"
DATE_PATTERNS = [
    re.compile(r"(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})[.\-/](?P<y>20\d{2})"),
    re.compile(r"(?P<d>\d{1,2})\s+(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*,?\s+(?P<y>20\d{2})", re.I),
]
MON = {"jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,"may":5,"jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,"september":9,"oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12}

@dataclass
class NoticeLink:
    notice_date: str
    title: str
    url: str
    source_page: str
    list_kind: str
    side: str = "Appellate Side"
    downloaded_path: str = ""
    downloaded_ok: bool = False
    http_status: int = 0
    content_type: str = ""

def parse_date_from_text(text: str) -> Optional[date]:
    text = re.sub(r"\s+", " ", text or "").strip()
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if not m: continue
        gd = m.groupdict()
        try:
            d, y = int(gd["d"]), int(gd["y"])
            mo = MON[gd["mon"].lower()] if gd.get("mon") else int(gd["m"])
            return date(y, mo, d)
        except Exception:
            pass
    return None

def classify_list_kind(title: str) -> str:
    low = title.lower()
    if "supplementary" in low:
        for n in [5,4,3,2]:
            if f"supplementary list {n}" in low or f"supplementary cause list {n}" in low or f"supplementary cause list ({n})" in low:
                return f"supplementary_{n}"
        return "supplementary_1"
    if "monthly" in low: return "monthly"
    if "daily" in low: return "daily"
    return "other_cause_list"

def is_relevant_appellate_cause_notice(title: str) -> bool:
    low = title.lower()
    return ("appellate side" in low and ("cause list" in low or "causelist" in low)
            and "original side" not in low and "circuit bench" not in low
            and "jalpaiguri" not in low and "port blair" not in low)

def safe_filename(title: str, url: str, suffix: str = ".pdf") -> str:
    d = parse_date_from_text(title)
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return f"{d.isoformat() if d else 'unknown_date'}_{classify_list_kind(title)}_{digest}{suffix}"

def request_html(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def iter_notice_pages(session: requests.Session, max_pages: int, sleep: float) -> Iterable[str]:
    seen, queue, numeric = set(), [START_URL], 1
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen: continue
        seen.add(url)
        yield url
        try:
            soup = BeautifulSoup(request_html(session, url), "html.parser")
        except Exception:
            continue
        for a in soup.find_all("a"):
            text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip().lower()
            href = a.get("href")
            if href and (text in {"next", "next ›", "›", ">"} or "page=" in href.lower()):
                nxt = urljoin(BASE, href)
                if nxt not in seen and nxt not in queue:
                    queue.append(nxt)
        numeric += 1
        for c in [f"{START_URL}?page={numeric}", f"{START_URL}/{numeric}", f"{START_URL}?page_no={numeric}"]:
            if c not in seen and c not in queue:
                queue.append(c)
        time.sleep(sleep)

def extract_links_from_page(session: requests.Session, page_url: str) -> list[NoticeLink]:
    soup = BeautifulSoup(request_html(session, page_url), "html.parser")
    out = []
    for a in soup.find_all("a"):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        href = a.get("href")
        if not title or not href or not is_relevant_appellate_cause_notice(title):
            continue
        dt = parse_date_from_text(title)
        out.append(NoticeLink(dt.isoformat() if dt else "", title, urljoin(BASE, href), page_url, classify_list_kind(title)))
    return out

def download_one(session: requests.Session, item: NoticeLink, pdf_dir: Path, sleep: float) -> NoticeLink:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(item.url, timeout=60, allow_redirects=True)
        item.http_status = r.status_code
        item.content_type = r.headers.get("content-type", "")
        suffix = ".pdf" if (r.status_code == 200 and (b"%PDF" in r.content[:1024] or "pdf" in item.content_type.lower())) else ".bin"
        path = pdf_dir / safe_filename(item.title, item.url, suffix)
        path.write_bytes(r.content)
        item.downloaded_path = str(path)
        item.downloaded_ok = suffix == ".pdf"
    except Exception as e:
        item.http_status = -1
        item.content_type = f"ERROR: {e}"
    time.sleep(sleep)
    return item

def main() -> None:
    ap = argparse.ArgumentParser(description="Download CHC Appellate Side cause-list PDFs from official notice archive; no captcha/date entry needed.")
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--include-monthly", action="store_true")
    args = ap.parse_args()
    start, end = datetime.strptime(args.start_date, "%Y-%m-%d").date(), datetime.strptime(args.end_date, "%Y-%m-%d").date()
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 academic-research"})
    items = {}
    for page_url in iter_notice_pages(s, args.max_pages, args.sleep):
        try: links = extract_links_from_page(s, page_url)
        except Exception as e:
            print(f"[WARN] {page_url}: {e}"); continue
        for item in links:
            if not args.include_monthly and item.list_kind == "monthly": continue
            if item.notice_date:
                d = datetime.strptime(item.notice_date, "%Y-%m-%d").date()
                if not (start <= d <= end): continue
            items[item.url] = item
        print(f"[PAGE] {page_url} -> collected={len(items)}")
    rows = sorted(items.values(), key=lambda x: (x.notice_date or "9999", x.list_kind, x.title))
    if args.download:
        for i, item in enumerate(rows, 1):
            download_one(s, item, out_dir / "pdfs", args.sleep)
            print(f"[DL {i}/{len(rows)}] {item.notice_date} {item.list_kind} ok={item.downloaded_ok} {item.title[:80]}")
    fields = list(asdict(NoticeLink("","","","","")).keys())
    with (out_dir / "notice_links.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); [w.writerow(asdict(r)) for r in rows]
    with (out_dir / "notice_links.jsonl").open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} notice links to {out_dir/'notice_links.csv'}")

if __name__ == "__main__": main()
