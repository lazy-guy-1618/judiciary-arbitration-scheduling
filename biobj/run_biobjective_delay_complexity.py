import argparse
from pathlib import Path

import pandas as pd


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


def normalise(s):
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    mn, mx = s.min(), s.max()
    if mx <= mn:
        return pd.Series(0.0, index=s.index)
    return (s - mn) / (mx - mn)


def load_pool(path):
    df = pd.read_csv(path)

    for col in [
        "case_age_days",
        "gap_since_last_activity_days",
        "hearing_history_rows",
        "order_count",
    ]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["case_type"] = df["case_type"].fillna("").astype(str).str.strip()
    df = df[df["case_type"].isin(TARGET_TYPES)].copy()

    df["delay_raw"] = (
        0.50 * df["case_age_days"]
        + 0.40 * df["gap_since_last_activity_days"]
        + 0.10 * df["hearing_history_rows"]
    )

    df["complexity_raw"] = (
        df["hearing_history_rows"]
        + 0.50 * df["order_count"]
    )

    df["delay_norm"] = normalise(df["delay_raw"])
    df["complexity_norm"] = normalise(df["complexity_raw"])

    return df.reset_index(drop=True)


def evaluate(pool, selected, complexity_weight, capacity):
    selected_ids = set(selected["case_id"].astype(str))
    left = pool[~pool["case_id"].astype(str).isin(selected_ids)].copy()

    row = {
        "complexity_weight": complexity_weight,
        "capacity": capacity,
        "selected_cases": len(selected),
        "pool_size": len(pool),

        "delay_mean": selected["delay_raw"].mean(),
        "complexity_mean": selected["complexity_raw"].mean(),

        "avg_age_selected": selected["case_age_days"].mean(),
        "avg_gap_selected": selected["gap_since_last_activity_days"].mean(),
        "avg_hearings_selected": selected["hearing_history_rows"].mean(),
        "avg_orders_selected": selected["order_count"].mean(),

        "old_cases_selected": int((selected["case_age_days"] >= 365).sum()),
        "avg_age_left": left["case_age_days"].mean() if len(left) else 0,
        "old_cases_left": int((left["case_age_days"] >= 365).sum()),
    }

    for ct in TARGET_TYPES:
        row[f"{ct}_selected"] = int((selected["case_type"] == ct).sum())
        row[f"{ct}_share"] = float((selected["case_type"] == ct).mean())

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--out-dir", default="output/biobjective_delay_complexity_cap20")
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument(
        "--weights",
        nargs="*",
        type=float,
        default=[0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0],
    )
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pool = load_pool(args.input)

    rows = []
    selected_all = []

    for w in args.weights:
        df = pool.copy()

        # Higher score is better:
        # delay is rewarded, complexity is penalised.
        df["bi_score"] = (
            (1.0 - w) * df["delay_norm"]
            - w * df["complexity_norm"]
        )

        selected = df.sort_values("bi_score", ascending=False).head(args.capacity).copy()
        selected["complexity_weight"] = w
        selected["rank_in_schedule"] = range(1, len(selected) + 1)

        selected.to_csv(out / f"selected_complexity_lambda_{w:.2f}.csv", index=False)

        rows.append(evaluate(pool, selected, w, args.capacity))
        selected_all.append(selected)

    summary = pd.DataFrame(rows)
    summary.to_csv(out / "delay_complexity_summary.csv", index=False)
    pd.concat(selected_all, ignore_index=True).to_csv(out / "delay_complexity_selected_all.csv", index=False)

    print(summary.to_string(index=False))
    print("\nWrote:", out)


if __name__ == "__main__":
    main()
