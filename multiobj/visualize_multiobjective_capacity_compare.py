import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def load(path, label):
    df = pd.read_csv(Path(path) / "multiobjective_summary.csv")
    df["capacity_label"] = label
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap10", default="output/multiobjective_results_cap10")
    parser.add_argument("--cap20", default="output/multiobjective_results_cap20")
    parser.add_argument("--cap30", default="output/multiobjective_results_cap30")
    parser.add_argument("--out-dir", default="output/multiobjective_capacity_compare")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    plots_dir = out_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    df = pd.concat(
        [
            load(args.cap10, "capacity=10"),
            load(args.cap20, "capacity=20"),
            load(args.cap30, "capacity=30"),
        ],
        ignore_index=True,
    )

    df.to_csv(out_dir / "multiobjective_capacity_compare.csv", index=False)

    plt.figure(figsize=(9, 6))

    for label, sub in df.groupby("capacity_label"):
        sub = sub.sort_values("delay_mean")
        plt.scatter(
            sub["fairness_score"],
            sub["delay_mean"],
            label=label,
            s=80,
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective delay-fairness space under different capacities")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "capacity_delay_fairness_space.png", dpi=300)
    plt.close()

    plt.figure(figsize=(9, 6))

    for label, sub in df.groupby("capacity_label"):
        sub = sub.sort_values("complexity_mean")
        plt.scatter(
            sub["complexity_mean"],
            sub["delay_mean"],
            label=label,
            s=80,
        )

    plt.xlabel("Mean selected complexity")
    plt.ylabel("Mean delay-priority score")
    plt.title("Multi-objective delay-complexity space under different capacities")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "capacity_delay_complexity_space.png", dpi=300)
    plt.close()

    print("Saved comparison to:", out_dir)
    print("Plots:", plots_dir)


if __name__ == "__main__":
    main()
