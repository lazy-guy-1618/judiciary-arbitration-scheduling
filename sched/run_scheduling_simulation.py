import argparse
from pathlib import Path

import pandas as pd


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


def prepare_dataset(path: str, only_pending: bool = True) -> pd.DataFrame:
    df = pd.read_csv(path)

    for col in [
        "case_age_days",
        "gap_since_last_activity_days",
        "hearing_history_rows",
        "order_count",
        "priority_age_gap_score",
    ]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "case_type" not in df.columns:
        raise ValueError("case_type column missing from scheduling dataset")

    df["case_type"] = df["case_type"].fillna("").astype(str).str.strip()
    df = df[df["case_type"].isin(TARGET_TYPES)].copy()

    if only_pending and "status_filter" in df.columns:
        pending = df[df["status_filter"].astype(str).str.lower().eq("pending")].copy()
        if len(pending) > 0:
            df = pending

    df["score_fcfs_oldest"] = df["case_age_days"]

    df["score_gap_first"] = df["gap_since_last_activity_days"]

    df["score_weighted_age_gap"] = (
        0.50 * df["case_age_days"]
        + 0.40 * df["gap_since_last_activity_days"]
        + 0.10 * df["hearing_history_rows"]
    )

    df["estimated_complexity"] = (
        1.0
        + df["hearing_history_rows"].clip(lower=0)
        + 0.5 * df["order_count"].clip(lower=0)
    )

    # Shorter/less complex cases first. Higher score should be better.
    df["score_sjf_proxy"] = -df["estimated_complexity"]

    # Balanced single-objective score:
    # high age, high gap, many hearings, but mild penalty for complexity.
    df["score_balanced"] = (
        0.45 * df["case_age_days"]
        + 0.35 * df["gap_since_last_activity_days"]
        + 0.15 * df["hearing_history_rows"]
        - 0.05 * df["order_count"]
    )

    return df.reset_index(drop=True)


def select_round_robin(df: pd.DataFrame, capacity: int) -> pd.DataFrame:
    queues = {}
    for ct in TARGET_TYPES:
        queues[ct] = df[df["case_type"] == ct].sort_values(
            ["case_age_days", "gap_since_last_activity_days", "hearing_history_rows"],
            ascending=False,
        ).reset_index(drop=True)

    selected_rows = []
    ptr = {ct: 0 for ct in TARGET_TYPES}

    while len(selected_rows) < capacity:
        moved = False
        for ct in TARGET_TYPES:
            q = queues[ct]
            if ptr[ct] < len(q):
                selected_rows.append(q.iloc[ptr[ct]])
                ptr[ct] += 1
                moved = True
                if len(selected_rows) >= capacity:
                    break
        if not moved:
            break

    if not selected_rows:
        return df.head(0).copy()

    return pd.DataFrame(selected_rows)


def select_cases(df: pd.DataFrame, policy: str, capacity: int) -> pd.DataFrame:
    if policy == "fcfs_oldest_first":
        return df.sort_values("score_fcfs_oldest", ascending=False).head(capacity).copy()

    if policy == "gap_first":
        return df.sort_values("score_gap_first", ascending=False).head(capacity).copy()

    if policy == "weighted_age_gap":
        return df.sort_values("score_weighted_age_gap", ascending=False).head(capacity).copy()

    if policy == "sjf_proxy":
        return df.sort_values("score_sjf_proxy", ascending=False).head(capacity).copy()

    if policy == "balanced_priority":
        return df.sort_values("score_balanced", ascending=False).head(capacity).copy()

    if policy == "round_robin_case_type":
        return select_round_robin(df, capacity)

    raise ValueError(f"Unknown policy: {policy}")


def evaluate(full_df: pd.DataFrame, selected: pd.DataFrame, policy: str, capacity: int) -> dict:
    selected_ids = set(selected["case_id"].astype(str))
    left = full_df[~full_df["case_id"].astype(str).isin(selected_ids)].copy()

    old_threshold = 365

    row = {
        "policy": policy,
        "capacity": capacity,
        "selected_cases": len(selected),
        "pool_size": len(full_df),

        "avg_age_selected": selected["case_age_days"].mean() if len(selected) else 0,
        "median_age_selected": selected["case_age_days"].median() if len(selected) else 0,
        "p90_age_selected": selected["case_age_days"].quantile(0.90) if len(selected) else 0,

        "avg_gap_selected": selected["gap_since_last_activity_days"].mean() if len(selected) else 0,
        "median_gap_selected": selected["gap_since_last_activity_days"].median() if len(selected) else 0,
        "p90_gap_selected": selected["gap_since_last_activity_days"].quantile(0.90) if len(selected) else 0,

        "avg_hearings_selected": selected["hearing_history_rows"].mean() if len(selected) else 0,
        "avg_orders_selected": selected["order_count"].mean() if len(selected) else 0,

        "old_cases_selected": int((selected["case_age_days"] >= old_threshold).sum()) if len(selected) else 0,
        "old_case_selection_rate": float((selected["case_age_days"] >= old_threshold).mean()) if len(selected) else 0,

        "avg_age_left": left["case_age_days"].mean() if len(left) else 0,
        "p90_age_left": left["case_age_days"].quantile(0.90) if len(left) else 0,
        "old_cases_left": int((left["case_age_days"] >= old_threshold).sum()) if len(left) else 0,
    }

    for ct in TARGET_TYPES:
        row[f"{ct}_selected"] = int((selected["case_type"] == ct).sum()) if len(selected) else 0
        row[f"{ct}_share"] = float((selected["case_type"] == ct).mean()) if len(selected) else 0

    return row


