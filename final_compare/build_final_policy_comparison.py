import argparse
import glob
import re
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


TARGET_TYPES = ["FMAT", "AOCOM", "ADCOM"]


REPORT_KEEP = {
    # Single-objective representative policies
    ("single", "fcfs_oldest_first"),
    ("single", "gap_first"),
    ("single", "weighted_age_gap"),
    ("single", "sjf_proxy"),
    ("single", "round_robin_case_type"),

    # Bi-objective delay vs fairness representative lambdas
    ("bi_delay_fairness", "lambda_0.00"),
    ("bi_delay_fairness", "lambda_0.75"),
    ("bi_delay_fairness", "lambda_1.00"),

    # Bi-objective delay vs complexity representative lambdas
    ("bi_delay_complexity", "lambda_0.00"),
    ("bi_delay_complexity", "lambda_0.50"),
    ("bi_delay_complexity", "lambda_1.00"),

    # Multi-objective representative profiles
    ("multi", "delay_only"),
    ("multi", "fairness_only"),
    ("multi", "complexity_only"),
    ("multi", "delay_fairness"),
    ("multi", "balanced_all"),
}


PRETTY_FAMILY = {
    "single": "Single-objective",
    "bi_delay_fairness": "Bi-objective: delay-fairness",
    "bi_delay_complexity": "Bi-objective: delay-complexity",
    "multi": "Multi-objective",
}


def normalise_case_type(df):
    df = df.copy()
    if "case_type" not in df.columns:
        raise ValueError("case_type missing in selected schedule")
    df["case_type"] = df["case_type"].fillna("").astype(str).str.strip()
    return df[df["case_type"].isin(TARGET_TYPES)].copy()


def ensure_numeric(df, cols):
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def compute_target_shares(pool):
    pool = normalise_case_type(pool)
    shares = (
        pool["case_type"]
        .value_counts(normalize=True)
        .reindex(TARGET_TYPES)
        .fillna(0.0)
        .to_dict()
    )
    return shares


def fairness_score(selected, target_shares):
    if len(selected) == 0:
        return 0.0, 2.0

    selected = normalise_case_type(selected)
    selected_shares = (
        selected["case_type"]
        .value_counts(normalize=True)
        .reindex(TARGET_TYPES)
        .fillna(0.0)
        .to_dict()
    )

    l1_error = sum(
        abs(selected_shares[k] - target_shares[k])
        for k in TARGET_TYPES
    )

    score = 1.0 - l1_error / 2.0
    return score, l1_error


def evaluate_schedule(df, family, policy, source_file, target_shares):
    df = normalise_case_type(df)
    df = ensure_numeric(
        df,
        [
            "case_age_days",
            "gap_since_last_activity_days",
            "hearing_history_rows",
            "order_count",
        ],
    )

    if len(df) == 0:
        return None

    df["delay_score"] = (
        0.50 * df["case_age_days"]
        + 0.40 * df["gap_since_last_activity_days"]
        + 0.10 * df["hearing_history_rows"]
    )

    df["complexity_score"] = (
        df["hearing_history_rows"]
        + 0.50 * df["order_count"]
    )

    f_score, f_l1 = fairness_score(df, target_shares)

    row = {
        "family": family,
        "family_label": PRETTY_FAMILY.get(family, family),
        "policy": policy,
        "source_file": source_file,
        "selected_cases": len(df),

        "delay_mean": df["delay_score"].mean(),
        "delay_sum": df["delay_score"].sum(),

        "fairness_score": f_score,
        "fairness_l1_error": f_l1,

        "complexity_mean": df["complexity_score"].mean(),

        "avg_age_selected": df["case_age_days"].mean(),
        "avg_gap_selected": df["gap_since_last_activity_days"].mean(),
        "avg_hearings_selected": df["hearing_history_rows"].mean(),
        "avg_orders_selected": df["order_count"].mean(),

        "old_cases_selected": int((df["case_age_days"] >= 365).sum()),
    }

    for ct in TARGET_TYPES:
        row[f"{ct}_selected"] = int((df["case_type"] == ct).sum())
        row[f"{ct}_share"] = float((df["case_type"] == ct).mean())

    return row


