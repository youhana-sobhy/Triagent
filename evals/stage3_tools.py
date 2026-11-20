"""Stage 3: tool use.

10 alerts where the correct tool call is known in advance: which tool and which server,
or no call at all (no server named, or unreadable, so any call would be a guess).

Runs the full agent with the input guardrail off, so this measures tool use only.

Usage:
    python -m evals.stage3_tools
"""

import argparse
from collections import Counter

from evals.common import load_jsonl, parallel_map, pct, save_csv, save_summary, table
from evals.grading import tool_call_grade
from triagent import config
from triagent.agent import triage


def run_case(case: dict) -> dict:
    result = triage(case["alert"], guard_mode="off")
    grade = tool_call_grade(result.tool_calls, case["expected_tool"], case["expected_server"])
    called = [f"{c['name']}({c['input'].get('server')})" for c in result.tool_calls]
    return {"id": case["id"], "alert": case["alert"],
            "expected": f"get_server_status({case['expected_server']})" if case["expected_tool"] else "no call",
            "calls": called, "grade": grade, "correct": grade == "correct",
            "error": result.error, "turns": result.model_turns}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = parallel_map(run_case, load_jsonl("tool_cases.jsonl", args.limit))

    print(table([[r["id"], r["expected"], ", ".join(r["calls"]) or "no call", r["grade"]] for r in rows],
                ["id", "expected", "actual calls", "grade"]))
    correct = sum(r["correct"] for r in rows)
    print(f"\nTool-call accuracy: {pct(correct, len(rows))}")
    breakdown = Counter(r["grade"] for r in rows)
    print(f"Breakdown: {dict(breakdown)}")
    print(f"Saved: {save_csv(rows, 'stage3')}")
    save_summary({"model": config.GENERATOR_MODEL, "n": len(rows), "correct": correct,
                  "breakdown": dict(breakdown),
                  "wrong": {r["id"]: r["grade"] for r in rows if not r["correct"]}}, "stage3")


if __name__ == "__main__":
    main()
