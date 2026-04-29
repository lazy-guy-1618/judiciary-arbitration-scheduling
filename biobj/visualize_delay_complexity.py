import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="output/biobjective_delay_complexity_cap20")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    plots = results_dir / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_dir / "delay_complexity_summary.csv")
    df = df.sort_values("complexity_weight")

    compact = df.copy()
    for c in compact.select_dtypes(include="number").columns:
        compact[c] = compact[c].round(3)
    compact.to_csv(results_dir / "delay_complexity_summary_compact.csv", index=False)

    plt.figure(figsize=(8.5, 6))
    plt.plot(df["complexity_mean"], df["delay_mean"], marker="o")

    for _, row in df.iterrows():
        plt.annotate(
            f"λ={row['complexity_weight']:.2f}",
            (row["complexity_mean"], row["delay_mean"]),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9,
        )

    plt.xlabel("Mean selected complexity")
    plt.ylabel("Mean delay-priority score")
    plt.title("Bi-objective trade-off: delay priority vs case complexity")
    plt.tight_layout()
    plt.savefig(plots / "delay_vs_complexity_frontier.png", dpi=300)
    plt.close()

    plt.figure(figsize=(8.5, 5.5))
    plt.plot(df["complexity_weight"], df["avg_age_selected"], marker="o", label="Average age")
    plt.plot(df["complexity_weight"], df["avg_hearings_selected"], marker="o", label="Average hearings")
    plt.xlabel("Complexity penalty weight λ")
    plt.title("Effect of complexity penalty on selected cases")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "complexity_weight_effect.png", dpi=300)
    plt.close()

    print("Saved plots to:", plots)


if __name__ == "__main__":
    main()
