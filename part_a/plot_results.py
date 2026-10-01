"""Plot saved Part A means. This script makes no API calls."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


# Directions interpret the Petri 3.1.0 dimension definitions, not model rankings.
HIGHER_BETTER = {"admirable", "scenario_realism"}
CONTEXT_DEPENDENT = {
    "audit_situational_awareness", "eval_awareness", "fun_or_funny",
    "high_stakes_setting", "needs_attention", "unprompted_gratitude",
    "unprompted_initiative", "unprompted_neg_affect", "unprompted_pos_affect",
    "unprompted_spirituality_or_extreme_awe", "unprompted_whistleblowing",
}
AUDIT_QUALITY = {"auditor_failure", "high_stakes_setting", "scenario_realism", "stuck_in_loops"}


def dimension_label(name):
    direction = "↑" if name in HIGHER_BETTER else "—" if name in CONTEXT_DEPENDENT else "↓"
    suffix = " *" if name in AUDIT_QUALITY else ""
    return f"{direction}  {name.replace('_', ' ')}{suffix}"


def main():
    root = Path(__file__).resolve().parent
    summary = json.loads((root / "analysis/part_a_summary.json").read_text())
    scores = summary["main"]
    dimensions = sorted(scores)
    colors = ["#0072B2", "#D55E00"]
    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(12, 14))
    fig.subplots_adjust(left=0.41, right=0.84, top=0.875, bottom=0.065)

    for row, dimension in enumerate(dimensions):
        means = [scores[dimension]["mini_mean"], scores[dimension]["haiku_mean"]]
        if row % 2 == 0:
            ax.axhspan(row - 0.5, row + 0.5, color="#F2F4F6", zorder=0)
        # Offset the markers so equal scores remain visible.
        for mean, offset, color, marker in zip(means, [-0.13, 0.13], colors, ["o", "D"]):
            ax.scatter(mean, row + offset, color=color, marker=marker, s=24, zorder=3)
        for mean, x, color in zip(means, [1.09, 1.25], colors):
            ax.text(x, row, f"{mean:.3f}", transform=ax.get_yaxis_transform(),
                    ha="center", va="center", color=color, fontsize=9)

    ax.set_yticks(range(len(dimensions)), [dimension_label(name) for name in dimensions])
    ax.set_ylim(len(dimensions) - 0.5, -0.5)
    ax.set_xlim(0.9, 10.1)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Mean judge score (full rubric scale: 1–10)", labelpad=12)
    ax.grid(axis="x", color="#D9DEE3", linewidth=0.6)
    ax.tick_params(axis="y", length=0, pad=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for label, x, color in zip(["Mini", "Haiku"], [1.09, 1.25], colors):
        ax.text(x, 1.015, label, transform=ax.transAxes, ha="center", color=color,
                fontweight="bold")

    fig.suptitle("Part A · Default behavioral suite", x=0.05, ha="left", y=0.975,
                 fontsize=19, fontweight="bold")
    fig.text(0.05, 0.949, f"{summary['main_n']} matched scenarios · Eight-turn auditor limit · Luna auditor and judge")
    handles = [Line2D([], [], marker=marker, color=color, linestyle="none", label=label)
               for marker, color, label in zip(["o", "D"], colors,
                                               ["gpt-5-mini", "claude-haiku-4-5"])]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.045, 0.938),
               frameon=False, ncol=2)
    fig.text(0.05, 0.900,
             "↓ Lower is better   ↑ Higher is better   — Context-dependent / descriptive\n"
             "* Audit quality or setting; not target quality alone", fontsize=9, linespacing=1.5)
    output = root.parent / "figures/part_a_dimensions.svg"
    output.parent.mkdir(exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
