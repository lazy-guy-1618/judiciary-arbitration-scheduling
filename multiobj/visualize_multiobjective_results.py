import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


LABELS = {
    "delay_only": "Delay only",
    "fairness_only": "Fairness only",
    "complexity_only": "Complexity only",
    "delay_fairness": "Delay + fairness",
    "delay_complexity": "Delay + complexity",
    "fair_balanced": "Fair-balanced",
    "balanced_all": "Balanced all",
}


def add_labels(df):
    df = df.copy()
    df["profile_label"] = df["profile"].map(LABELS).fillna(df["profile"])
    return df


def save_compact(df, out_dir):
    cols = [
        "profile",
        "w_delay",
        "w_fairness",
        "w_complexity",
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "avg_age_selected",
        "avg_gap_selected",
        "old_cases_selected",
        "FMAT_selected",
        "AOCOM_selected",
        "ADCOM_selected",
        "old_cases_left",
        "is_pareto",
    ]

    cols = [c for c in cols if c in df.columns]
    compact = df[cols].copy()

    for c in compact.select_dtypes(include="number").columns:
        compact[c] = compact[c].round(3)

    compact.to_csv(out_dir / "multiobjective_summary_compact.csv", index=False)


def scatter_delay_fairness(df, outpath):
    plt.figure(figsize=(8.5, 6))

    for _, row in df.iterrows():
        marker = "o" if row["is_pareto"] else "x"
        size = 90 if row["is_pareto"] else 60

        plt.scatter(
            row["fairness_score"],
            row["delay_mean"],
            s=size,
            marker=marker,
        )

        plt.annotate(
            row["profile_label"],
            (row["fairness_score"], row["delay_mean"]),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9,
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective schedules: delay vs fairness")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def scatter_delay_complexity(df, outpath):
    plt.figure(figsize=(8.5, 6))

    for _, row in df.iterrows():
        marker = "o" if row["is_pareto"] else "x"
        size = 90 if row["is_pareto"] else 60

        plt.scatter(
            row["complexity_mean"],
            row["delay_mean"],
            s=size,
            marker=marker,
        )

        plt.annotate(
            row["profile_label"],
            (row["complexity_mean"], row["delay_mean"]),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9,
        )

    plt.xlabel("Mean selected complexity")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective schedules: delay vs complexity")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_mix(df, outpath):
    d = df.copy()
    x = range(len(d))
    bottom = [0] * len(d)

    plt.figure(figsize=(11, 5.5))

    for col, label in [
        ("FMAT_share", "FMAT"),
        ("AOCOM_share", "AOCOM"),
        ("ADCOM_share", "ADCOM"),
    ]:
        vals = d[col].fillna(0).tolist()
        plt.bar(x, vals, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, vals)]

    plt.xticks(list(x), d["profile_label"], rotation=25, ha="right")
    plt.ylabel("Selected share")
    plt.title("Case-type composition under multi-objective profiles")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def parallel_normalised(df, outpath):
    metrics = [
        "delay_mean",
        "fairness_score",
        "complexity_mean",
        "avg_age_selected",
        "old_cases_left",
    ]

    d = df[["profile_label", "is_pareto"] + metrics].copy()

    for m in metrics:
        mn = d[m].min()
        mx = d[m].max()
        if mx > mn:
            d[m] = (d[m] - mn) / (mx - mn)
        else:
            d[m] = 0

    plt.figure(figsize=(10.5, 6))

    x = list(range(len(metrics)))

    for _, row in d.iterrows():
        linestyle = "-" if row["is_pareto"] else "--"
        linewidth = 2.0 if row["is_pareto"] else 1.2

        plt.plot(
            x,
            [row[m] for m in metrics],
            marker="o",
            linestyle=linestyle,
            linewidth=linewidth,
            label=row["profile_label"],
        )

    plt.xticks(x, metrics, rotation=20, ha="right")
    plt.ylabel("Normalised value")
    plt.title("Normalised multi-objective profile comparison")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/multiobjective_results_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "multiobjective_summary.csv")
    df = add_labels(df)

    save_compact(df, results_dir)

    scatter_delay_fairness(
        df,
        plots_dir / "multiobj_delay_vs_fairness.png",
    )

    scatter_delay_complexity(
        df,
        plots_dir / "multiobj_delay_vs_complexity.png",
    )

    case_mix(
        df,
        plots_dir / "multiobj_case_type_mix.png",
    )

    parallel_normalised(
        df,
        plots_dir / "multiobj_parallel_profile.png",
    )

    print("Saved plots to:", plots_dir)
    print("Saved compact table to:", results_dir / "multiobjective_summary_compact.csv")


if __name__ == "__main__":
    main()
