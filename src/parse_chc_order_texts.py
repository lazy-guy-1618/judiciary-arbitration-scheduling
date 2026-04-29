#!/usr/bin/env python3
"""
Parse downloaded Calcutta High Court order PDFs/HTML into text and simple outcome labels.

Input:
  order_raw/order_manifest.jsonl produced by scrape_chc_order_texts.py

Outputs:
  order_texts.csv/jsonl       one row per downloaded/parsed order
  case_order_features.csv     aggregated features per case
  unparsed_orders.csv         files that could not be parsed
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from bs4 import BeautifulSoup


def safe_text(x: Any) -> str:
    if x is None:
        return ""
    x = html.unescape(str(x)).replace("\u00a0", " ").replace("\ufffe", "")
    return re.sub(r"\s+", " ", x).strip()


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def parse_pdf_text(path: Path) -> str:
    # Prefer PyMuPDF; fallback to pypdf.
    try:
        import fitz  # type: ignore
        parts = []
        with fitz.open(path) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return safe_text("\n".join(parts))
    except Exception:
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return safe_text("\n".join(page.extract_text() or "" for page in reader.pages))
    except Exception as e:
        raise RuntimeError(f"PDF parse failed: {e}")


def parse_html_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return safe_text(soup.get_text("\n", strip=True))


def parse_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf_text(path)
    if suffix in {".html", ".htm", ".txt", ".bin"}:
        # Some sites return HTML with .bin extension if content-type was absent.
        data = path.read_bytes()[:8]
        if data.startswith(b"%PDF"):
            return parse_pdf_text(path)
        return parse_html_text(path)
    return safe_text(path.read_text(encoding="utf-8", errors="replace"))


OUTCOME_PATTERNS = {
    "disposed": [
        r"\bdisposed\s+of\b", r"\bdisposed\b", r"\bcase\s+is\s+disposed\b",
        r"\bapplication\s+is\s+disposed\b",
    ],
    "dismissed": [r"\bdismissed\b", r"\bstands\s+dismissed\b"],
    "withdrawn": [r"\bwithdrawn\b", r"\bleave\s+to\s+withdraw\b"],
    "allowed": [r"\ballowed\b", r"\bapplication\s+is\s+allowed\b", r"\bappeal\s+is\s+allowed\b"],
    "rejected": [r"\brejected\b", r"\brefused\b"],
    "adjourned": [r"\badjourn(?:ed|ment)\b", r"\blet\s+the\s+matter\s+appear\b"],
    "not_taken_up": [r"\bnot\s+taken\s+up\b", r"\bcould\s+not\s+be\s+taken\s+up\b", r"\bnot\s+reached\b"],
    "heard_in_part": [r"\bheard\s+in\s+part\b", r"\bpart[-\s]?heard\b"],
    "reserved": [r"\bjudg(?:e)?ment\s+reserved\b", r"\border\s+reserved\b", r"\breserved\s+for\s+judg"],
    "next_date_given": [r"\blist(?:ed)?\s+(?:the\s+matter\s+)?on\b", r"\bappear\s+on\b", r"\breturnable\s+on\b"],
    "service_issue": [r"\bservice\b", r"\bnotice\b", r"\baffidavit\s+of\s+service\b"],
    "defect_objection": [r"\bdefect\b", r"\bobjection\b", r"\bdepartment\b"],
    "arbitrator": [r"\barbitrator\b", r"\barbitral\b", r"\barbitration\b"],
}


def classify_outcomes(text: str) -> Dict[str, int]:
    low = text.lower()
    flags: Dict[str, int] = {}
    for label, pats in OUTCOME_PATTERNS.items():
        flags[label] = int(any(re.search(p, low, flags=re.I) for p in pats))
    # A crude progress flag: any meaningful terminal/procedural movement.
    flags["progress_signal"] = int(any(flags[k] for k in [
        "disposed", "dismissed", "withdrawn", "allowed", "rejected", "heard_in_part", "reserved", "next_date_given"
    ]))
    flags["terminal_signal"] = int(any(flags[k] for k in ["disposed", "dismissed", "withdrawn", "allowed", "rejected"]))
    flags["ineffective_signal"] = int(any(flags[k] for k in ["adjourned", "not_taken_up", "service_issue", "defect_objection"]))
    return flags


def extract_next_dates(text: str) -> str:
    # Keep conservative DD.MM.YYYY/DD-MM-YYYY/DD/MM/YYYY dates around list/appear/returnable.
    dates = []
    date_pat = r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b"
    for m in re.finditer(date_pat, text):
        window = text[max(0, m.start()-80): m.end()+80].lower()
        if any(k in window for k in ["list", "appear", "returnable", "fixed", "next"]):
            dates.append(m.group(0))
    seen = []
    for d in dates:
        if d not in seen:
            seen.append(d)
    return ";".join(seen[:5])


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
    ap.add_argument("--manifest", required=True, help="order_manifest.jsonl from scrape_chc_order_texts.py")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--min-text-chars", type=int, default=30)
    args = ap.parse_args()

    manifest = Path(args.manifest)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    order_rows: List[Dict[str, Any]] = []
    bad_rows: List[Dict[str, Any]] = []

    for row in read_jsonl(manifest):
        path_s = safe_text(row.get("download_path"))
        if not path_s:
            continue
        path = Path(path_s)
        if not path.exists():
            bad_rows.append({**row, "parse_error": "download_path_missing"})
            continue
        try:
            text = parse_file_text(path)
            if len(text) < args.min_text_chars:
                raise RuntimeError(f"too_little_text chars={len(text)}")
            flags = classify_outcomes(text)
            out = dict(row)
            out.update(flags)
            out["parsed_text"] = text
            out["text_chars"] = len(text)
            out["next_dates_in_order"] = extract_next_dates(text)
            order_rows.append(out)
        except Exception as e:
            bad_rows.append({**row, "parse_error": str(e)})

    # JSONL with full text
    with (out_dir / "order_texts.jsonl").open("w", encoding="utf-8") as f:
        for r in order_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # CSV with text too. If it becomes large, use JSONL for modelling.
    write_csv(out_dir / "order_texts.csv", order_rows)
    write_csv(out_dir / "unparsed_orders.csv", bad_rows)

    # Aggregate per case.
    agg = defaultdict(lambda: defaultdict(int))
    meta = {}
    for r in order_rows:
        key = r.get("case_key") or r.get("case_id")
        meta[key] = {
            "case_key": r.get("case_key", ""),
            "case_id": r.get("case_id", ""),
            "case_type": r.get("case_type", ""),
            "case_no": r.get("case_no", ""),
            "case_year": r.get("case_year", ""),
            "status_filter": r.get("status_filter", ""),
        }
        agg[key]["orders_parsed"] += 1
        for label in list(OUTCOME_PATTERNS.keys()) + ["progress_signal", "terminal_signal", "ineffective_signal"]:
            agg[key][f"{label}_count"] += int(r.get(label, 0) or 0)
        try:
            agg[key]["text_chars_total"] += int(r.get("text_chars", 0) or 0)
        except Exception:
            pass

    case_rows = []
    for key, counts in agg.items():
        out = dict(meta.get(key, {}))
        out.update(counts)
        case_rows.append(out)
    write_csv(out_dir / "case_order_features.csv", case_rows)

    print(f"Parsed orders: {len(order_rows)}")
    print(f"Unparsed orders: {len(bad_rows)}")
    print(f"Case feature rows: {len(case_rows)}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
