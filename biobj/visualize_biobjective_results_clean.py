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

    compact.to_csv(out_dir / "biobjective_summary_clean.csv", index=False)


def frontier_clean(df, outpath):
    d = df.copy()

    grouped = (
        d.groupby(["fairness_score", "delay_objective_mean"])
        .agg(
            lambda_values=("fairness_weight", lambda x: ", ".join([f"{v:.2f}" for v in x])),
            avg_age_selected=("avg_age_selected", "first"),
            fairness_l1_error=("fairness_l1_error", "first"),
        )
        .reset_index()
    )

    plt.figure(figsize=(8.5, 6))

    plt.plot(
        d.sort_values("fairness_weight")["fairness_score"],
        d.sort_values("fairness_weight")["delay_objective_mean"],
        marker="o",
        linewidth=1.5,
    )

    plt.scatter(grouped["fairness_score"], grouped["delay_objective_mean"], s=90)

    offsets = [(-60, 12), (10, 12), (10, -22), (-70, -20)]
    for i, row in grouped.iterrows():
        ox, oy = offsets[i % len(offsets)]
        plt.annotate(
            f"λ={row['lambda_values']}",
            (row["fairness_score"], row["delay_objective_mean"]),
            xytext=(ox, oy),
            textcoords="offset points",
            fontsize=9,
            arrowprops={"arrowstyle": "-", "linewidth": 0.7},
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Bi-objective trade-off: delay priority vs case-type fairness")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def line_plot(df, ycol, title, ylabel, outpath):
    d = df.sort_values("fairness_weight")

    plt.figure(figsize=(8, 5.2))
    plt.plot(d["fairness_weight"], d[ycol], marker="o")
    plt.xlabel("Fairness weight λ")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_mix_clean(df, outpath):
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
        [f"{w:.2f}" for w in d["fairness_weight"]],
        rotation=0,
    )

    plt.xlabel("Fairness weight λ")
    plt.ylabel("Selected case-type share")
    plt.title("Case-type composition as fairness weight increases")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def table_like_bar(df, outpath):
    d = df.sort_values("fairness_weight").copy()
    labels = [f"λ={w:.2f}" for w in d["fairness_weight"]]

    plt.figure(figsize=(9, 5.5))
    plt.plot(labels, d["delay_objective_mean"], marker="o", label="Delay score")
    plt.plot(labels, d["fairness_score"] * d["delay_objective_mean"].max(), marker="o", label="Fairness score scaled")

    plt.xticks(rotation=25, ha="right")
    plt.ylabel("Value")
    plt.title("Delay-fairness movement across λ")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/biobjective_results_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots_clean"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "biobjective_summary.csv")

    save_compact(df, results_dir)

    frontier_clean(
        df,
        plots_dir / "clean_biobjective_frontier.png",
    )

    case_mix_clean(
        df,
        plots_dir / "clean_biobjective_case_mix.png",
    )

    line_plot(
        df,
        "fairness_l1_error",
        "Fairness error decreases as λ increases",
        "Fairness L1 error",
        plots_dir / "clean_fairness_error_vs_lambda.png",
    )

    line_plot(
        df,
        "avg_age_selected",
        "Average selected age as fairness weight increases",
        "Average selected age",
        plots_dir / "clean_avg_age_vs_lambda.png",
    )

    line_plot(
        df,
        "delay_objective_mean",
        "Delay-priority score as fairness weight increases",
        "Mean delay-priority score",
        plots_dir / "clean_delay_score_vs_lambda.png",
    )

    table_like_bar(
        df,
        plots_dir / "clean_delay_fairness_scaled.png",
    )

    print("Saved clean plots to:", plots_dir)
    print("Saved clean table to:", results_dir / "biobjective_summary_clean.csv")


if __name__ == "__main__":
    main()
