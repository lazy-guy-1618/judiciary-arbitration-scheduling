import argparse
from pathlib import Path

import pandas as pd


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


PROFILES = {
    "delay_only": {
        "w_delay": 1.00,
        "w_fairness": 0.00,
        "w_complexity": 0.00,
    },
    "fairness_only": {
        "w_delay": 0.00,
        "w_fairness": 1.00,
        "w_complexity": 0.00,
    },
    "complexity_only": {
        "w_delay": 0.00,
        "w_fairness": 0.00,
        "w_complexity": 1.00,
    },
    "delay_fairness": {
        "w_delay": 0.60,
        "w_fairness": 0.30,
        "w_complexity": 0.10,
    },
    "delay_complexity": {
        "w_delay": 0.60,
        "w_fairness": 0.10,
        "w_complexity": 0.30,
    },
    "fair_balanced": {
        "w_delay": 0.40,
        "w_fairness": 0.40,
        "w_complexity": 0.20,
    },
    "balanced_all": {
        "w_delay": 0.50,
        "w_fairness": 0.30,
        "w_complexity": 0.20,
    },
}


def normalise(series):
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    mn = series.min()
    mx = series.max()
    if mx <= mn:
        return pd.Series(0.0, index=series.index)
    return (series - mn) / (mx - mn)


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

    if "case_type" not in df.columns:
        raise ValueError("case_type column missing")

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


def fairness_l1(counts, n, target_shares):
    if n <= 0:
        return sum(abs(0.0 - target_shares[k]) for k in TARGET_TYPES)

    return sum(
        abs((counts.get(k, 0) / n) - target_shares[k])
        for k in TARGET_TYPES
    )


def greedy_multiobjective_select(pool, capacity, profile_name):
    weights = PROFILES[profile_name]

    target_shares = (
        pool["case_type"]
        .value_counts(normalize=True)
        .reindex(TARGET_TYPES)
        .fillna(0.0)
        .to_dict()
    )

    selected_indices = []
    remaining = set(pool.index.tolist())
    counts = {k: 0 for k in TARGET_TYPES}

    for _ in range(capacity):
        if not remaining:
            break

        current_n = len(selected_indices)
        current_fair_error = fairness_l1(counts, current_n, target_shares)

        best_idx = None
        best_score = None

        for idx in remaining:
            row = pool.loc[idx]
            ct = row["case_type"]

            new_counts = counts.copy()
            new_counts[ct] += 1

            new_fair_error = fairness_l1(new_counts, current_n + 1, target_shares)
            fairness_gain = current_fair_error - new_fair_error

            score = (
                weights["w_delay"] * row["delay_norm"]
                + weights["w_fairness"] * fairness_gain
                - weights["w_complexity"] * row["complexity_norm"]
            )

            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx

        selected_indices.append(best_idx)
        selected_type = pool.loc[best_idx, "case_type"]
        counts[selected_type] += 1
        remaining.remove(best_idx)

    selected = pool.loc[selected_indices].copy()
    selected["profile"] = profile_name
    selected["rank_in_schedule"] = range(1, len(selected) + 1)

    return selected, target_shares


def evaluate(pool, selected, profile_name, capacity, target_shares):
    selected_ids = set(selected["case_id"].astype(str))
    left = pool[~pool["case_id"].astype(str).isin(selected_ids)].copy()

    weights = PROFILES[profile_name]

    counts = (
        selected["case_type"]
        .value_counts()
        .reindex(TARGET_TYPES)
        .fillna(0)
        .astype(int)
        .to_dict()
    )

    n = max(len(selected), 1)

    selected_shares = {k: counts[k] / n for k in TARGET_TYPES}

    fairness_l1_error = sum(
        abs(selected_shares[k] - target_shares[k])
        for k in TARGET_TYPES
    )

    fairness_score = 1 - fairness_l1_error / 2

    row = {
        "profile": profile_name,
        "capacity": capacity,
        "selected_cases": len(selected),
        "pool_size": len(pool),

        "w_delay": weights["w_delay"],
        "w_fairness": weights["w_fairness"],
        "w_complexity": weights["w_complexity"],

        "delay_mean": selected["delay_raw"].mean(),
        "delay_sum": selected["delay_raw"].sum(),

        "fairness_score": fairness_score,
        "fairness_l1_error": fairness_l1_error,

        "complexity_mean": selected["complexity_raw"].mean(),

        "avg_age_selected": selected["case_age_days"].mean(),
        "avg_gap_selected": selected["gap_since_last_activity_days"].mean(),
        "avg_hearings_selected": selected["hearing_history_rows"].mean(),
        "avg_orders_selected": selected["order_count"].mean(),

        "old_cases_selected": int((selected["case_age_days"] >= 365).sum()),
        "avg_age_left": left["case_age_days"].mean() if len(left) else 0,
        "old_cases_left": int((left["case_age_days"] >= 365).sum()),
    }

    for k in TARGET_TYPES:
        row[f"{k}_selected"] = counts[k]
        row[f"{k}_share"] = selected_shares[k]
        row[f"{k}_target_share"] = target_shares[k]

    return row


def pareto_filter(summary):
    objectives = [
        ("delay_mean", "max"),
        ("fairness_score", "max"),
        ("complexity_mean", "min"),
    ]

    is_pareto = []

    for i, row_i in summary.iterrows():
        dominated = False

        for j, row_j in summary.iterrows():
            if i == j:
                continue

            better_or_equal_all = True
            strictly_better_one = False

            for col, direction in objectives:
                if direction == "max":
                    if row_j[col] < row_i[col]:
                        better_or_equal_all = False
                    if row_j[col] > row_i[col]:
                        strictly_better_one = True
                else:
                    if row_j[col] > row_i[col]:
                        better_or_equal_all = False
                    if row_j[col] < row_i[col]:
                        strictly_better_one = True

            if better_or_equal_all and strictly_better_one:
                dominated = True
                break

        is_pareto.append(not dominated)

    out = summary.copy()
    out["is_pareto"] = is_pareto
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--out-dir", default="output/multiobjective_results_cap20")
    parser.add_argument("--capacity", type=int, default=20)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pool = load_pool(args.input)

    print("Pool:", pool.shape)
    print(pool["case_type"].value_counts())

    summary_rows = []
    selected_all = []

    for profile_name in PROFILES:
        selected, target_shares = greedy_multiobjective_select(
            pool,
            args.capacity,
            profile_name,
        )

        selected.to_csv(out_dir / f"selected_{profile_name}.csv", index=False)
        selected_all.append(selected)

        summary_rows.append(
            evaluate(pool, selected, profile_name, args.capacity, target_shares)
        )

    summary = pd.DataFrame(summary_rows)
    summary = pareto_filter(summary)

    summary.to_csv(out_dir / "multiobjective_summary.csv", index=False)
    pd.concat(selected_all, ignore_index=True).to_csv(
        out_dir / "multiobjective_selected_all.csv",
        index=False,
    )

    print("\nWrote:", out_dir / "multiobjective_summary.csv")

    show = [
        "profile",
        "w_delay",
        "w_fairness",
        "w_complexity",
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "avg_age_selected",
        "old_cases_selected",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "is_pareto",
    ]

    print(summary[show].to_string(index=False))


if __name__ == "__main__":
    main()
