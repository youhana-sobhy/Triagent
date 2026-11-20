"""Stage 5: cost, latency and the regression check.

Runs the full pipeline (guardrails + RAG + tools) on all 20 alerts with two agent models
and logs tokens, seconds and cost per alert:

    before: claude-sonnet-5-5   (larger model)
    after:  claude-haiku-5-5    (smaller model)

The input guard uses the small model in both runs, so the difference is the agent model only.

Usage:
    python -m evals.stage5_cost
"""

import argparse
import statistics

from evals.common import load_jsonl, parallel_map, save_csv, save_summary, table
from evals.grading import citation_correct, severity_match
from triagent import config
from triagent.agent import triage

CONFIGS = {"before": config.GENERATOR_MODEL, "after": config.SMALL_MODEL}


def run_config(label: str, model: str, cases: list[dict]) -> tuple[list[dict], dict]:
    def run(case):
        r = triage(case["alert"], model=model, status_overrides=case.get("server_status"))
        answer = r.answer or {}
        return {"config": label, "model": model, "id": case["id"],
                "severity_ok": severity_match(answer.get("severity"), case["expected"]),
                "citation_ok": citation_correct(answer.get("runbook_cited"), case["expected_runbook"]),
                "valid_output": r.ok, "blocked": r.blocked,
                "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                "api_calls": r.usage.n_calls, "cost_usd": round(r.cost, 6), "seconds": round(r.seconds, 2)}

    rows = parallel_map(run, cases)
    n = len(rows)
    metrics = {
        "model": model,
        "severity_accuracy": sum(r["severity_ok"] for r in rows) / n,
        "citation_accuracy": sum(r["citation_ok"] for r in rows) / n,
        "valid_output_rate": sum(r["valid_output"] for r in rows) / n,
        "false_blocks": sum(r["blocked"] for r in rows),
        "avg_cost_usd": statistics.mean(r["cost_usd"] for r in rows),
        "total_cost_usd": sum(r["cost_usd"] for r in rows),
        "median_seconds": statistics.median(r["seconds"] for r in rows),
        "p90_seconds": sorted(r["seconds"] for r in rows)[int(0.9 * (n - 1))],
        "avg_input_tokens": statistics.mean(r["input_tokens"] for r in rows),
        "avg_output_tokens": statistics.mean(r["output_tokens"] for r in rows),
        "severity_failures": [r["id"] for r in rows if not r["severity_ok"]],
        "citation_failures": [r["id"] for r in rows if not r["citation_ok"]],
    }
    return rows, metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cases = load_jsonl("alerts.jsonl", args.limit)

    all_rows, results = [], {}
    for label, model in CONFIGS.items():
        print(f"Running {label}: {model} ...")
        rows, metrics = run_config(label, model, cases)
        all_rows += rows
        results[label] = metrics

    b, a = results["before"], results["after"]
    print()
    print(table([
        ["agent model", b["model"], a["model"], ""],
        ["severity accuracy", f"{b['severity_accuracy']:.0%}", f"{a['severity_accuracy']:.0%}",
         f"{(a['severity_accuracy'] - b['severity_accuracy']) * 100:+.0f} pts"],
        ["citation accuracy", f"{b['citation_accuracy']:.0%}", f"{a['citation_accuracy']:.0%}",
         f"{(a['citation_accuracy'] - b['citation_accuracy']) * 100:+.0f} pts"],
        ["valid output", f"{b['valid_output_rate']:.0%}", f"{a['valid_output_rate']:.0%}", ""],
        ["avg cost / alert", f"${b['avg_cost_usd']:.4f}", f"${a['avg_cost_usd']:.4f}",
         f"{(1 - a['avg_cost_usd'] / b['avg_cost_usd']):.0%} cheaper"],
        ["median latency", f"{b['median_seconds']:.1f} s", f"{a['median_seconds']:.1f} s",
         f"{(1 - a['median_seconds'] / b['median_seconds']):.0%} faster"],
        ["p90 latency", f"{b['p90_seconds']:.1f} s", f"{a['p90_seconds']:.1f} s", ""],
        ["avg tokens in / out", f"{b['avg_input_tokens']:.0f} / {b['avg_output_tokens']:.0f}",
         f"{a['avg_input_tokens']:.0f} / {a['avg_output_tokens']:.0f}", ""],
    ], ["metric", "before", "after", "change"]))
    print(f"\nbefore failures: severity {b['severity_failures']}, citation {b['citation_failures']}")
    print(f"after failures:  severity {a['severity_failures']}, citation {a['citation_failures']}")
    print(f"Saved: {save_csv(all_rows, 'stage5')}")
    save_summary(results, "stage5")


if __name__ == "__main__":
    main()
