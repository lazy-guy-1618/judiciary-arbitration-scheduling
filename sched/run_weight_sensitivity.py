import argparse
from pathlib import Path

import pandas as pd


PROFILES = {
    "age_dominant": {
        "alpha_age": 0.70,
        "beta_gap": 0.20,
        "gamma_hearings": 0.10,
        "delta_orders": 0.00,
    },
    "gap_dominant": {
        "alpha_age": 0.30,
        "beta_gap": 0.60,
        "gamma_hearings": 0.10,
        "delta_orders": 0.00,
    },
    "history_dominant": {
        "alpha_age": 0.40,
        "beta_gap": 0.20,
        "gamma_hearings": 0.40,
        "delta_orders": 0.00,
    },
    "balanced": {
        "alpha_age": 0.50,
        "beta_gap": 0.40,
        "gamma_hearings": 0.10,
        "delta_orders": 0.00,
    },
    "complexity_penalty": {
        "alpha_age": 0.45,
        "beta_gap": 0.35,
        "gamma_hearings": 0.15,
        "delta_orders": 0.05,
    },
}


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


def load_pool(path, include_disposed=False):
    df = pd.read_csv(path)

    required = [
        "case_age_days",
        "gap_since_last_activity_days",
        "hearing_history_rows",
        "order_count",
    ]

    for col in required:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["case_type"] = df["case_type"].fillna("").astype(str).str.strip()
    df = df[df["case_type"].isin(TARGET_TYPES)].copy()

    if not include_disposed and "status_filter" in df.columns:
        pending = df[df["status_filter"].astype(str).str.lower().eq("pending")].copy()
        if len(pending) > 0:
            df = pending

    return df.reset_index(drop=True)


def score_cases(df, profile):
    p = PROFILES[profile]
    score = (
        p["alpha_age"] * df["case_age_days"]
        + p["beta_gap"] * df["gap_since_last_activity_days"]
        + p["gamma_hearings"] * df["hearing_history_rows"]
        - p["delta_orders"] * df["order_count"]
    )
    return score


def evaluate(pool, selected, profile, capacity):
    selected_ids = set(selected["case_id"].astype(str))
    left = pool[~pool["case_id"].astype(str).isin(selected_ids)].copy()

    old_threshold = 365

    row = {
        "profile": profile,
        "capacity": capacity,
        "selected_cases": len(selected),
        "pool_size": len(pool),
        **PROFILES[profile],

        "avg_age_selected": selected["case_age_days"].mean(),
        "median_age_selected": selected["case_age_days"].median(),
        "p90_age_selected": selected["case_age_days"].quantile(0.90),

        "avg_gap_selected": selected["gap_since_last_activity_days"].mean(),
        "median_gap_selected": selected["gap_since_last_activity_days"].median(),
        "p90_gap_selected": selected["gap_since_last_activity_days"].quantile(0.90),

        "avg_hearings_selected": selected["hearing_history_rows"].mean(),
        "avg_orders_selected": selected["order_count"].mean(),

        "old_cases_selected": int((selected["case_age_days"] >= old_threshold).sum()),
        "old_cases_left": int((left["case_age_days"] >= old_threshold).sum()),
        "avg_age_left": left["case_age_days"].mean() if len(left) else 0,
        "p90_age_left": left["case_age_days"].quantile(0.90) if len(left) else 0,
    }

    for ct in TARGET_TYPES:
        row[f"{ct}_selected"] = int((selected["case_type"] == ct).sum())
        row[f"{ct}_share"] = float((selected["case_type"] == ct).mean())

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--out-dir", default="output/weight_sensitivity")
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument("--include-disposed", action="store_true")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pool = load_pool(args.input, include_disposed=args.include_disposed)

    print("Pool:", pool.shape)
    print(pool["case_type"].value_counts(dropna=False))

    summary_rows = []

    for profile in PROFILES:
        df = pool.copy()
        df["profile"] = profile
        df["weight_score"] = score_cases(df, profile)

        selected = df.sort_values("weight_score", ascending=False).head(args.capacity).copy()

        selected.to_csv(out / f"selected_{profile}.csv", index=False)
        summary_rows.append(evaluate(pool, selected, profile, args.capacity))

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out / "weight_sensitivity_summary.csv", index=False)

    print("\nWrote:", out / "weight_sensitivity_summary.csv")

    cols = [
        "profile",
        "alpha_age",
        "beta_gap",
        "gamma_hearings",
        "delta_orders",
        "avg_age_selected",
        "avg_gap_selected",
        "avg_hearings_selected",
        "avg_orders_selected",
        "old_cases_selected",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "avg_age_left",
        "old_cases_left",
    ]
    print(summary[cols].sort_values("avg_age_selected", ascending=False))


if __name__ == "__main__":
    main()
