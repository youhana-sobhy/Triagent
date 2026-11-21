"""Run the whole eval suite with one command (the regression check to run after every change).

Usage:
    python evals/run_all.py            # everything, including paid API calls (a few dollars)
    python evals/run_all.py --free     # no API calls: unit tests, retrieval, fallback, offline pipeline + monitoring

Writes a step-by-step summary to results/day9_summary.md.
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = {"TRIAGENT_OFFLINE": "1", "TRIAGENT_FAKE_FAILURE_RATE": "0.15"}

FREE = [
    ("Unit tests (guardrails, approvals, retries, logging, graders)", ["-m", "pytest", "-q"], {}),
    ("Stage 2 retrieval recall@3", ["-m", "evals.stage2_rag", "--retrieval-only"], {}),
    ("Degraded-mode fallback accuracy", ["-m", "evals.fallback_baseline"], {}),
    ("Offline pipeline, 20 alerts with injected 429/529s", ["-m", "evals.run_pipeline"], OFFLINE),
    ("Offline pipeline, 10 attacks", ["-m", "evals.run_pipeline", "--dataset", "attacks.jsonl"], OFFLINE),
    ("Monitoring report on offline logs",
     ["-m", "monitor.summarize_logs", "--log", "logs/runs_offline.jsonl", "--save"], OFFLINE),
]
PAID = [
    ("Stage 1 classify, prompt v1", ["-m", "evals.stage1_classify", "--prompt", "v1"], {}),
    ("Stage 1 classify, prompt v2", ["-m", "evals.stage1_classify", "--prompt", "v2"], {}),
    ("Stage 1 held-out set", ["-m", "evals.stage1_classify", "--prompt", "v2", "--dataset", "held_out.jsonl"], {}),
    ("Stage 2 RAG answers", ["-m", "evals.stage2_rag"], {}),
    ("Stage 3 tool calls", ["-m", "evals.stage3_tools"], {}),
    ("Stage 4 guardrails + pass^3", ["-m", "evals.stage4_guardrails"], {}),
    ("Stage 5 cost: prompt caching before/after", ["-m", "evals.stage5_cost", "--experiment", "caching"], {}),
    ("Pipeline on 20 alerts (real logs)", ["-m", "evals.run_pipeline"], {}),
    ("Monitoring report with online quality sample", ["-m", "monitor.summarize_logs"], {}),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--free", action="store_true", help="skip everything that calls the API")
    args = parser.parse_args()
    steps = FREE if args.free else FREE + PAID

    log_file = ROOT / "logs" / "runs_offline.jsonl"
    if log_file.exists():
        log_file.unlink()   # fresh offline log each suite run, so the report reflects this run only

    rows = []
    for name, cmd, env in steps:
        print(f"\n{'=' * 72}\n{name}\n$ python {' '.join(cmd)}\n{'=' * 72}", flush=True)
        start = time.monotonic()
        code = subprocess.run([sys.executable, *cmd], cwd=ROOT, env={**os.environ, **env}).returncode
        rows.append((name, " ".join(cmd), "PASS" if code == 0 else "FAIL", time.monotonic() - start))

    lines = [f"# Eval suite summary ({'free' if args.free else 'full'})", "",
             f"Run at {datetime.now(timezone.utc).isoformat(timespec='seconds')}. "
             f"Command: `python evals/run_all.py{' --free' if args.free else ''}`", "",
             "| Step | Command | Result | Time |", "| --- | --- | --- | --- |"]
    lines += [f"| {n} | `python {c}` | {r} | {s:.0f}s |" for n, c, r, s in rows]
    if args.free:
        lines += ["", "Paid steps not run: " + ", ".join(n for n, _, _ in PAID) + ".",
                  "Their latest saved results are in `results/*.json`."]
    (ROOT / "results" / "day9_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    failed = [r for r in rows if r[2] == "FAIL"]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} steps passed. Summary: results/day9_summary.md")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
