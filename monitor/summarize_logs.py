"""Turn logs/runs.jsonl into health and quality numbers, with threshold warnings.

Service signals: requests, error and degraded rates, latency (avg / p50 / p95), tokens, cost,
tool-call failures, guardrail blocks, retries.
Quality signals: grounded-citation rate (code check on every run) and an online quality sample:
N logged answers scored with the Stage 1 clarity rubric by a DIFFERENT model than the one that wrote them.

Usage:
    python -m monitor.summarize_logs                              # logs/runs.jsonl
    python -m monitor.summarize_logs --log logs/runs_offline.jsonl --save
    python -m monitor.summarize_logs --no-quality                 # skip the LLM-graded sample (free)
"""

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from triagent import config


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(p / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue   # a corrupted line must not break monitoring
    return events


def compute_metrics(events: list[dict]) -> dict:
    run_events = [e for e in events if e.get("run_id")]
    finals = [e for e in run_events if e["step"] == "final"]
    tools = [e for e in run_events if e["step"] == "tool"]
    n = len(finals)
    latencies = [e.get("run_seconds", 0) for e in finals]
    cost_by_day = defaultdict(float)
    for e in finals:
        cost_by_day[e["timestamp"][:10]] += e.get("run_cost", 0)
    with_output = [e for e in finals if e.get("output")]
    grounded = sum(e["output"].get("runbook_cited") == "none"
                   or e["output"].get("runbook_cited") in (e.get("retrieved") or []) for e in with_output)
    return {
        "runs": n,
        "simulated_runs": sum(bool(e.get("simulated")) for e in finals),
        "error_rate": sum(e["status"] == "error" for e in finals) / n if n else 0,
        "degraded_rate": sum(e["status"] == "degraded" for e in finals) / n if n else 0,
        "latency_avg_s": statistics.mean(latencies) if latencies else 0,
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "tokens_total": sum(e.get("run_input_tokens", 0) + e.get("run_output_tokens", 0) for e in finals),
        "tokens_avg": statistics.mean([e.get("run_input_tokens", 0) + e.get("run_output_tokens", 0)
                                       for e in finals]) if finals else 0,
        "cost_total_usd": sum(e.get("run_cost", 0) for e in finals),
        "cost_avg_usd": statistics.mean([e.get("run_cost", 0) for e in finals]) if finals else 0,
        "max_daily_cost_usd": max(cost_by_day.values()) if cost_by_day else 0,
        "tool_calls": len(tools),
        "tool_failure_rate": sum(e["status"] == "error" for e in tools) / len(tools) if tools else 0,
        "guardrail_block_rate": sum(e.get("guardrail") == "blocked_input" for e in finals) / n if n else 0,
        "output_guardrail_failures": sum(e.get("guardrail") == "failed_output" for e in finals),
        "retries_total": sum(e.get("retries", 0) for e in run_events if e["step"] != "final"),
        "needs_review": sum(bool(e.get("needs_review")) for e in finals),
        "grounded_rate": grounded / len(with_output) if with_output else 1.0,
    }


def quality_sample(events: list[dict], n: int, seed: int = 0) -> dict:
    """Score N logged answers with the Stage 1 clarity rubric, using a different model as grader."""
    from evals.stage1_classify import grade_clarity   # reuse the offline grader as-is

    candidates = [e for e in events if e.get("step") == "final" and e.get("status") == "ok"
                  and e.get("output") and e.get("alert") is not None]
    sample = random.Random(seed).sample(candidates, min(n, len(candidates)))
    generators = {e.get("model") for e in sample}
    grader = config.GRADER_MODEL if config.GRADER_MODEL not in generators else config.SMALL_MODEL
    if grader in generators:
        raise SystemExit("No grader model available that differs from the generator; set models.grader.")
    scores = [s for s in (grade_clarity(e["alert"], e["output"]["explanation"]) for e in sample) if s]
    return {"sample_size": len(sample), "scored": len(scores), "grader_model": grader,
            "generator_models": sorted(m for m in generators if m),
            "avg_quality": statistics.mean(scores) if scores else None}


def warnings(m: dict, q: dict | None, t: dict) -> list[str]:
    checks = [
        ("error rate", m["error_rate"], ">", t["max_error_rate"], "{:.0%}"),
        ("degraded rate", m["degraded_rate"], ">", t["max_degraded_rate"], "{:.0%}"),
        ("p95 latency", m["latency_p95_s"], ">", t["max_p95_latency_s"], "{:.1f}s"),
        ("daily cost", m["max_daily_cost_usd"], ">", t["max_daily_cost_usd"], "${:.2f}"),
        ("tool failure rate", m["tool_failure_rate"], ">", t["max_tool_failure_rate"], "{:.0%}"),
        ("guardrail block rate", m["guardrail_block_rate"], ">", t["max_guardrail_block_rate"], "{:.0%}"),
        ("grounded rate", m["grounded_rate"], "<", t["min_grounded_rate"], "{:.0%}"),
    ]
    if q and q["avg_quality"] is not None:
        checks.append(("quality score", q["avg_quality"], "<", t["min_quality_score"], "{:.2f}"))
    out = []
    for name, value, op, limit, fmt in checks:
        if (value > limit) if op == ">" else (value < limit):
            out.append(f"WARN {name} {fmt.format(value)} {'above' if op == '>' else 'below'} "
                       f"limit {fmt.format(limit)}")
    return out


def render(m: dict, q: dict | None, warns: list[str], log_path: Path) -> str:
    rows = [
        ("Runs (alerts)", f"{m['runs']}" + (f"  ({m['simulated_runs']} simulated)" if m["simulated_runs"] else "")),
        ("Error rate", f"{m['error_rate']:.0%}"),
        ("Degraded (fallback) rate", f"{m['degraded_rate']:.0%}"),
        ("Latency avg / p50 / p95", f"{m['latency_avg_s']:.2f}s / {m['latency_p50_s']:.2f}s / {m['latency_p95_s']:.2f}s"),
        ("Tokens total / avg per alert", f"{m['tokens_total']:,} / {m['tokens_avg']:,.0f}"),
        ("Cost total / avg per alert", f"${m['cost_total_usd']:.4f} / ${m['cost_avg_usd']:.4f}"),
        ("Tool calls / failure rate", f"{m['tool_calls']} / {m['tool_failure_rate']:.0%}"),
        ("Input guardrail block rate", f"{m['guardrail_block_rate']:.0%}"),
        ("Output guardrail failures", f"{m['output_guardrail_failures']}"),
        ("Retries (total)", f"{m['retries_total']}"),
        ("Flagged needs_review", f"{m['needs_review']}"),
        ("Grounded citations", f"{m['grounded_rate']:.0%}"),
    ]
    if q:
        quality = f"{q['avg_quality']:.2f} / 5" if q["avg_quality"] is not None else "n/a"
        rows.append(("Online quality sample", f"{quality}  (n={q['scored']}, grader {q['grader_model']}, "
                                              f"generator {', '.join(q['generator_models'])})"))
    width = max(len(r[0]) for r in rows)
    lines = [f"Triagent health report: {log_path.name}", ""]
    lines += [f"{name.ljust(width)}  {value}" for name, value in rows]
    lines += [""] + (warns or ["OK: all metrics within thresholds"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=config.LOG_PATH)
    parser.add_argument("--quality-sample", type=int, default=10)
    parser.add_argument("--no-quality", action="store_true")
    parser.add_argument("--save", action="store_true", help="write results/monitoring_example.md")
    args = parser.parse_args()

    if not args.log.exists():
        raise SystemExit(f"{args.log} not found. Run: python -m evals.run_pipeline")
    events = load_events(args.log)
    metrics = compute_metrics(events)
    quality = None if args.no_quality else quality_sample(events, args.quality_sample)
    warns = warnings(metrics, quality, config.THRESHOLDS)
    report = render(metrics, quality, warns, args.log)
    print(report)
    if args.save:
        out = config.RESULTS_DIR / "monitoring_example.md"
        note = ("> Generated from **simulated** offline runs (fake model, injected 429/529 errors), so the "
                "numbers show the monitoring mechanics, not model quality or real latency.\n\n"
                if metrics["simulated_runs"] else "")
        out.write_text(f"# Monitoring example\n\n{note}Command: `python -m monitor.summarize_logs "
                       f"--log {args.log.as_posix().split('Triagent/')[-1]} --save`\n\n```text\n{report}\n```\n",
                       encoding="utf-8")
        print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
