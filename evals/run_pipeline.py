"""Run alerts through the full pipeline and write traces to the log (input for monitoring).

Usage:
    python -m evals.run_pipeline                              # 20 alerts, real model (paid)
    python -m evals.run_pipeline --dataset attacks.jsonl
    TRIAGENT_OFFLINE=1 python -m evals.run_pipeline           # simulated, free (logs/runs_offline.jsonl)
    TRIAGENT_OFFLINE=1 TRIAGENT_FAKE_FAILURE_RATE=0.15 python -m evals.run_pipeline   # with injected 429/529s
"""

import argparse

from approvals.store import ApprovalStore
from evals.common import load_jsonl, parallel_map, table
from triagent import config
from triagent.agent import triage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="alerts.jsonl")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    store = ApprovalStore(config.APPROVALS_DIR)   # restart requests land in the real review queue
    cases = load_jsonl(args.dataset, args.limit)
    results = parallel_map(lambda c: triage(c["alert"], alert_id=c["id"], approvals=store,
                                            status_overrides=c.get("server_status")), cases)
    print(table([[r.alert_id, r.run_id, (r.answer or {}).get("severity", "-"), r.guardrail_outcome,
                  "degraded" if r.degraded else ("error" if r.error else "ok"), r.usage.retries,
                  f"{r.seconds:.1f}s", "yes" if r.needs_review else ""] for r in results],
                ["alert", "run_id", "severity", "guardrail", "status", "retries", "time", "review"]))
    mode = "SIMULATED (offline)" if config.OFFLINE else "real model"
    print(f"\n{len(results)} runs ({mode}) logged to {config.LOG_PATH}")
    pending = store.list("pending")
    if pending:
        print(f"{len(pending)} restart request(s) waiting: python -m approvals.review list")


if __name__ == "__main__":
    main()
