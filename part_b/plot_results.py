# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.11.2"]
# ///
"""Plot saved Part B disclosure rates. This script makes no API calls."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


def main():
    root = Path(__file__).resolve().parent
    summary = json.loads((root / "analysis/evaluation_summary.json").read_text())
    conditions = ["ordinary", "direct", "gradual"]
    counts = [len(summary["conditions"][name]["matched_ids"]) for name in conditions]
    plt.rcParams.update({"font.size": 11, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(8, 4.8), layout="constrained")

    for target, label, color, offset in [
        ("mini", "gpt-5-mini", "#0072B2", -0.18),
        ("haiku", "claude-haiku-4-5", "#D55E00", 0.18),
    ]:
        disclosures = [summary["conditions"][name]["targets"][target]["disclosures"]
                       for name in conditions]
        rates = [value / count for value, count in zip(disclosures, counts)]
        bars = ax.bar([i + offset for i in range(3)], rates, width=0.34,
                      color=color, label=label, zorder=3)
        ax.bar_label(bars, labels=[f"{value}/{count}" for value, count in zip(disclosures, counts)],
                     padding=5, fontsize=10)

    ax.set_title("Answer disclosure by student condition", pad=44, fontweight="bold")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False)
    ax.set_xticks(range(3), [name.capitalize() for name in conditions])
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_ylabel("Conversations with answer disclosure")
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.7, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    output = root.parent / "figures/part_b_disclosure.svg"
    output.parent.mkdir(exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
