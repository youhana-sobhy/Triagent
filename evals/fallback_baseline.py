"""How good is degraded mode? Scores the rule-based fallback on the same datasets (free, no API).

Usage:
    python -m evals.fallback_baseline
"""

from evals.common import load_jsonl, pct, save_summary, table
from evals.grading import severity_match
from triagent.fallback import rule_based_severity


def main() -> None:
    summary = {}
    for dataset in ("alerts.jsonl", "held_out.jsonl"):
        rows = []
        for case in load_jsonl(dataset):
            got, reason = rule_based_severity(case["alert"])
            rows.append([case["id"], case["expected"], got, "PASS" if severity_match(got, case["expected"]) else "FAIL",
                         reason])
        correct = sum(r[3] == "PASS" for r in rows)
        print(f"\n== {dataset} ==")
        print(table(rows, ["id", "expected", "fallback", "result", "rule"]))
        print(f"Fallback severity accuracy: {pct(correct, len(rows))}")
        summary[dataset.removesuffix(".jsonl")] = {"n": len(rows), "correct": correct,
                                                    "failures": [r[0] for r in rows if r[3] == "FAIL"]}
    save_summary(summary, "fallback_baseline")


if __name__ == "__main__":
    main()
