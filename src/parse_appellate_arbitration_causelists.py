#!/usr/bin/env python3
from __future__ import annotations

import argparse, re
from dataclasses import dataclass, asdict
from pathlib import Path
import pandas as pd

COURT_RE = re.compile(r"\bCOURT\s+NO\.?\s*(?P<court_no>[A-Z0-9\-/]+)", re.I)
BENCH_ID_RE = re.compile(r"\bBench\s*ID\s*[-:]?\s*(?P<bench_id>\d+)", re.I)
HONBLE_RE = re.compile(r"HON'?BLE\s+(?:THE\s+)?(?:CHIEF\s+JUSTICE|JUSTICE)\s+[^\n]+", re.I)
DATE_RE = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")

@dataclass
class CauseRow:
    source_pdf: str; source_date: str; list_kind: str; page_no: int
    court_no: str; bench_id: str; coram: str; bench_type: str
    serial_no: str; case_type: str; case_no: str; case_year: str; case_key: str
    line_text: str; context_text: str; inferred_purpose: str

@dataclass
class BenchRow:
    source_pdf: str; source_date: str; list_kind: str; page_no: int
    court_no: str; bench_id: str; coram: str; bench_type: str

def extract_text_pages(pdf_path: Path) -> list[str]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        return [page.get_text("text") or "" for page in doc]
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:
        raise RuntimeError(f"Install pymupdf or pypdf to parse PDFs. Failed on {pdf_path}: {e}")

def normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def infer_date(path: Path) -> str:
    m = DATE_RE.search(path.name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

def infer_kind(path: Path) -> str:
    low = path.name.lower()
    if "supplementary_5" in low: return "supplementary_5"
    if "supplementary_4" in low: return "supplementary_4"
    if "supplementary_3" in low: return "supplementary_3"
    if "supplementary_2" in low: return "supplementary_2"
    if "supplementary" in low: return "supplementary_1"
    if "monthly" in low: return "monthly"
    if "daily" in low: return "daily"
    return "unknown"

def serial_before(text: str, idx: int) -> str:
    nums = re.findall(r"(?:^|\s)(\d{1,4})(?:\s|$)", text[:idx])
    return nums[-1] if nums else ""

def infer_purpose(context: str) -> str:
    ctx = context.lower()
    keys = ["for orders", "for judgement", "for judgment", "for hearing", "for admission", "motion", "to be mentioned", "part heard", "specially fixed", "for disposal", "application"]
    return "; ".join([k for k in keys if k in ctx][:3])

def page_context(text: str) -> tuple[str, str, str, str]:
    court_no = bench_id = bench_type = ""; coram_parts = []
    for line in text.splitlines()[:100]:
        clean = normalise(line)
        if not clean: continue
        m = COURT_RE.search(clean)
        if m and not court_no: court_no = m.group("court_no")
        b = BENCH_ID_RE.search(clean)
        if b and not bench_id: bench_id = b.group("bench_id")
        up = clean.upper()
        if "DIVISION BENCH" in up: bench_type = "DIVISION BENCH"
        elif "SINGLE BENCH" in up and not bench_type: bench_type = "SINGLE BENCH"
        if HONBLE_RE.search(clean): coram_parts.append(clean)
    return court_no, bench_id, " | ".join(coram_parts[:3]), bench_type

def parse_pdf(pdf: Path, case_types: list[str]):
    case_re = re.compile(r"\b(?P<case_type>" + "|".join(map(re.escape, case_types)) + r")\s*/\s*(?P<case_no>\d+[A-Z]?)\s*/\s*(?P<case_year>20\d{2})\b", re.I)
    source_date, list_kind = infer_date(pdf), infer_kind(pdf)
    cause_rows, bench_rows = [], []
    pages = extract_text_pages(pdf)
    hits = 0
    for pno, text in enumerate(pages, 1):
        court_no, bench_id, coram, bench_type = page_context(text)
        if court_no or bench_id or coram:
            bench_rows.append(BenchRow(str(pdf), source_date, list_kind, pno, court_no, bench_id, coram, bench_type))
        lines = [normalise(x) for x in text.splitlines()]
        for i, line in enumerate(lines):
            context = normalise(" | ".join(lines[max(0, i-2): min(len(lines), i+6)]))
            for m in case_re.finditer(context):
                ct, no, yr = m.group("case_type").upper(), m.group("case_no"), m.group("case_year")
                key = f"{ct}/{no}/{yr}"
                hits += 1
                cause_rows.append(CauseRow(str(pdf), source_date, list_kind, pno, court_no, bench_id, coram, bench_type, serial_before(context, m.start()), ct, no, yr, key, line, context, infer_purpose(context)))
    return cause_rows, bench_rows, {"source_pdf": str(pdf), "source_date": source_date, "list_kind": list_kind, "pages": len(pages), "arbitration_hits": hits}

def main():
    ap = argparse.ArgumentParser(description="Parse CHC Appellate Side cause-list PDFs and keep FMAT/AOCOM/ADCOM rows.")
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--case-types", nargs="+", default=["FMAT", "AOCOM", "ADCOM"])
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    cause, bench, meta = [], [], []
    pdfs = sorted(Path(args.pdf_dir).rglob("*.pdf"))
    for i, pdf in enumerate(pdfs, 1):
        try:
            cr, br, mr = parse_pdf(pdf, [x.upper() for x in args.case_types])
            cause.extend(cr); bench.extend(br); meta.append(mr)
            print(f"[{i}/{len(pdfs)}] {pdf.name}: hits={mr['arbitration_hits']} pages={mr['pages']}")
        except Exception as e:
            meta.append({"source_pdf": str(pdf), "error": str(e), "arbitration_hits": 0})
            print(f"[WARN] {pdf}: {e}")
    cdf = pd.DataFrame([asdict(x) for x in cause])
    if not cdf.empty: cdf = cdf.drop_duplicates(subset=["source_pdf", "page_no", "case_key", "context_text"])
    bdf = pd.DataFrame([asdict(x) for x in bench]).drop_duplicates() if bench else pd.DataFrame()
    mdf = pd.DataFrame(meta)
    cdf.to_csv(out / "appellate_arbitration_cause_list.csv", index=False)
    bdf.to_csv(out / "bench_roster_from_pdfs.csv", index=False)
    mdf.to_csv(out / "pdf_text_index.csv", index=False)
    print(f"Wrote {len(cdf)} cause rows, {len(bdf)} bench rows, {len(mdf)} pdf-index rows to {out}")

if __name__ == "__main__": main()
