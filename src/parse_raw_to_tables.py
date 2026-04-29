#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd


def safe_text(x: Any) -> str:
    if x is None:
        return ""
    x = html.unescape(str(x))
    x = x.replace("\u00a0", " ")
    x = x.replace("\ufffe", "")
    return re.sub(r"\s+", " ", x).strip()


def slugify_col(x: str) -> str:
    x = safe_text(x).lower()
    x = x.replace("::", "__")
    x = re.sub(r"[^a-z0-9]+", "_", x)
    return x.strip("_")


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def infer_case_id(rec: Dict[str, Any]) -> str:
    parsed = rec.get("parsed", {}) or {}
    case_details = parsed.get("case_details", {}) or {}
    kv = parsed.get("kv", {}) or {}

    for key in [
        case_details.get("CNR Number"),
        case_details.get("Registration Number"),
        case_details.get("Filing Number"),
        kv.get("CNR Number"),
        kv.get("Registration Number"),
        kv.get("Filing Number"),
    ]:
        key = safe_text(key)
        if key:
            return key

    fallback = safe_text(rec.get("row_preview")) or "unknown_case"
    return fallback[:200]


def split_parties_from_row_preview(row_preview: str) -> Tuple[str, str]:
    row_preview = safe_text(row_preview)
    if not row_preview:
        return "", ""

    text = row_preview.replace(" Versus ", " versus ").replace(" VS ", " versus ")
    if " versus " in text.lower():
        parts = re.split(r"\bversus\b", text, flags=re.IGNORECASE, maxsplit=1)
        if len(parts) == 2:
            left = safe_text(parts[0])
            right = safe_text(parts[1])
            left = re.sub(r"^[A-Z0-9\-/() ]{3,}\s+", "", left).strip()
            return left, right
    return "", ""


def headers_of(table_obj: Dict[str, Any]) -> List[str]:
    return [safe_text(h).lower() for h in (table_obj.get("headers") or []) if safe_text(h)]


def table_text_of(table_obj: Dict[str, Any]) -> str:
    return safe_text(table_obj.get("table_text") or "").lower()


def inline_title_of(table_obj: Dict[str, Any]) -> str:
    return safe_text(table_obj.get("inline_title") or table_obj.get("context_title") or "").lower()


