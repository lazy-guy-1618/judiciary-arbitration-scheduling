import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


LABELS = {
    "age_dominant": "Age-dominant",
    "gap_dominant": "Gap-dominant",
    "history_dominant": "History-dominant",
    "balanced": "Balanced",
    "complexity_penalty": "Complexity penalty",
}


def label_profiles(df):
    df = df.copy()
    df["profile_label"] = df["profile"].map(LABELS).fillna(df["profile"])
    return df


def save_compact(df, out_dir):
    cols = [
        "profile",
        "alpha_age",
        "beta_gap",
        "gamma_hearings",
        "delta_orders",
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
    cols = [c for c in cols if c in df.columns]
    compact = df[cols].copy()

    for c in compact.select_dtypes(include="number").columns:
        compact[c] = compact[c].round(2)

    compact.to_csv(out_dir / "weight_sensitivity_summary_clean.csv", index=False)


def horizontal_bar(df, metric, title, xlabel, outpath):
    d = df.sort_values(metric, ascending=True)

    plt.figure(figsize=(9, 5.5))
    plt.barh(d["profile_label"], d[metric])
    plt.xlabel(xlabel)
    plt.title(title)

    for i, v in enumerate(d[metric]):
        plt.text(v, i, f" {v:.1f}", va="center", fontsize=9)

    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def tradeoff_plot(df, outpath):
    plt.figure(figsize=(9, 6))

    plt.scatter(df["avg_age_selected"], df["avg_gap_selected"], s=80)

    offsets = [
        (-45, 12),
        (12, 14),
        (-50, -18),
        (14, -18),
        (18, 4),
    ]

    for i, (_, row) in enumerate(df.iterrows()):
        ox, oy = offsets[i % len(offsets)]
        plt.annotate(
            row["profile_label"],
            (row["avg_age_selected"], row["avg_gap_selected"]),
            xytext=(ox, oy),
            textcoords="offset points",
            fontsize=9,
            arrowprops={"arrowstyle": "-", "linewidth": 0.7},
        )

    plt.xlabel("Average age of selected cases")
    plt.ylabel("Average inactivity gap of selected cases")
    plt.title("Coefficient sensitivity: age vs inactivity-gap trade-off")
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def case_type_share(df, outpath):
    d = df.copy()

    d["total"] = d[["FMAT_selected", "AOCOM_selected", "ADCOM_selected"]].sum(axis=1)
    d["FMAT_share_plot"] = d["FMAT_selected"] / d["total"]
    d["AOCOM_share_plot"] = d["AOCOM_selected"] / d["total"]
    d["ADCOM_share_plot"] = d["ADCOM_selected"] / d["total"]

    x = range(len(d))
    bottom = [0] * len(d)

    plt.figure(figsize=(10, 5.5))

    for col, label in [
        ("FMAT_share_plot", "FMAT"),
        ("AOCOM_share_plot", "AOCOM"),
        ("ADCOM_share_plot", "ADCOM"),
    ]:
        vals = d[col].tolist()
        plt.bar(x, vals, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, vals)]

    plt.xticks(list(x), d["profile_label"], rotation=25, ha="right")
    plt.ylabel("Share of selected cases")
    plt.title("Selected case-type share under coefficient profiles")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/weight_sensitivity_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots_dir = results_dir / "plots_clean"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "weight_sensitivity_summary.csv")
    df = label_profiles(df)

    save_compact(df, results_dir)

    horizontal_bar(
        df,
        "avg_age_selected",
        "Coefficient sensitivity: average selected age",
        "Average selected age",
        plots_dir / "clean_avg_age_selected.png",
    )

    horizontal_bar(
        df,
        "avg_gap_selected",
        "Coefficient sensitivity: average selected inactivity gap",
        "Average selected gap",
        plots_dir / "clean_avg_gap_selected.png",
    )

    horizontal_bar(
        df,
        "avg_age_left",
        "Backlog age after one scheduling decision",
        "Average age left in backlog",
        plots_dir / "clean_avg_age_left.png",
    )

    tradeoff_plot(df, plots_dir / "clean_tradeoff_age_vs_gap.png")
    case_type_share(df, plots_dir / "clean_case_type_share.png")

    print("Saved cleaned plots to:", plots_dir)
    print("Saved cleaned table to:", results_dir / "weight_sensitivity_summary_clean.csv")


if __name__ == "__main__":
    main()
