import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def plot_bar(summary, xcol, ycol, title, ylabel, outpath):
    df = summary.sort_values(ycol, ascending=False).copy()

    plt.figure(figsize=(10, 6))
    plt.bar(df[xcol], df[ycol])
    plt.xticks(rotation=30, ha="right")
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def plot_grouped_case_mix(summary, outpath):
    df = summary.copy()
    df = df[["policy", "FMAT_selected", "AOCOM_selected", "ADCOM_selected"]]

    x = range(len(df))
    width = 0.25

    plt.figure(figsize=(10, 6))
    plt.bar([i - width for i in x], df["FMAT_selected"], width=width, label="FMAT")
    plt.bar(x, df["AOCOM_selected"], width=width, label="AOCOM")
    plt.bar([i + width for i in x], df["ADCOM_selected"], width=width, label="ADCOM")
    plt.xticks(list(x), df["policy"], rotation=30, ha="right")
    plt.ylabel("Selected cases")
    plt.title("Case-type mix selected on Day 1")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def plot_line(metrics, ycol, title, ylabel, outpath):
    plt.figure(figsize=(10, 6))

    for policy, sub in metrics.groupby("policy"):
        sub = sub.sort_values("sim_day")
        plt.plot(sub["sim_day"], sub[ycol], marker="o", label=policy)

    plt.xlabel("Simulation day")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def make_report_tables(summary, out_dir):
    cols = [
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
    cols = [c for c in cols if c in summary.columns]

    compact = summary[cols].copy()
    numeric_cols = compact.select_dtypes(include=["number"]).columns
    compact[numeric_cols] = compact[numeric_cols].round(2)

    compact.to_csv(out_dir / "policy_day1_summary_compact.csv", index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-dir",
        default="output/scheduling_results",
        help="Directory containing policy_day1_summary.csv and multi_day_metrics.csv",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    summary = pd.read_csv(results_dir / "policy_day1_summary.csv")
    metrics = pd.read_csv(results_dir / "multi_day_metrics.csv")

    # Save a compact table
    make_report_tables(summary, results_dir)

    # Day-1 bar charts
    plot_bar(
        summary,
        "policy",
        "avg_age_selected",
        "Average age of selected cases (Day 1)",
        "Average age (days)",
        plots_dir / "day1_avg_age_selected.png",
    )

    plot_bar(
        summary,
        "policy",
        "avg_gap_selected",
        "Average inactivity gap of selected cases (Day 1)",
        "Average gap (days)",
        plots_dir / "day1_avg_gap_selected.png",
    )

    plot_bar(
        summary,
        "policy",
        "old_cases_selected",
        "Old cases selected (Day 1)",
        "Number of old cases selected",
        plots_dir / "day1_old_cases_selected.png",
    )

    plot_bar(
        summary,
        "policy",
        "avg_age_left",
        "Average age left in backlog after Day 1",
        "Average age left (days)",
        plots_dir / "day1_avg_age_left.png",
    )

    plot_bar(
        summary,
        "policy",
        "old_cases_left",
        "Old cases left in backlog after Day 1",
        "Number of old cases left",
        plots_dir / "day1_old_cases_left.png",
    )

    # Case mix
    plot_grouped_case_mix(summary, plots_dir / "day1_case_type_mix.png")

    # Multi-day trend plots
    plot_line(
        metrics,
        "avg_age_left",
        "Average backlog age across simulation days",
        "Average age left (days)",
        plots_dir / "multiday_avg_age_left.png",
    )

    plot_line(
        metrics,
        "old_cases_left",
        "Old cases left across simulation days",
        "Old cases left",
        plots_dir / "multiday_old_cases_left.png",
    )

    plot_line(
        metrics,
        "avg_age_selected",
        "Average age of selected cases across simulation days",
        "Average age selected (days)",
        plots_dir / "multiday_avg_age_selected.png",
    )

    plot_line(
        metrics,
        "avg_gap_selected",
        "Average inactivity gap of selected cases across simulation days",
        "Average gap selected (days)",
        plots_dir / "multiday_avg_gap_selected.png",
    )

    print("Saved plots to:", plots_dir)
    print("Saved compact table to:", results_dir / "policy_day1_summary_compact.csv")


if __name__ == "__main__":
    main()
