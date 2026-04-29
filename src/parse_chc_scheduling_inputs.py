#!/usr/bin/env python3
"""
parse_chc_scheduling_inputs.py

Normalizes raw scheduling inputs captured by scrape_chc_scheduling_inputs.py.

Outputs:
  daily_cause_list.csv     - one row per listed case/item if detectable
  bench_roster.csv         - bench/coram/court blocks inferred from cause-list text
  raw_cause_tables.csv     - table rows preserved for audit/debug
  order_links.csv          - order/judgement/PDF links found in captured pages
  official_pdf_links.csv   - metadata from downloaded official PDFs, if present

It supports:
  - raw_pages.jsonl captures from rendered eCourts/official pages
  - downloaded cause-list PDFs in official_cause_pdfs/ using PyMuPDF or pypdf if installed

This parser is deliberately heuristic because Calcutta HC/eCourts layouts vary by
side and date. It preserves raw fields so you can improve rules without rescraping.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

CASE_TYPES_DEFAULT = ["FMAT", "AOCOM", "ADCOM"]
CASE_RE = re.compile(r"\b(?P<case_type>FMAT|AOCOM|ADCOM)\s*[/\- ]\s*(?P<case_no>\d{1,7})\s*[/\- ]\s*(?P<case_year>20\d{2})\b", re.I)
DATE_RE = re.compile(r"\b(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>20\d{2})\b")
COURT_RE = re.compile(r"\bCOURT\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*(?P<court_no>[A-Z0-9]+)\b", re.I)
ITEM_RE = re.compile(r"^\s*(?P<serial>\d{1,4})[).\-\s]+(?P<rest>.*)$")
CORAM_HINT_RE = re.compile(r"\b(?:HON'?BLE|JUSTICE|THE HONOURABLE|BEFORE)\b", re.I)


def safe_text(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def normalize_date(text: str) -> str:
    m = DATE_RE.search(text or "")
    if not m:
        return ""
    d, mo, y = int(m.group("d")), int(m.group("m")), int(m.group("y"))
    try:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception:
        return ""


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def extract_case_from_text(text: str, case_types: List[str]) -> Optional[Dict[str, str]]:
    pattern = re.compile(r"\b(?P<case_type>" + "|".join(map(re.escape, case_types)) + r")\s*[/\- ]\s*(?P<case_no>\d{1,7})\s*[/\- ]\s*(?P<case_year>20\d{2})\b", re.I)
    m = pattern.search(text or "")
    if not m:
        return None
    ct = m.group("case_type").upper()
    no = m.group("case_no")
    yr = m.group("case_year")
    return {"case_type": ct, "case_number": no, "case_year": yr, "case_key": f"{ct}/{no}/{yr}"}


def split_parties(text: str) -> Tuple[str, str]:
    parts = re.split(r"\b(?:versus|vs\.?|v\.)\b", text or "", maxsplit=1, flags=re.I)
    if len(parts) == 2:
        return safe_text(parts[0]), safe_text(parts[1])
    return "", ""


def parse_table_rows_from_capture(rec: Dict[str, Any], case_types: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    cause_rows: List[Dict[str, Any]] = []
    raw_rows: List[Dict[str, Any]] = []
    roster_rows: List[Dict[str, Any]] = []
    date = normalize_date(" ".join([safe_text(rec.get("label")), safe_text(rec.get("body_text"))]))
    label = safe_text(rec.get("label"))
    source_url = safe_text(rec.get("url"))

    for table in rec.get("tables", []) or []:
        headers = [safe_text(h) for h in table.get("headers", [])]
        rows = table.get("rows", []) or []
        for ridx, vals in enumerate(rows):
            row_text = safe_text(" | ".join(map(str, vals)))
            raw = {
                "source": "html_table",
                "label": label,
                "url": source_url,
                "date": date,
                "table_index": table.get("table_index"),
                "row_index": ridx,
                "headers": json.dumps(headers, ensure_ascii=False),
                "values": json.dumps(vals, ensure_ascii=False),
                "row_text": row_text,
            }
            raw_rows.append(raw)
            case = extract_case_from_text(row_text, case_types)
            if case:
                petitioner, respondent = split_parties(row_text)
                serial = ""
                if vals:
                    m_item = ITEM_RE.match(safe_text(vals[0]))
                    serial = m_item.group("serial") if m_item else (safe_text(vals[0]) if safe_text(vals[0]).isdigit() else "")
                cause_rows.append({
                    "date": date,
                    "side_or_label": label,
                    "bench_id": "",
                    "court_number": "",
                    "coram": "",
                    "serial_no": serial,
                    **case,
                    "petitioner_text": petitioner,
                    "respondent_text": respondent,
                    "purpose": infer_purpose(row_text),
                    "advocates": infer_advocates(row_text),
                    "raw_text": row_text,
                    "source_url": source_url,
                    "source_kind": "html_table",
                })

    # weak roster extraction from body lines
    roster_rows.extend(extract_roster_blocks(safe_text(rec.get("body_text")), date, label, source_url))
    return cause_rows, roster_rows, raw_rows


def infer_purpose(text: str) -> str:
    candidates = [
        "FOR ADMISSION", "ADMISSION", "HEARING", "FINAL HEARING", "MOTION", "ORDERS",
        "FOR ORDERS", "JUDGMENT", "ARGUMENT", "APPLICATION", "EXTENSION", "INTERIM",
    ]
    up = (text or "").upper()
    hits = [c for c in candidates if c in up]
    return hits[0].title() if hits else ""


def infer_advocates(text: str) -> str:
    # Keep conservative: cause-list formats vary. Capture phrases after common advocate markers.
    m = re.search(r"(?:ADVOCATE[S]?|FOR PETITIONER|FOR RESPONDENT)\s*[:\-]?\s*(.{0,160})", text or "", re.I)
    return safe_text(m.group(1)) if m else ""


def extract_roster_blocks(text: str, date: str, label: str, source_url: str) -> List[Dict[str, Any]]:
    lines = [safe_text(x) for x in re.split(r"[\n|]", text or "") if safe_text(x)]
    out = []
    current_court = ""
    current_coram = ""
    for line in lines:
        cm = COURT_RE.search(line)
        if cm:
            current_court = cm.group("court_no")
        if CORAM_HINT_RE.search(line) and len(line) < 250:
            current_coram = line
            out.append({
                "date": date,
                "side_or_label": label,
                "bench_id": f"{date}_{current_court}_{len(out)+1}",
                "court_number": current_court,
                "coram": current_coram,
                "judge_1": extract_first_judge(current_coram),
                "judge_2": extract_second_judge(current_coram),
                "bench_type": "division" if re.search(r"\bAND\b|&", current_coram, re.I) else "single",
                "roster_subject": "",
                "is_available": 1,
                "raw_text": line,
                "source_url": source_url,
            })
    return out


def extract_first_judge(coram: str) -> str:
    names = re.split(r"\bAND\b|&", coram, flags=re.I)
    return clean_judge_name(names[0]) if names else ""


def extract_second_judge(coram: str) -> str:
    names = re.split(r"\bAND\b|&", coram, flags=re.I)
    return clean_judge_name(names[1]) if len(names) > 1 else ""


def clean_judge_name(x: str) -> str:
    x = re.sub(r"\b(?:HON'?BLE|THE|JUSTICE|MR\.?|MRS\.?|MS\.?|CHIEF|JUDGE|BEFORE)\b", " ", x or "", flags=re.I)
    return safe_text(x)


def extract_order_links_from_capture(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for link in rec.get("links", []) or []:
        text = safe_text(link.get("text"))
        href = safe_text(link.get("href"))
        low = f"{text} {href}".lower()
        if any(k in low for k in ["order", "judgement", "judgment", ".pdf", "download"]):
            out.append({
                "captured_at": rec.get("captured_at"),
                "label": rec.get("label"),
                "page_url": rec.get("url"),
                "link_text": text,
                "href": href,
            })
    return out


def extract_pdf_text(path: Path) -> str:
    # Try PyMuPDF first, then pypdf. Keep dependency optional.
    try:
        import fitz  # type: ignore
        doc = fitz.open(str(path))
        return "\n".join(page.get_text("text") for page in doc)
    except Exception:
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        raise RuntimeError(f"Could not extract PDF text from {path}. Install pymupdf or pypdf. Error: {e}")


def parse_pdf_cause_list(path: Path, case_types: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    text = extract_pdf_text(path)
    date = normalize_date(text) or normalize_date(path.name)
    lines = [safe_text(x) for x in text.splitlines() if safe_text(x)]
    cause_rows = []
    roster_rows = []
    current_court = ""
    current_coram = ""
    current_bench_id = ""
    serial_hint = ""
    for i, line in enumerate(lines):
        cm = COURT_RE.search(line)
        if cm:
            current_court = cm.group("court_no")
            current_bench_id = f"{date}_{current_court}"
        if CORAM_HINT_RE.search(line) and len(line) < 220:
            current_coram = line
            roster_rows.append({
                "date": date,
                "side_or_label": path.name,
                "bench_id": current_bench_id or f"{date}_bench_{len(roster_rows)+1}",
                "court_number": current_court,
                "coram": current_coram,
                "judge_1": extract_first_judge(current_coram),
                "judge_2": extract_second_judge(current_coram),
                "bench_type": "division" if re.search(r"\bAND\b|&", current_coram, re.I) else "single",
                "roster_subject": "",
                "is_available": 1,
                "raw_text": line,
                "source_url": str(path),
            })
        im = ITEM_RE.match(line)
        if im:
            serial_hint = im.group("serial")
        case = extract_case_from_text(line, case_types)
        if case:
            # Join neighboring lines because PDF extraction often splits parties/purpose.
            window = " ".join(lines[max(0, i-2): min(len(lines), i+4)])
            petitioner, respondent = split_parties(window)
            cause_rows.append({
                "date": date,
                "side_or_label": path.name,
                "bench_id": current_bench_id,
                "court_number": current_court,
                "coram": current_coram,
                "serial_no": serial_hint,
                **case,
                "petitioner_text": petitioner,
                "respondent_text": respondent,
                "purpose": infer_purpose(window),
                "advocates": infer_advocates(window),
                "raw_text": window,
                "source_url": str(path),
                "source_kind": "pdf_text",
            })
    return cause_rows, roster_rows


def dedupe_rows(rows: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in rows:
        k = tuple(safe_text(r.get(x)) for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, help="Directory produced by scraper")
    ap.add_argument("--out-dir", required=True, help="Directory for normalized CSVs")
    ap.add_argument("--case-types", nargs="+", default=CASE_TYPES_DEFAULT)
    ap.add_argument("--parse-pdfs", action="store_true", help="Also parse PDFs in official_cause_pdfs/")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_types = [x.upper() for x in args.case_types]

    cause_rows: List[Dict[str, Any]] = []
    roster_rows: List[Dict[str, Any]] = []
    raw_table_rows: List[Dict[str, Any]] = []
    order_links: List[Dict[str, Any]] = []

    raw_pages = raw_dir / "raw_pages.jsonl"
    if raw_pages.exists():
        for rec in read_jsonl(raw_pages):
            c, r, raw = parse_table_rows_from_capture(rec, case_types)
            cause_rows.extend(c)
            roster_rows.extend(r)
            raw_table_rows.extend(raw)
            order_links.extend(extract_order_links_from_capture(rec))

    pdf_meta = raw_dir / "official_cause_pdf_links.jsonl"
    if pdf_meta.exists():
        pd.DataFrame(list(read_jsonl(pdf_meta))).to_csv(out_dir / "official_pdf_links.csv", index=False)

    if args.parse_pdfs:
        pdf_dir = raw_dir / "official_cause_pdfs"
        for pdf in sorted(pdf_dir.glob("*.pdf")):
            try:
                c, r = parse_pdf_cause_list(pdf, case_types)
                cause_rows.extend(c)
                roster_rows.extend(r)
            except Exception as e:
                print(f"PDF parse failed for {pdf}: {e}")

    cause_rows = dedupe_rows(cause_rows, ["date", "case_key", "bench_id", "serial_no", "source_kind"])
    roster_rows = dedupe_rows(roster_rows, ["date", "court_number", "coram", "source_url"])

    pd.DataFrame(cause_rows).to_csv(out_dir / "daily_cause_list.csv", index=False)
    pd.DataFrame(roster_rows).to_csv(out_dir / "bench_roster.csv", index=False)
    pd.DataFrame(raw_table_rows).to_csv(out_dir / "raw_cause_tables.csv", index=False)
    pd.DataFrame(order_links).to_csv(out_dir / "order_links.csv", index=False)

    print(f"Wrote: {out_dir / 'daily_cause_list.csv'} rows={len(cause_rows)}")
    print(f"Wrote: {out_dir / 'bench_roster.csv'} rows={len(roster_rows)}")
    print(f"Wrote: {out_dir / 'raw_cause_tables.csv'} rows={len(raw_table_rows)}")
    print(f"Wrote: {out_dir / 'order_links.csv'} rows={len(order_links)}")


if __name__ == "__main__":
    main()
