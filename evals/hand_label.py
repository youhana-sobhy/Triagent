"""Stage 1 hand-label check: score explanations yourself, blind, then compare with the LLM grader.

Usage:
    python -m evals.hand_label [v1|v2] [how_many]     (defaults: v2, 5)

Reads   results/stage1_<version>.csv   (written by `python -m evals.stage1_classify`)
Writes  results/stage1_<version>_hand_labels.csv
"""

import csv
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"

RUBRIC = """
Score the explanation's CLARITY from 1 to 5:
  5 = Says what is wrong, where, and why it matters, in plain words. One or two sentences, no filler.
  4 = Clear and correct, but missing one of: what, where, or why it matters.
  3 = Understandable but vague or generic.
  2 = Confusing, or mostly repeats the alert text without adding meaning.
  1 = Wrong, misleading, contradicts the alert, or unreadable.
  (Empty/garbled/vague alert: a 5 says so plainly. Don't judge whether the severity is right.)
"""


def ask_score() -> int:
    """Keep asking until the user types a number from 1 to 5."""
    while True:
        answer = input("Your score (1-5): ").strip()
        if answer in {"1", "2", "3", "4", "5"}:
            return int(answer)
        print("  Please type a whole number from 1 to 5.")


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "v2"
    how_many = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    source = RESULTS_DIR / f"stage1_{version}.csv"
    if not source.exists():
        sys.exit(f"{source} not found. Run `python -m evals.stage1_classify --prompt {version}` first.")

    with source.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["explanation"] and r["clarity"]]

    # Fixed seed: the same 5 rows are picked every time, so you can redo the check later.
    sample = random.Random(42).sample(rows, min(how_many, len(rows)))
    if len(sample) < how_many:
        print(f"WARNING: only {len(sample)} graded explanation(s) in {source.name}; "
              f"run the Stage 1 eval on all 20 alerts first for a real check.\n")

    print(RUBRIC)
    print("The LLM grader's scores are hidden until you finish.\n")

    labels = []
    for i, row in enumerate(sample, start=1):
        print(f"--- {i}/{len(sample)}  [{row['id']}] ---")
        print(f"Alert:       {row['alert'] or '(empty)'}")
        print(f"Explanation: {row['explanation']}")
        human = ask_score()
        print()
        grader = int(row["clarity"])
        labels.append({"id": row["id"], "human": human, "grader": grader, "diff": grader - human,
                       "alert": row["alert"], "explanation": row["explanation"]})

    # Agreement table
    print(f"{'id':<5} {'you':>4} {'grader':>7} {'diff':>5}")
    for r in labels:
        print(f"{r['id']:<5} {r['human']:>4} {r['grader']:>7} {r['diff']:>+5}")

    n = len(labels)
    exact = sum(r["diff"] == 0 for r in labels)
    within_one = sum(abs(r["diff"]) <= 1 for r in labels)
    bias = sum(r["diff"] for r in labels) / n
    print(f"\nExact agreement:   {exact}/{n}")
    print(f"Within 1 point:    {within_one}/{n}")
    print(f"Average bias:      {bias:+.2f}  (positive = grader is more generous than you)")

    out = RESULTS_DIR / f"stage1_{version}_hand_labels.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "human", "grader", "diff", "alert", "explanation"])
        writer.writeheader()
        writer.writerows(labels)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