def rows_of(table_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    return table_obj.get("rows") or []


def kv_of(table_obj: Dict[str, Any]) -> Dict[str, Any]:
    return table_obj.get("kv_rows") or {}


def first_nonempty(*vals: Any) -> str:
    for v in vals:
        s = safe_text(v)
        if s:
            return s
    return ""


def normalize_date_like(x: Any) -> str:
    s = safe_text(x)
    return s


def looks_like_orders_table(table_obj: Dict[str, Any]) -> bool:
    hs = set(headers_of(table_obj))
    txt = table_text_of(table_obj)
    title = inline_title_of(table_obj)
    markers = {"order number", "order on", "judge", "order date", "order details"}
    return (
        title == "orders"
        or "orders" in txt
        or len(hs.intersection(markers)) >= 3
    )


def looks_like_objection_table(table_obj: Dict[str, Any]) -> bool:
    hs = set(headers_of(table_obj))
    txt = table_text_of(table_obj)
    title = inline_title_of(table_obj)
    markers = {"sr.no.", "sr no", "scrutiny date", "objection", "objection compliance date", "receipt date"}
    return (
        title == "objection"
        or "objection" in txt
        or len(hs.intersection(markers)) >= 2
    )


def looks_like_subordinate_table(table_obj: Dict[str, Any]) -> bool:
    txt = table_text_of(table_obj)
    title = inline_title_of(table_obj)
    kv = {safe_text(k).lower(): safe_text(v) for k, v in kv_of(table_obj).items()}
    markers = {"court number and name", "case number and year", "case decision date", "state", "district"}
    return (
        title == "subordinate court information"
        or "subordinate court information" in txt
        or len(set(kv.keys()).intersection(markers)) >= 2
    )


def promote_missing_sections(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Promote structured sections from other_tables when scraper-side parser
    left them there.
    """
    other_tables = parsed.get("other_tables", []) or []

    if not parsed.get("orders"):
        promoted_orders: List[Dict[str, Any]] = []
        for t in other_tables:
            if not looks_like_orders_table(t):
                continue
            for row in rows_of(t):
                promoted_orders.append(
                    {
                        "Order Number": first_nonempty(row.get("Order Number"), row.get("Order Number ")),
                        "Order on": first_nonempty(row.get("Order on"), row.get("Order On")),
                        "Judge": safe_text(row.get("Judge")),
                        "Order Date": first_nonempty(row.get("Order Date"), row.get("Date")),
                        "Order Details": first_nonempty(row.get("Order Details"), row.get("View"), row.get("Details")),
                    }
                )
        if promoted_orders:
            parsed["orders"] = promoted_orders

    if not parsed.get("objection"):
        promoted_objection: List[Dict[str, Any]] = []
        for t in other_tables:
            if not looks_like_objection_table(t):
                continue
            for row in rows_of(t):
                promoted_objection.append(
                    {
                        "Sr.No.": first_nonempty(row.get("Sr.No."), row.get("Sr. No."), row.get("Sr No")),
                        "Scrutiny Date": safe_text(row.get("Scrutiny Date")),
                        "OBJECTION": first_nonempty(row.get("OBJECTION"), row.get("Objection")),
                        "OBJECTION Compliance Date": first_nonempty(
                            row.get("OBJECTION Compliance Date"),
                            row.get("Objection Compliance Date"),
                        ),
                        "Receipt Date": safe_text(row.get("Receipt Date")),
                    }
                )
        if promoted_objection:
            parsed["objection"] = promoted_objection

    if not parsed.get("subordinate_court_information"):
        promoted_subordinate: Dict[str, Any] = {}
        for t in other_tables:
            if not looks_like_subordinate_table(t):
                continue
            for k, v in kv_of(t).items():
                promoted_subordinate[safe_text(k)] = safe_text(v)
        if promoted_subordinate:
            parsed["subordinate_court_information"] = promoted_subordinate

    return parsed


def normalize_history_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    cause_list_type = safe_text(row.get("Cause List Type"))
    judge = safe_text(row.get("Judge"))
    business_on_date = safe_text(row.get("Business On Date"))
    hearing_date = safe_text(row.get("Hearing Date"))
    purpose = safe_text(row.get("Purpose of hearing"))

    # repair common shifts
    if hearing_date and not re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", hearing_date):
        if not purpose:
            purpose = hearing_date
            hearing_date = ""

    if business_on_date and not re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", business_on_date):
        if not purpose and not hearing_date:
            purpose = business_on_date
            business_on_date = ""

    return {
        "case_id": case_id,
        "history_index": idx,
        "cause_list_type": cause_list_type,
        "judge": judge,
        "business_on_date": normalize_date_like(business_on_date),
        "hearing_date": normalize_date_like(hearing_date),
        "purpose_of_hearing": purpose,
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_acts_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "act_index": idx,
        "under_acts": first_nonempty(
            row.get("Under Act(s)"),
            row.get("under act(s)"),
            row.get("Act"),
            row.get("act"),
        ),
        "under_sections": first_nonempty(
            row.get("Under Section(s)"),
            row.get("under section(s)"),
            row.get("Section"),
            row.get("section"),
        ),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_ia_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "ia_index": idx,
        "ia_number": safe_text(row.get("IA Number")),
        "party": safe_text(row.get("Party")),
        "date_of_filing": safe_text(row.get("Date of Filing")),
        "next_date": safe_text(row.get("Next Date")),
        "ia_status": safe_text(row.get("IA Status")),
        "classification": safe_text(row.get("Classification")),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_doc_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "document_index": idx,
        "sr_no": first_nonempty(row.get("Sr. No."), row.get("Sr.No."), row.get("Sr No")),
        "document_no": safe_text(row.get("Document No.")),
        "date_of_receiving": safe_text(row.get("Date of Receiving")),
        "filed_by": safe_text(row.get("Filed by")),
        "name_of_advocate": safe_text(row.get("Name of Advocate")),
        "document_filed": safe_text(row.get("Document Filed")),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_order_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "order_index": idx,
        "order_number": first_nonempty(row.get("Order Number"), row.get("Order Number ")),
        "order_on": first_nonempty(row.get("Order on"), row.get("Order On")),
        "judge": safe_text(row.get("Judge")),
        "order_date": safe_text(row.get("Order Date")),
        "order_details": first_nonempty(row.get("Order Details"), row.get("View"), row.get("Details")),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_objection_row(case_id: str, row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "objection_index": idx,
        "sr_no": first_nonempty(row.get("Sr.No."), row.get("Sr. No."), row.get("Sr No")),
        "scrutiny_date": safe_text(row.get("Scrutiny Date")),
        "objection": first_nonempty(row.get("OBJECTION"), row.get("Objection")),
        "objection_compliance_date": first_nonempty(
            row.get("OBJECTION Compliance Date"),
            row.get("Objection Compliance Date"),
        ),
        "receipt_date": safe_text(row.get("Receipt Date")),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def parse_advocate_blocks(case_id: str, blocks: List[Dict[str, Any]], side: str) -> List[Dict[str, Any]]:
    out = []
    for idx, row in enumerate(blocks, start=1):
        raw_block = safe_text(row.get("raw_block_text"))
        if raw_block:
            lines = [safe_text(x) for x in raw_block.split("|") if safe_text(x)]
            party_name = lines[0] if len(lines) >= 1 else ""
            advocate_name = lines[1] if len(lines) >= 2 else ""
        else:
            values = [safe_text(v) for v in row.values() if safe_text(v)]
            party_name = values[0] if len(values) >= 1 else ""
            advocate_name = values[1] if len(values) >= 2 else ""

        out.append(
            {
                "case_id": case_id,
                "side": side,
                "advocate_index": idx,
                "party_name": party_name,
                "advocate_name": advocate_name,
                "raw_json": json.dumps(row, ensure_ascii=False),
            }
        )
    return out


def build_case_row(rec: Dict[str, Any], source_path: Path, input_dir: Path) -> Dict[str, Any]:
    parsed = promote_missing_sections((rec.get("parsed", {}) or {}).copy())
    case_details = parsed.get("case_details", {}) or {}
    case_status = parsed.get("case_status", {}) or {}
    category_details = parsed.get("category_details", {}) or {}
    subordinate = parsed.get("subordinate_court_information", {}) or {}
    kv = parsed.get("kv", {}) or {}

    case_id = infer_case_id({"parsed": parsed, **rec})
    petitioner_guess, respondent_guess = split_parties_from_row_preview(safe_text(rec.get("row_preview")))

    row = {
        "case_id": case_id,
        "court": safe_text(rec.get("court")),
        "year_scraped": rec.get("year"),
        "status_filter": safe_text(rec.get("status_filter")),
        "scraped_at": safe_text(rec.get("scraped_at")),
        "detail_url": safe_text(rec.get("detail_url")),
        "row_preview": safe_text(rec.get("row_preview")),
        "source_file": source_path.name,
        "source_relpath": str(source_path.relative_to(input_dir)),

        "filing_number": safe_text(case_details.get("Filing Number")),
        "filing_date": safe_text(case_details.get("Filing Date")),
        "registration_number": safe_text(case_details.get("Registration Number")),
        "registration_date": safe_text(case_details.get("Registration Date")),
        "e_filno": first_nonempty(case_details.get("e-Filno."), case_details.get("e-Filno")),
        "e_filing_date": safe_text(case_details.get("e-Filing Date")),
        "cnr_number": safe_text(case_details.get("CNR Number")),

        "first_hearing_date": safe_text(case_status.get("First Hearing Date")),
        "next_hearing_date": safe_text(case_status.get("Next Hearing Date")),
        "stage_of_case": safe_text(case_status.get("Stage of Case")),
        "coram": safe_text(case_status.get("Coram")),
        "bench_type": safe_text(case_status.get("Bench Type")),
        "judicial_branch": safe_text(case_status.get("Judicial Branch")),
        "state": safe_text(case_status.get("State")),
        "district": safe_text(case_status.get("District")),

        "category": safe_text(category_details.get("Category")),
        "sub_category": first_nonempty(category_details.get("Sub Category"), category_details.get("SubCategory")),

        "subordinate_court_name": safe_text(subordinate.get("Court Number and Name")),
        "subordinate_case_number_year": safe_text(subordinate.get("Case Number and Year")),
        "subordinate_case_decision_date": safe_text(subordinate.get("Case Decision Date")),
        "subordinate_state": safe_text(subordinate.get("State")),
        "subordinate_district": safe_text(subordinate.get("District")),

        "petitioner_name_guess": petitioner_guess,
        "respondent_name_guess": respondent_guess,
        "history_count": len(parsed.get("history", []) or []),
        "acts_count": len(parsed.get("acts", []) or []),
        "ia_count": len(parsed.get("ia_details", []) or []),
        "document_count": len(parsed.get("document_details", []) or []),
        "order_count": len(parsed.get("orders", []) or []),
        "objection_count": len(parsed.get("objection", []) or []),
        "raw_text_blob_present": 1 if safe_text(parsed.get("text_blob")) else 0,
    }

    for k, v in kv.items():
        col = f"kv__{slugify_col(k)}"
        if col not in row:
            row[col] = safe_text(v)

    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True, help="Directory containing raw scrape outputs")
    ap.add_argument("--out-dir", required=True, help="Directory to write normalized CSV tables")
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    case_rows: List[Dict[str, Any]] = []
    history_rows: List[Dict[str, Any]] = []
    acts_rows: List[Dict[str, Any]] = []
    ia_rows: List[Dict[str, Any]] = []
    doc_rows: List[Dict[str, Any]] = []
    adv_rows: List[Dict[str, Any]] = []
    order_rows: List[Dict[str, Any]] = []
    objection_rows: List[Dict[str, Any]] = []
    subordinate_rows: List[Dict[str, Any]] = []

    files = sorted(input_dir.rglob("*.jsonl"))
    if not files:
        print(f"No JSONL files found in {input_dir}")
        return

    for path in files:
        for rec in read_jsonl(path):
            parsed = promote_missing_sections((rec.get("parsed", {}) or {}).copy())
            case_id = infer_case_id({"parsed": parsed, **rec})

            case_rows.append(build_case_row({**rec, "parsed": parsed}, path, input_dir))

            for idx, row in enumerate(parsed.get("history", []) or [], start=1):
                history_rows.append(normalize_history_row(case_id, row, idx))

            for idx, row in enumerate(parsed.get("acts", []) or [], start=1):
                acts_rows.append(normalize_acts_row(case_id, row, idx))

            for idx, row in enumerate(parsed.get("ia_details", []) or [], start=1):
                ia_rows.append(normalize_ia_row(case_id, row, idx))

            for idx, row in enumerate(parsed.get("document_details", []) or [], start=1):
                doc_rows.append(normalize_doc_row(case_id, row, idx))

            for idx, row in enumerate(parsed.get("orders", []) or [], start=1):
                order_rows.append(normalize_order_row(case_id, row, idx))

            for idx, row in enumerate(parsed.get("objection", []) or [], start=1):
                objection_rows.append(normalize_objection_row(case_id, row, idx))

            adv_rows.extend(parse_advocate_blocks(case_id, parsed.get("petitioners", []) or [], "petitioner"))
            adv_rows.extend(parse_advocate_blocks(case_id, parsed.get("respondents", []) or [], "respondent"))

            subordinate = parsed.get("subordinate_court_information", {}) or {}
            if subordinate:
                subordinate_rows.append(
                    {
                        "case_id": case_id,
                        "court_number_and_name": safe_text(subordinate.get("Court Number and Name")),
                        "case_number_and_year": safe_text(subordinate.get("Case Number and Year")),
                        "case_decision_date": safe_text(subordinate.get("Case Decision Date")),
                        "state": safe_text(subordinate.get("State")),
                        "district": safe_text(subordinate.get("District")),
                        "raw_json": json.dumps(subordinate, ensure_ascii=False),
                    }
                )

    pd.DataFrame(case_rows).to_csv(out_dir / "cases.csv", index=False)
    pd.DataFrame(history_rows).to_csv(out_dir / "case_history.csv", index=False)
    pd.DataFrame(acts_rows).to_csv(out_dir / "acts.csv", index=False)
    pd.DataFrame(ia_rows).to_csv(out_dir / "ia_details.csv", index=False)
    pd.DataFrame(doc_rows).to_csv(out_dir / "document_details.csv", index=False)
    pd.DataFrame(adv_rows).to_csv(out_dir / "advocates.csv", index=False)
    pd.DataFrame(order_rows).to_csv(out_dir / "orders.csv", index=False)
    pd.DataFrame(objection_rows).to_csv(out_dir / "objection.csv", index=False)
    pd.DataFrame(subordinate_rows).to_csv(out_dir / "subordinate_court_information.csv", index=False)

    print(f"Wrote tables to {out_dir}")
    print(
        f"cases={len(case_rows)} "
        f"history={len(history_rows)} "
        f"acts={len(acts_rows)} "
        f"ia={len(ia_rows)} "
        f"docs={len(doc_rows)} "
        f"advocates={len(adv_rows)} "
        f"orders={len(order_rows)} "
        f"objection={len(objection_rows)} "
        f"subordinate={len(subordinate_rows)}"
    )


if __name__ == "__main__":
    main()