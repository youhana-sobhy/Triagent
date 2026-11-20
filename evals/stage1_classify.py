"""Stage 1: classify and explain.

Code grader: exact match on severity.
LLM grader:  1-5 clarity rubric, scored by a different model than the one that wrote the answer.

Usage:
    python -m evals.stage1_classify --prompt v1
    python -m evals.stage1_classify --prompt v2
    python -m evals.stage1_classify --prompt v2 --dataset held_out.jsonl
"""

import argparse
import re

from evals.common import load_jsonl, parallel_map, pct, save_csv, save_summary, table
from evals.grading import severity_match
from triagent import config
from triagent.classify import classify
from triagent.llm import complete_text, track_usage

CLARITY_RUBRIC = """
You are grading the clarity of an explanation written by an alert triage assistant.

<alert>{alert}</alert>
<explanation>{explanation}</explanation>

A clear explanation answers three things in plain words:
- WHAT is wrong (the problem, e.g. "the disk is almost full")
- WHERE it is (the server or service, e.g. "db-01")
- WHY it matters (the impact, e.g. "the database may stop accepting writes")

Score from 1 to 5:
5 = Says what is wrong, where, and why it matters, in plain words. One or two sentences, no filler.
4 = Clear and correct, but missing one of: what, where, or why it matters.
3 = Understandable but vague or generic (e.g. "There is an issue with the server that should be checked").
2 = Confusing, or mostly repeats the alert text without adding meaning.
1 = Wrong, misleading, contradicts the alert, or unreadable.

Special cases:
- If the alert is empty, garbled, or too vague to act on, a 5 explanation says so plainly.
  Do not penalize it for missing "where" or "why" information that the alert never contained.
- Grade clarity only. Do not grade whether the severity is correct; that is checked separately.

Think step by step inside <thinking> tags, then output only the number inside <score> tags.
"""


def parse_score(reply: str) -> int | None:
    match = re.search(r"<score>\s*([1-5])\s*</score>", reply)
    return int(match.group(1)) if match else None


def grade_clarity(alert: str, explanation: str) -> int | None:
    reply = complete_text(CLARITY_RUBRIC.format(alert=alert, explanation=explanation), model=config.GRADER_MODEL)
    return parse_score(reply)


def run_case(case: dict, version: str) -> dict:
    with track_usage() as usage:
        output = classify(case["alert"], version)
    got = output["severity"] if output else "INVALID JSON"
    explanation = output["explanation"] if output else ""
    clarity = grade_clarity(case["alert"], explanation) if output else None
    return {"id": case["id"], "alert": case["alert"], "expected": case["expected"], "got": got,
            "pass": severity_match(got, case["expected"]), "clarity": clarity,
            "tricky": case.get("tricky", False), "explanation": explanation,
            "cost_usd": round(usage.cost, 6), "seconds": round(usage.api_seconds, 2)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="v2", choices=["v1", "v2"])
    parser.add_argument("--dataset", default="alerts.jsonl")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    cases = load_jsonl(args.dataset, args.limit)
    rows = parallel_map(lambda c: run_case(c, args.prompt), cases)

    print(table([[r["id"], r["expected"], r["got"], "PASS" if r["pass"] else "FAIL", r["clarity"]] for r in rows],
                ["id", "expected", "got", "result", "clarity"]))
    passed = sum(r["pass"] for r in rows)
    scores = [r["clarity"] for r in rows if r["clarity"] is not None]
    tricky = [r for r in rows if r["tricky"]]
    avg_clarity = sum(scores) / len(scores) if scores else None
    print(f"\nSeverity accuracy: {pct(passed, len(rows))}")
    print(f"Tricky cases:      {pct(sum(r['pass'] for r in tricky), len(tricky))}")
    print(f"Average clarity:   {avg_clarity:.2f} / 5 ({len(scores)} scored)" if scores else "")

    suffix = "" if args.dataset == "alerts.jsonl" else "_" + args.dataset.removesuffix(".jsonl")
    name = f"stage1_{args.prompt}{suffix}"
    print(f"Saved: {save_csv(rows, name)}")
    save_summary({"prompt": args.prompt, "dataset": args.dataset, "model": config.GENERATOR_MODEL,
                  "grader_model": config.GRADER_MODEL, "n": len(rows), "severity_correct": passed,
                  "tricky_correct": sum(r["pass"] for r in tricky), "tricky_n": len(tricky),
                  "avg_clarity": round(avg_clarity, 2) if avg_clarity else None,
                  "failures": [r["id"] for r in rows if not r["pass"]]}, name)


if __name__ == "__main__":
    main()
