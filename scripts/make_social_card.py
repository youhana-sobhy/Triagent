"""Render docs/assets/triagent-series.png: the LinkedIn / README image for this part of the series.

Headline numbers are read from results/, so the image always matches the saved evals.

Usage:
    pip install matplotlib
    python scripts/make_social_card.py
"""

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "assets" / "triagent-series.png"

BG, PANEL, EDGE = "#0A0F1F", "#131A30", "#2A3555"
INK, MUTED, DIM = "#F5F7FC", "#A3ADC8", "#5D6888"
VIOLET, CYAN, GREEN, AMBER, RED = "#8B7CFF", "#39D0FF", "#3DDC97", "#FFC857", "#FF6B81"

# What I studied, in order, and where each topic shows up in the project.
ROADMAP = [
    ("Prompting & APIs", "versioned prompts"),
    ("Structured outputs", "JSON schemas"),
    ("Tool use", "server checks"),
    ("RAG", "runbook search"),
    ("AI agents", "agent loop"),
    ("Guardrails", "injection filter"),
    ("Human-in-the-loop", "approval gate"),
    ("Evals", "4 layers"),
    ("Cost & latency", "per-call logging"),
]


def load_json(name):
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def load_csv(name):
    with (RESULTS / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pill(ax, x, y, w, h, text, fg, bg, size=12, weight="bold"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={h / 2}",
                                facecolor=bg, edgecolor=fg, linewidth=1.4))
    ax.text(x + w / 2, y + h / 2, text, color=fg, fontsize=size, fontweight=weight, ha="center", va="center")


def main():
    s1, held = load_json("stage1_v2"), load_json("stage1_v2_held_out")
    guard = load_csv("stage4_input_guard")
    attacks = [r for r in guard if r["label"] == "attack"]
    blocked = sum(r["layered_block"] == "True" for r in attacks)

    fig = plt.figure(figsize=(10.8, 13.5), dpi=125, facecolor=BG)   # 1350 x 1688 px, 4:5 portrait
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100), ax.set_ylim(0, 125), ax.axis("off")

    # Soft glow accents
    for (cx, cy, r, c, a) in [(92, 118, 26, VIOLET, 0.10), (4, 50, 22, CYAN, 0.07)]:
        ax.add_patch(Circle((cx, cy), r, facecolor=c, alpha=a, edgecolor="none"))

    # Series badge
    pill(ax, 6, 114, 52, 5, "LEARNING AI ENGINEERING IN PUBLIC", CYAN, BG, size=12.5)
    pill(ax, 60, 114, 18, 5, "THE SERIES", VIOLET, BG, size=12.5)

    # Hook
    ax.text(6, 104, "I stopped watching tutorials.", color=MUTED, fontsize=27, fontweight="bold", va="center")
    ax.text(6, 96, "I built an AI agent.", color=INK, fontsize=40, fontweight="bold", va="center")
    ax.text(6, 88, "Then I tried to break it.", color=VIOLET, fontsize=40, fontweight="bold", va="center")

    # Roadmap: what I studied, mapped to the project
    ax.text(6, 79, "WHAT I STUDIED  →  WHERE IT LIVES IN THE PROJECT", color=DIM, fontsize=12,
            fontweight="bold", va="center")
    top, row_h, col_w = 74.5, 7.6, 28.7
    for i, (topic, used) in enumerate(ROADMAP):
        col, row = i % 3, i // 3
        x, y = 6 + col * (col_w + 0.95), top - row * row_h
        ax.add_patch(FancyBboxPatch((x, y - 5.6), col_w, 6.2, boxstyle="round,pad=0,rounding_size=1.2",
                                    facecolor=PANEL, edgecolor=EDGE, linewidth=1.1))
        ax.add_patch(Circle((x + 3, y - 2.5), 1.5, facecolor=GREEN, edgecolor="none"))
        ax.text(x + 3, y - 2.55, "✓", color=BG, fontsize=11, fontweight="bold", ha="center", va="center")
        ax.text(x + 5.6, y - 1.2, topic, color=INK, fontsize=13, fontweight="bold", va="center")
        ax.text(x + 5.6, y - 3.9, used, color=MUTED, fontsize=11, va="center")

    # The project
    py = 49.5
    ax.add_patch(FancyBboxPatch((6, py - 9.5), 88, 11.5, boxstyle="round,pad=0,rounding_size=2",
                                facecolor="#1A1440", edgecolor=VIOLET, linewidth=2))
    ax.text(10, py - 1.2, "THE PROJECT", color=VIOLET, fontsize=12, fontweight="bold", va="center")
    ax.text(10, py - 5.6, "Triagent", color=INK, fontsize=30, fontweight="bold", va="center")
    ax.text(40, py - 3.0, "An AI on-call assistant that reads server alerts,", color=INK, fontsize=13.5, va="center")
    ax.text(40, py - 6.6, "searches runbooks, checks servers and suggests a fix.", color=INK, fontsize=13.5,
            va="center")

    # Punchlines
    ax.text(6, 33.5, "WHAT THE TESTS SHOWED", color=DIM, fontsize=12, fontweight="bold", va="center")
    stats = [
        (f"{s1['severity_correct'] / s1['n']:.0%} → {held['severity_correct'] / held['n']:.0%}",
         "my own tests vs.\nalerts it never saw", AMBER),
        (f"{blocked}/{len(attacks)}", "prompt-injection\nattacks blocked", GREEN),
        ("0", "servers restarted\nwithout a human", CYAN),
    ]
    for i, (value, label, color) in enumerate(stats):
        x = 6 + i * 29.65
        ax.add_patch(FancyBboxPatch((x, 10.5), 28.7, 19.5, boxstyle="round,pad=0,rounding_size=1.8",
                                    facecolor=PANEL, edgecolor=color, linewidth=1.6))
        ax.text(x + 14.35, 23.2, value, color=color, fontsize=24 if "→" in value else 32,
                fontweight="bold", ha="center", va="center")
        ax.text(x + 14.35, 15.0, label, color=MUTED, fontsize=12.5, ha="center", va="center", linespacing=1.4)

    ax.text(6, 4.5, "Code, data and every result (failures too) are open on GitHub.", color=MUTED,
            fontsize=12.5, va="center")
    ax.text(94, 4.5, "Follow the series  →", color=CYAN, fontsize=12.5, fontweight="bold", ha="right", va="center")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, facecolor=BG)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
