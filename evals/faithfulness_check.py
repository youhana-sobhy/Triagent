"""Stage 2 manual faithfulness check: does each recommendation match the runbook it cites?

Usage:
    python -m evals.faithfulness_check [how_many]     (default 5)

Reads   results/stage2.csv   (written by `python -m evals.stage2_rag`)
Writes  results/stage2_faithfulness.csv

Faithful = every step in the recommended action is in the cited runbook,
and nothing important from the runbook is contradicted.
"""

import csv
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
RUNBOOKS_DIR = REPO_ROOT / "data" / "runbooks"


def ask_yes_no() -> bool:
    while True:
        answer = input("Faithful to the runbook? (y/n): ").strip().lower()
        if answer in {"y", "n"}:
            return answer == "y"
        print("  Please type y or n.")


def main() -> None:
    how_many = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    source = RESULTS_DIR / "stage2.csv"
    if not source.exists():
        sys.exit(f"{source} not found. Run `python -m evals.stage2_rag` first.")

    with source.open(encoding="utf-8") as f:
        # Only answers that cite a real runbook can be checked against one.
        rows = [r for r in csv.DictReader(f) if (RUNBOOKS_DIR / f"{r['cited']}.md").exists()]

    sample = random.Random(42).sample(rows, min(how_many, len(rows)))
    if len(sample) < how_many:
        print(f"WARNING: only {len(sample)} answer(s) cite a runbook; run stage2 on all 20 alerts first.\n")

    checks = []
    for i, row in enumerate(sample, start=1):
        runbook_text = (RUNBOOKS_DIR / f"{row['cited']}.md").read_text(encoding="utf-8")
        print(f"=== {i}/{len(sample)}  [{row['id']}] ===")
        print(f"Alert:  {row['alert']}")
        print(f"Action: {row['recommended_action']}")
        print(f"\nCited runbook ({row['cited']}):\n{runbook_text}")
        faithful = ask_yes_no()
        note = input("Note (optional, e.g. which step was invented): ").strip()
        print()
        checks.append({"id": row["id"], "cited": row["cited"], "faithful": faithful, "note": note,
                       "alert": row["alert"], "recommended_action": row["recommended_action"]})

    n = len(checks)
    print(f"{'id':<5} {'cited':<22} faithful  note")
    for c in checks:
        print(f"{c['id']:<5} {c['cited']:<22} {'yes' if c['faithful'] else 'NO ':<9} {c['note']}")
    print(f"\nFaithful: {sum(c['faithful'] for c in checks)}/{n}")

    out = RESULTS_DIR / "stage2_faithfulness.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(checks[0].keys()))
        writer.writeheader()
        writer.writerows(checks)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