def simulate_multiday(df: pd.DataFrame, policy: str, capacity: int, days: int):
    backlog = df.copy()
    logs = []
    schedules = []

    for day in range(1, days + 1):
        if backlog.empty:
            break

        selected = select_cases(backlog, policy, capacity)
        selected = selected.copy()
        selected["sim_day"] = day
        selected["policy"] = policy

        log = evaluate(backlog, selected, policy, capacity)
        log["sim_day"] = day
        logs.append(log)
        schedules.append(selected)

        selected_ids = set(selected["case_id"].astype(str))

        # Phase-1 assumption:
        # once listed, remove from immediate listing backlog.
        # Later this can become stochastic disposal/progress instead of deterministic removal.
        backlog = backlog[~backlog["case_id"].astype(str).isin(selected_ids)].copy()

        # Remaining cases age by one court day.
        backlog["case_age_days"] += 1
        backlog["gap_since_last_activity_days"] += 1

        # Recompute dynamic scores.
        backlog["score_fcfs_oldest"] = backlog["case_age_days"]
        backlog["score_gap_first"] = backlog["gap_since_last_activity_days"]
        backlog["score_weighted_age_gap"] = (
            0.50 * backlog["case_age_days"]
            + 0.40 * backlog["gap_since_last_activity_days"]
            + 0.10 * backlog["hearing_history_rows"]
        )
        backlog["estimated_complexity"] = (
            1.0
            + backlog["hearing_history_rows"].clip(lower=0)
            + 0.5 * backlog["order_count"].clip(lower=0)
        )
        backlog["score_sjf_proxy"] = -backlog["estimated_complexity"]
        backlog["score_balanced"] = (
            0.45 * backlog["case_age_days"]
            + 0.35 * backlog["gap_since_last_activity_days"]
            + 0.15 * backlog["hearing_history_rows"]
            - 0.05 * backlog["order_count"]
        )

    log_df = pd.DataFrame(logs)
    schedule_df = pd.concat(schedules, ignore_index=True) if schedules else pd.DataFrame()
    return log_df, schedule_df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--out-dir", default="output/scheduling_results")
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--include-disposed", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = prepare_dataset(args.input, only_pending=not args.include_disposed)

    print("Scheduling pool:", df.shape)
    print("\nCase type counts:")
    print(df["case_type"].value_counts(dropna=False))

    if "status_filter" in df.columns:
        print("\nStatus counts:")
        print(df["status_filter"].value_counts(dropna=False))

    policies = [
        "fcfs_oldest_first",
        "gap_first",
        "weighted_age_gap",
        "balanced_priority",
        "sjf_proxy",
        "round_robin_case_type",
    ]

    day1_rows = []
    all_logs = []
    all_schedules = []

    for policy in policies:
        selected = select_cases(df, policy, args.capacity)
        selected.to_csv(out_dir / f"day1_schedule_{policy}.csv", index=False)

        day1_rows.append(evaluate(df, selected, policy, args.capacity))

        logs, schedules = simulate_multiday(df, policy, args.capacity, args.days)
        all_logs.append(logs)
        all_schedules.append(schedules)

    day1_summary = pd.DataFrame(day1_rows)
    day1_summary.to_csv(out_dir / "policy_day1_summary.csv", index=False)

    multi_day_metrics = pd.concat(all_logs, ignore_index=True)
    multi_day_schedules = pd.concat(all_schedules, ignore_index=True)

    multi_day_metrics.to_csv(out_dir / "multi_day_metrics.csv", index=False)
    multi_day_schedules.to_csv(out_dir / "multi_day_schedules.csv", index=False)

    print("\nWrote outputs to:", out_dir)

    show_cols = [
        "policy",
        "selected_cases",
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
    show_cols = [c for c in show_cols if c in day1_summary.columns]

    print("\nDay-1 summary:")
    print(day1_summary[show_cols].sort_values("avg_age_selected", ascending=False))


if __name__ == "__main__":
    main()
