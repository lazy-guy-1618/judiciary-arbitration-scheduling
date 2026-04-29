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


def compact_duplicate_labels(df):
    grouped = (
        df.groupby(["delay_mean", "fairness_score", "complexity_mean"], dropna=False)
        .agg(
            profiles=("profile_label", lambda x: " / ".join(x)),
            w_delay=("w_delay", "first"),
            w_fairness=("w_fairness", "first"),
            w_complexity=("w_complexity", "first"),
            avg_age_selected=("avg_age_selected", "first"),
            old_cases_selected=("old_cases_selected", "first"),
            FMAT_selected=("FMAT_selected", "first"),
            AOCOM_selected=("AOCOM_selected", "first"),
            ADCOM_selected=("ADCOM_selected", "first"),
            is_pareto=("is_pareto", "max"),
        )
        .reset_index()
    )
    return grouped


def save_clean_table(df, out_dir):
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

    clean = df[cols].copy()
    for c in clean.select_dtypes(include="number").columns:
        clean[c] = clean[c].round(3)

    clean.to_csv(out_dir / "multiobjective_summary_clean.csv", index=False)


def scatter_delay_fairness(df, outpath):
    d = compact_duplicate_labels(df)

    plt.figure(figsize=(9, 6))

    plt.scatter(
        d["fairness_score"],
        d["delay_mean"],
        s=90,
    )

    offsets = [(-80, 14), (12, 14), (12, -22), (-90, -22), (16, 0)]

    for i, row in d.iterrows():
        ox, oy = offsets[i % len(offsets)]
        plt.annotate(
            row["profiles"],
            (row["fairness_score"], row["delay_mean"]),
            xytext=(ox, oy),
            textcoords="offset points",
            fontsize=8,
            arrowprops={"arrowstyle": "-", "linewidth": 0.7},
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective trade-off: delay priority vs fairness")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def scatter_delay_complexity(df, outpath):
    d = compact_duplicate_labels(df)

    plt.figure(figsize=(9, 6))

    plt.scatter(
        d["complexity_mean"],
        d["delay_mean"],
        s=90,
    )

    offsets = [(-80, 14), (12, 14), (12, -22), (-90, -22), (16, 0)]

    for i, row in d.iterrows():
        ox, oy = offsets[i % len(offsets)]
        plt.annotate(
            row["profiles"],
            (row["complexity_mean"], row["delay_mean"]),
            xytext=(ox, oy),
            textcoords="offset points",
            fontsize=8,
            arrowprops={"arrowstyle": "-", "linewidth": 0.7},
        )

    plt.xlabel("Mean selected complexity")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective trade-off: delay priority vs complexity")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def horizontal_metric_bar(df, metric, title, xlabel, outpath):
    d = df.sort_values(metric, ascending=True).copy()

    plt.figure(figsize=(9.5, 5.8))
    plt.barh(d["profile_label"], d[metric])
    plt.xlabel(xlabel)
    plt.title(title)

    for i, v in enumerate(d[metric]):
        plt.text(v, i, f" {v:.2f}", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_mix_share(df, outpath):
    d = df.copy()

    d["total"] = d[["FMAT_selected", "AOCOM_selected", "ADCOM_selected"]].sum(axis=1)
    d["FMAT_plot"] = d["FMAT_selected"] / d["total"]
    d["AOCOM_plot"] = d["AOCOM_selected"] / d["total"]
    d["ADCOM_plot"] = d["ADCOM_selected"] / d["total"]

    x = range(len(d))
    bottom = [0] * len(d)

    plt.figure(figsize=(11, 5.8))

    for col, label in [
        ("FMAT_plot", "FMAT"),
        ("AOCOM_plot", "AOCOM"),
        ("ADCOM_plot", "ADCOM"),
    ]:
        vals = d[col].fillna(0).tolist()
        plt.bar(x, vals, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, vals)]

    plt.xticks(list(x), d["profile_label"], rotation=25, ha="right")
    plt.ylabel("Selected case-type share")
    plt.title("Case-type composition under multi-objective profiles")
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
        "old_cases_left",
    ]

    d = df[["profile_label"] + metrics].copy()

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
            linewidth=1.6,
            label=row["profile_label"],
        )

    plt.xticks(x, metrics, rotation=20, ha="right")
    plt.ylabel("Normalised value")
    plt.title("Normalised comparison of multi-objective profiles")
    plt.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/multiobjective_results_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots_clean"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "multiobjective_summary.csv")
    df = add_labels(df)

    save_clean_table(df, results_dir)

    scatter_delay_fairness(
        df,
        plots_dir / "clean_multiobj_delay_vs_fairness.png",
    )

    scatter_delay_complexity(
        df,
        plots_dir / "clean_multiobj_delay_vs_complexity.png",
    )

    horizontal_metric_bar(
        df,
        "delay_mean",
        "Mean delay-priority score by profile",
        "Mean delay-priority score",
        plots_dir / "clean_delay_score_by_profile.png",
    )

    horizontal_metric_bar(
        df,
        "complexity_mean",
        "Mean selected complexity by profile",
        "Mean selected complexity",
        plots_dir / "clean_complexity_by_profile.png",
    )

    horizontal_metric_bar(
        df,
        "fairness_score",
        "Fairness score by profile",
        "Fairness score",
        plots_dir / "clean_fairness_score_by_profile.png",
    )

    case_mix_share(
        df,
        plots_dir / "clean_multiobj_case_mix_share.png",
    )

    parallel_plot(
        df,
        plots_dir / "clean_multiobj_parallel_profile.png",
    )

    print("Saved clean plots to:", plots_dir)
    print("Saved clean table to:", results_dir / "multiobjective_summary_clean.csv")


if __name__ == "__main__":
    main()
