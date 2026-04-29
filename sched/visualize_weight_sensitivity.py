import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def bar(df, y, title, ylabel, outpath):
    d = df.copy()
    plt.figure(figsize=(10, 6))
    plt.bar(d["profile"], d[y])
    plt.xticks(rotation=30, ha="right")
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def grouped_case_mix(df, outpath):
    x = range(len(df))
    width = 0.25

    plt.figure(figsize=(10, 6))
    plt.bar([i - width for i in x], df["FMAT_selected"], width=width, label="FMAT")
    plt.bar(x, df["AOCOM_selected"], width=width, label="AOCOM")
    plt.bar([i + width for i in x], df["ADCOM_selected"], width=width, label="ADCOM")
    plt.xticks(list(x), df["profile"], rotation=30, ha="right")
    plt.ylabel("Selected cases")
    plt.title("Case-type mix under coefficient profiles")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def scatter_tradeoff(df, outpath):
    plt.figure(figsize=(8, 6))
    plt.scatter(df["avg_age_selected"], df["avg_gap_selected"])

    for _, row in df.iterrows():
        plt.annotate(
            row["profile"],
            (row["avg_age_selected"], row["avg_gap_selected"]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=9,
        )

    plt.xlabel("Average age selected")
    plt.ylabel("Average inactivity gap selected")
    plt.title("Coefficient profile trade-off: age vs inactivity gap")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def radar_like_parallel(df, outpath):
    metrics = [
        "avg_age_selected",
        "avg_gap_selected",
        "avg_hearings_selected",
        "avg_orders_selected",
        "old_cases_selected",
    ]

    norm = df[["profile"] + metrics].copy()

    for m in metrics:
        mn, mx = norm[m].min(), norm[m].max()
        if mx > mn:
            norm[m] = (norm[m] - mn) / (mx - mn)
        else:
            norm[m] = 0

    plt.figure(figsize=(10, 6))

    x = list(range(len(metrics)))
    for _, row in norm.iterrows():
        y = [row[m] for m in metrics]
        plt.plot(x, y, marker="o", label=row["profile"])

    plt.xticks(x, metrics, rotation=20, ha="right")
    plt.ylabel("Normalised value")
    plt.title("Normalised metric profile across coefficient settings")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/weight_sensitivity_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots = results_dir / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "weight_sensitivity_summary.csv")

    rounded = df.copy()
    num_cols = rounded.select_dtypes(include=["number"]).columns
    rounded[num_cols] = rounded[num_cols].round(2)
    rounded.to_csv(results_dir / "weight_sensitivity_summary_compact.csv", index=False)

    bar(
        df,
        "avg_age_selected",
        "Effect of coefficients on average age selected",
        "Average age selected",
        plots / "coeff_avg_age_selected.png",
    )

    bar(
        df,
        "avg_gap_selected",
        "Effect of coefficients on inactivity gap selected",
        "Average gap selected",
        plots / "coeff_avg_gap_selected.png",
    )

    bar(
        df,
        "avg_hearings_selected",
        "Effect of coefficients on repeat-hearing intensity",
        "Average hearing-history rows selected",
        plots / "coeff_avg_hearings_selected.png",
    )

    bar(
        df,
        "old_cases_selected",
        "Old-case coverage under coefficient profiles",
        "Old cases selected",
        plots / "coeff_old_cases_selected.png",
    )

    grouped_case_mix(df, plots / "coeff_case_type_mix.png")
    scatter_tradeoff(df, plots / "coeff_tradeoff_age_vs_gap.png")
    radar_like_parallel(df, plots / "coeff_parallel_metric_profile.png")

    print("Saved plots to:", plots)
    print("Saved compact table to:", results_dir / "weight_sensitivity_summary_compact.csv")


if __name__ == "__main__":
    main()