def parse_lambda_from_name(path):
    name = Path(path).stem
    nums = re.findall(r"(\d+\.\d+|\d+)", name)
    if not nums:
        return name
    try:
        val = float(nums[-1])
        return f"lambda_{val:.2f}"
    except Exception:
        return name


def load_single_objective(single_dir):
    rows = []
    for path in sorted(glob.glob(str(Path(single_dir) / "day1_schedule_*.csv"))):
        name = Path(path).stem.replace("day1_schedule_", "")
        rows.append(("single", name, path))
    return rows


def load_bi_delay_fairness(bi_dir):
    rows = []
    for path in sorted(glob.glob(str(Path(bi_dir) / "selected_lambda_*.csv"))):
        policy = parse_lambda_from_name(path)
        rows.append(("bi_delay_fairness", policy, path))
    return rows


def load_bi_delay_complexity(bi_complexity_dir):
    rows = []
    for path in sorted(glob.glob(str(Path(bi_complexity_dir) / "selected_complexity_lambda_*.csv"))):
        policy = parse_lambda_from_name(path)
        rows.append(("bi_delay_complexity", policy, path))
    return rows


def load_multiobjective(multi_dir):
    rows = []
    for path in sorted(glob.glob(str(Path(multi_dir) / "selected_*.csv"))):
        stem = Path(path).stem
        if stem == "selected_all":
            continue
        policy = stem.replace("selected_", "")
        rows.append(("multi", policy, path))
    return rows


def pareto_filter(df):
    out = df.copy()
    flags = []

    for i, row_i in out.iterrows():
        dominated = False

        for j, row_j in out.iterrows():
            if i == j:
                continue

            better_or_equal = (
                row_j["delay_mean"] >= row_i["delay_mean"]
                and row_j["fairness_score"] >= row_i["fairness_score"]
                and row_j["complexity_mean"] <= row_i["complexity_mean"]
            )

            strictly_better = (
                row_j["delay_mean"] > row_i["delay_mean"]
                or row_j["fairness_score"] > row_i["fairness_score"]
                or row_j["complexity_mean"] < row_i["complexity_mean"]
            )

            if better_or_equal and strictly_better:
                dominated = True
                break

        flags.append(not dominated)

    out["is_pareto"] = flags
    return out


def make_subset(df):
    keep = df.apply(lambda r: (r["family"], r["policy"]) in REPORT_KEEP, axis=1)
    subset = df[keep].copy()

    if len(subset) == 0:
        subset = df.copy()

    subset = subset.sort_values(
        ["family", "policy"],
        ascending=[True, True],
    ).reset_index(drop=True)

    subset["point_id"] = range(1, len(subset) + 1)
    subset["plot_label"] = subset["point_id"].astype(str)

    return subset


def save_compact_tables(df, subset, out_dir):
    cols = [
        "point_id",
        "family_label",
        "policy",
        "selected_cases",
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "avg_age_selected",
        "avg_gap_selected",
        "old_cases_selected",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "is_pareto",
    ]

    all_compact = df.copy()
    if "point_id" not in all_compact.columns:
        all_compact["point_id"] = ""

    for c in all_compact.select_dtypes(include="number").columns:
        all_compact[c] = all_compact[c].round(3)

    all_compact.to_csv(out_dir / "final_policy_comparison_compact_all.csv", index=False)

    subset_compact = subset[cols].copy()
    for c in subset_compact.select_dtypes(include="number").columns:
        subset_compact[c] = subset_compact[c].round(3)

    subset_compact.to_csv(out_dir / "final_policy_comparison_report_subset.csv", index=False)

    label_map = subset[
        [
            "point_id",
            "family_label",
            "policy",
            "delay_mean",
            "fairness_score",
            "complexity_mean",
            "FMAT_selected",
            "AOCOM_selected",
            "ADCOM_selected",
            "is_pareto",
        ]
    ].copy()

    for c in label_map.select_dtypes(include="number").columns:
        label_map[c] = label_map[c].round(3)

    label_map.to_csv(out_dir / "plot_point_label_map.csv", index=False)


