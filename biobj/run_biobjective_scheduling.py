import argparse
from pathlib import Path

import pandas as pd


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


def normalise(s):
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    mn = s.min()
    mx = s.max()
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

    df["delay_score_raw"] = (
        0.50 * df["case_age_days"]
        + 0.40 * df["gap_since_last_activity_days"]
        + 0.10 * df["hearing_history_rows"]
    )

    df["delay_score_norm"] = normalise(df["delay_score_raw"])

    return df.reset_index(drop=True)


def fairness_l1(counts, n, target_shares):
    if n <= 0:
        return sum(abs(0.0 - target_shares[k]) for k in TARGET_TYPES)

    return sum(
        abs((counts.get(k, 0) / n) - target_shares[k])
        for k in TARGET_TYPES
    )


def greedy_select(pool, capacity, fairness_weight):
    target_shares = (
        pool["case_type"]
        .value_counts(normalize=True)
        .reindex(TARGET_TYPES)
        .fillna(0)
        .to_dict()
    )

    remaining = set(pool.index.tolist())
    selected_indices = []
    counts = {k: 0 for k in TARGET_TYPES}

    for _ in range(capacity):
        if not remaining:
            break

        selected_n = len(selected_indices)
        current_error = fairness_l1(counts, selected_n, target_shares)

        best_idx = None
        best_score = None

        for idx in remaining:
            row = pool.loc[idx]
            ct = row["case_type"]

            new_counts = counts.copy()
            new_counts[ct] += 1

            new_error = fairness_l1(new_counts, selected_n + 1, target_shares)
            fairness_gain = current_error - new_error

            score = (
                (1.0 - fairness_weight) * row["delay_score_norm"]
                + fairness_weight * fairness_gain
            )

            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx

        selected_indices.append(best_idx)
        selected_type = pool.loc[best_idx, "case_type"]
        counts[selected_type] += 1
        remaining.remove(best_idx)

    selected = pool.loc[selected_indices].copy()
    selected["fairness_weight"] = fairness_weight
    selected["rank_in_schedule"] = range(1, len(selected) + 1)

    return selected, target_shares


def evaluate(pool, selected, fairness_weight, capacity, target_shares):
    selected_ids = set(selected["case_id"].astype(str))
    left = pool[~pool["case_id"].astype(str).isin(selected_ids)].copy()

    counts = (
        selected["case_type"]
        .value_counts()
        .reindex(TARGET_TYPES)
        .fillna(0)
        .astype(int)
        .to_dict()
    )

    n = max(len(selected), 1)

    selected_shares = {
        k: counts[k] / n
        for k in TARGET_TYPES
    }

    fairness_error = sum(
        abs(selected_shares[k] - target_shares[k])
        for k in TARGET_TYPES
    )

    fairness_score = 1.0 - fairness_error / 2.0

    row = {
        "fairness_weight": fairness_weight,
        "capacity": capacity,
        "selected_cases": len(selected),
        "pool_size": len(pool),

        "delay_objective_sum": selected["delay_score_raw"].sum(),
        "delay_objective_mean": selected["delay_score_raw"].mean(),

        "avg_age_selected": selected["case_age_days"].mean(),
        "avg_gap_selected": selected["gap_since_last_activity_days"].mean(),
        "avg_hearings_selected": selected["hearing_history_rows"].mean(),
        "avg_orders_selected": selected["order_count"].mean(),

        "old_cases_selected": int((selected["case_age_days"] >= 365).sum()),
        "avg_age_left": left["case_age_days"].mean() if len(left) else 0,
        "old_cases_left": int((left["case_age_days"] >= 365).sum()),

        "fairness_l1_error": fairness_error,
        "fairness_score": fairness_score,
    }

    for k in TARGET_TYPES:
        row[f"{k}_selected"] = counts[k]
        row[f"{k}_share"] = selected_shares[k]
        row[f"{k}_target_share"] = target_shares[k]

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--out-dir", default="output/biobjective_results_cap20")
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument(
        "--weights",
        nargs="*",
        type=float,
        default=[0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0],
    )

    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pool = load_pool(args.input)

    print("Pool:", pool.shape)
    print(pool["case_type"].value_counts())

    summary_rows = []
    all_selected = []

    for w in args.weights:
        selected, target_shares = greedy_select(pool, args.capacity, w)

        selected.to_csv(out_dir / f"selected_lambda_{w:.2f}.csv", index=False)

        summary_rows.append(
            evaluate(pool, selected, w, args.capacity, target_shares)
        )

        all_selected.append(selected)

    summary = pd.DataFrame(summary_rows)
    selected_all = pd.concat(all_selected, ignore_index=True)

    summary.to_csv(out_dir / "biobjective_summary.csv", index=False)
    selected_all.to_csv(out_dir / "biobjective_selected_all.csv", index=False)

    print("\nWrote:", out_dir / "biobjective_summary.csv")

    show = [
        "fairness_weight",
        "delay_objective_mean",
        "fairness_l1_error",
        "fairness_score",
        "avg_age_selected",
        "avg_gap_selected",
        "old_cases_selected",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "avg_age_left",
        "old_cases_left",
    ]

    print(summary[show].to_string(index=False))


if __name__ == "__main__":
    main()
