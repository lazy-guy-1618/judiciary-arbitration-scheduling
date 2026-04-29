import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def save_compact(df, out_dir):
    cols = [
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

    cols = [c for c in cols if c in df.columns]

    compact = df[cols].copy()

    for c in compact.select_dtypes(include="number").columns:
        compact[c] = compact[c].round(3)

    compact.to_csv(out_dir / "biobjective_summary_compact.csv", index=False)


def frontier_plot(df, outpath):
    d = df.sort_values("fairness_weight")

    plt.figure(figsize=(8, 6))

    plt.plot(
        d["fairness_score"],
        d["delay_objective_mean"],
        marker="o",
    )

    for _, row in d.iterrows():
        plt.annotate(
            f"λ={row['fairness_weight']:.2f}",
            (row["fairness_score"], row["delay_objective_mean"]),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9,
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Bi-objective frontier: delay priority vs fairness")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_mix_plot(df, outpath):
    d = df.sort_values("fairness_weight").copy()

    x = range(len(d))
    bottom = [0] * len(d)

    plt.figure(figsize=(10, 5.5))

    for col, label in [
        ("FMAT_share", "FMAT"),
        ("AOCOM_share", "AOCOM"),
        ("ADCOM_share", "ADCOM"),
    ]:
        vals = d[col].fillna(0).tolist()
        plt.bar(x, vals, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, vals)]

    plt.xticks(
        list(x),
        [f"λ={w:.2f}" for w in d["fairness_weight"]],
        rotation=25,
        ha="right",
    )

    plt.ylabel("Selected share")
    plt.title("Selected case-type mix as fairness weight increases")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def line_plot(df, ycol, title, ylabel, outpath):
    d = df.sort_values("fairness_weight")

    plt.figure(figsize=(8, 5.5))
    plt.plot(d["fairness_weight"], d[ycol], marker="o")
    plt.xlabel("Fairness weight λ")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/biobjective_results_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "biobjective_summary.csv")

    save_compact(df, results_dir)

    frontier_plot(
        df,
        plots_dir / "biobjective_frontier_delay_vs_fairness.png",
    )

    case_mix_plot(
        df,
        plots_dir / "biobjective_case_type_mix.png",
    )

    line_plot(
        df,
        "fairness_l1_error",
        "Fairness error vs fairness weight",
        "L1 share deviation",
        plots_dir / "biobjective_fairness_error.png",
    )

    line_plot(
        df,
        "avg_age_selected",
        "Average selected age vs fairness weight",
        "Average selected age",
        plots_dir / "biobjective_avg_age_selected.png",
    )

    line_plot(
        df,
        "old_cases_left",
        "Old cases left vs fairness weight",
        "Old cases left",
        plots_dir / "biobjective_old_cases_left.png",
    )

    print("Saved plots to:", plots_dir)
    print("Saved compact table to:", results_dir / "biobjective_summary_compact.csv")


if __name__ == "__main__":
    main()