def scatter_with_ids(df, xcol, ycol, title, xlabel, ylabel, outpath):
    plt.figure(figsize=(9, 6))

    for family, sub in df.groupby("family_label"):
        plt.scatter(sub[xcol], sub[ycol], s=80, label=family)

        for _, row in sub.iterrows():
            plt.annotate(
                str(row["point_id"]),
                (row[xcol], row[ycol]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9,
            )

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def bar_by_policy(df, metric, title, ylabel, outpath):
    d = df.sort_values(metric, ascending=True).copy()
    labels = d["point_id"].astype(str)

    plt.figure(figsize=(9, 6))
    plt.barh(labels, d[metric])
    plt.xlabel(ylabel)
    plt.ylabel("Policy point ID")
    plt.title(title)

    for i, v in enumerate(d[metric]):
        plt.text(v, i, f" {v:.2f}", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_mix_plot(df, outpath):
    d = df.copy()

    total = d[["FMAT_selected", "AOCOM_selected", "ADCOM_selected"]].sum(axis=1)
    d["FMAT_plot"] = d["FMAT_selected"] / total
    d["AOCOM_plot"] = d["AOCOM_selected"] / total
    d["ADCOM_plot"] = d["ADCOM_selected"] / total

    x = range(len(d))
    bottom = [0] * len(d)

    plt.figure(figsize=(11, 6))

    for col, label in [
        ("FMAT_plot", "FMAT"),
        ("AOCOM_plot", "AOCOM"),
        ("ADCOM_plot", "ADCOM"),
    ]:
        vals = d[col].fillna(0).tolist()
        plt.bar(x, vals, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, vals)]

    plt.xticks(list(x), d["point_id"].astype(str), rotation=0)
    plt.xlabel("Policy point ID")
    plt.ylabel("Selected case-type share")
    plt.title("Case-type composition across representative policies")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def parallel_plot(df, outpath):
    metrics = [
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "avg_age_selected",
        "old_cases_selected",
    ]

    d = df[["point_id", "family_label", "policy"] + metrics].copy()

    for m in metrics:
        mn = d[m].min()
        mx = d[m].max()
        if mx > mn:
            d[m] = (d[m] - mn) / (mx - mn)
        else:
            d[m] = 0

    plt.figure(figsize=(11, 6.5))
    x = list(range(len(metrics)))

    for _, row in d.iterrows():
        plt.plot(
            x,
            [row[m] for m in metrics],
            marker="o",
            linewidth=1.4,
            label=str(row["point_id"]),
        )

    plt.xticks(x, metrics, rotation=20, ha="right")
    plt.ylabel("Normalised value")
    plt.title("Normalised comparison of representative schedules")
    plt.legend(title="Point ID", fontsize=7, ncol=3)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def write_interpretation(df, subset, out_dir):
    best_delay = df.loc[df["delay_mean"].idxmax()]
    best_fairness = df.loc[df["fairness_score"].idxmax()]
    best_complexity = df.loc[df["complexity_mean"].idxmin()]

    lines = []
    lines.append("# Final Unified Comparison Interpretation\n")
    lines.append("This table evaluates all selected schedules under the same three objective metrics:\n")
    lines.append("- Delay mean: higher is better.\n")
    lines.append("- Fairness score: higher is better.\n")
    lines.append("- Complexity mean: lower is better.\n\n")

    lines.append("## Extremes\n")
    lines.append(
        f"- Highest delay score: {best_delay['family_label']} / {best_delay['policy']} "
        f"with delay_mean={best_delay['delay_mean']:.3f}, "
        f"fairness_score={best_delay['fairness_score']:.3f}, "
        f"complexity_mean={best_delay['complexity_mean']:.3f}.\n"
    )
    lines.append(
        f"- Highest fairness score: {best_fairness['family_label']} / {best_fairness['policy']} "
        f"with delay_mean={best_fairness['delay_mean']:.3f}, "
        f"fairness_score={best_fairness['fairness_score']:.3f}, "
        f"complexity_mean={best_fairness['complexity_mean']:.3f}.\n"
    )
    lines.append(
        f"- Lowest complexity: {best_complexity['family_label']} / {best_complexity['policy']} "
        f"with delay_mean={best_complexity['delay_mean']:.3f}, "
        f"fairness_score={best_complexity['fairness_score']:.3f}, "
        f"complexity_mean={best_complexity['complexity_mean']:.3f}.\n\n"
    )

    lines.append("## Main takeaway\n")
    lines.append(
        "Single-objective policies occupy extreme regions of the objective space: "
        "delay-oriented policies are strong on delay but weaker on representation, "
        "SJF-like policies reduce complexity but lose delay priority, and round-robin improves representation "
        "but sacrifices delay. Bi-objective and multi-objective schedules provide intermediate, controllable "
        "trade-off points between delay, fairness, and complexity.\n"
    )

    with open(out_dir / "final_interpretation.md", "w") as f:
        f.writelines(lines)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--pool", default="output/features/scheduling_case_dataset.csv")
    parser.add_argument("--single-dir", default="output/scheduling_results")
    parser.add_argument("--bi-dir", default="output/biobjective_results_cap20")
    parser.add_argument("--bi-complexity-dir", default="output/biobjective_delay_complexity_cap20")
    parser.add_argument("--multi-dir", default="output/multiobjective_results_cap20")
    parser.add_argument("--out-dir", default="output/final_policy_comparison")

    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    pool = pd.read_csv(args.pool)
    target_shares = compute_target_shares(pool)

    schedule_sources = []
    schedule_sources.extend(load_single_objective(args.single_dir))
    schedule_sources.extend(load_bi_delay_fairness(args.bi_dir))
    schedule_sources.extend(load_bi_delay_complexity(args.bi_complexity_dir))
    schedule_sources.extend(load_multiobjective(args.multi_dir))

    if not schedule_sources:
        raise RuntimeError("No selected schedule files found. Check input directories.")

    rows = []

    for family, policy, path in schedule_sources:
        try:
            selected = pd.read_csv(path)
            row = evaluate_schedule(selected, family, policy, path, target_shares)
            if row is not None:
                rows.append(row)
        except Exception as e:
            print(f"Skipping {path}: {e}")

    if not rows:
        raise RuntimeError("No valid schedules could be evaluated.")

    df = pd.DataFrame(rows)
    df = pareto_filter(df)
    df = df.sort_values(["family", "policy"]).reset_index(drop=True)

    subset = make_subset(df)
    df.to_csv(out_dir / "final_policy_comparison_all.csv", index=False)

    save_compact_tables(df, subset, out_dir)

    scatter_with_ids(
        subset,
        "fairness_score",
        "delay_mean",
        "Unified comparison: delay priority vs fairness",
        "Fairness score",
        "Mean delay-priority score",
        plots_dir / "unified_delay_vs_fairness.png",
    )

    scatter_with_ids(
        subset,
        "complexity_mean",
        "delay_mean",
        "Unified comparison: delay priority vs complexity",
        "Mean selected complexity",
        "Mean delay-priority score",
        plots_dir / "unified_delay_vs_complexity.png",
    )

    scatter_with_ids(
        subset,
        "complexity_mean",
        "fairness_score",
        "Unified comparison: fairness vs complexity",
        "Mean selected complexity",
        "Fairness score",
        plots_dir / "unified_fairness_vs_complexity.png",
    )

    bar_by_policy(
        subset,
        "delay_mean",
        "Delay-priority score across representative policies",
        "Mean delay-priority score",
        plots_dir / "unified_delay_score_bar.png",
    )

    bar_by_policy(
        subset,
        "fairness_score",
        "Fairness score across representative policies",
        "Fairness score",
        plots_dir / "unified_fairness_score_bar.png",
    )

    bar_by_policy(
        subset,
        "complexity_mean",
        "Selected complexity across representative policies",
        "Mean selected complexity",
        plots_dir / "unified_complexity_bar.png",
    )

    case_mix_plot(
        subset,
        plots_dir / "unified_case_type_mix.png",
    )

    parallel_plot(
        subset,
        plots_dir / "unified_parallel_profile.png",
    )

    write_interpretation(df, subset, out_dir)

    print("\nSaved final comparison to:", out_dir)
    print("Main table:", out_dir / "final_policy_comparison_report_subset.csv")
    print("All schedules table:", out_dir / "final_policy_comparison_all.csv")
    print("Point label map:", out_dir / "plot_point_label_map.csv")
    print("Plots:", plots_dir)

    print("\nReport subset:")
    show_cols = [
        "point_id",
        "family_label",
        "policy",
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "is_pareto",
    ]
    print(subset[show_cols].to_string(index=False))


if __name__ == "__main__":
    main()
