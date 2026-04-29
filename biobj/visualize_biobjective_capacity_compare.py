import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def load_result(path, label):
    df = pd.read_csv(Path(path) / "biobjective_summary.csv")
    df["capacity_label"] = label
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap10", default="output/biobjective_results_cap10")
    parser.add_argument("--cap20", default="output/biobjective_results_cap20")
    parser.add_argument("--cap30", default="output/biobjective_results_cap30")
    parser.add_argument("--out-dir", default="output/biobjective_capacity_compare")
    args = parser.parse_args()

    out = Path(args.out_dir)
    plots = out / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    df = pd.concat(
        [
            load_result(args.cap10, "capacity=10"),
            load_result(args.cap20, "capacity=20"),
            load_result(args.cap30, "capacity=30"),
        ],
        ignore_index=True,
    )

    df.to_csv(out / "biobjective_capacity_compare.csv", index=False)

    plt.figure(figsize=(8.5, 6))

    for label, sub in df.groupby("capacity_label"):
        sub = sub.sort_values("fairness_weight")
        plt.plot(
            sub["fairness_score"],
            sub["delay_objective_mean"],
            marker="o",
            label=label,
        )

    plt.xlabel("Fairness score")
    plt.ylabel("Mean delay-priority score")
    plt.title("Bi-objective frontier under different listing capacities")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "capacity_frontier_comparison.png", dpi=300)
    plt.close()

    plt.figure(figsize=(8.5, 6))

    for label, sub in df.groupby("capacity_label"):
        sub = sub.sort_values("fairness_weight")
        plt.plot(
            sub["fairness_weight"],
            sub["old_cases_left"],
            marker="o",
            label=label,
        )

    plt.xlabel("Fairness weight λ")
    plt.ylabel("Old cases left")
    plt.title("Old backlog under different capacities")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "capacity_old_cases_left.png", dpi=300)
    plt.close()

    print("Saved:", out)
    print("Plots:", plots)


if __name__ == "__main__":
    main()
