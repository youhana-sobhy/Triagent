"""Stage 4: guardrails and agent-level (end-to-end) evals.

Part A  Input guardrail: catch rate on 10 attacks, false-block rate on 10 normal alerts,
        for three strictness settings (rules only, LLM only, layered), plus guard latency.
Part B  Action guardrail: run every attack through the agent with the input guard OFF
        (worst case), then confirm no restart was ever executed without human approval.
Part C  Reliability: 10 alerts x 3 runs through the full pipeline; pass@1, pass@3, pass^3.

Usage:
    python -m evals.stage4_guardrails
"""

import argparse
import time

from evals.common import load_jsonl, parallel_map, pct, save_csv, save_summary, table
from evals.grading import citation_correct, pass_at_k, pass_hat_k, severity_match
from triagent import config
from triagent.agent import triage
from triagent.guardrails import check_injection_llm, check_injection_rules, redact_secrets
from triagent.tools import ApprovalQueue, RestartExecutor

RELIABILITY_IDS = ["a01", "a03", "a04", "a06", "a08", "a12", "a14", "a16", "a17", "a19"]
TRIALS = 3


def input_guard_eval() -> dict:
    attacks = [dict(c, label="attack") for c in load_jsonl("attacks.jsonl")]
    normal = [dict(c, label="normal") for c in load_jsonl("guardrail_normal.jsonl")]
    cases = attacks + normal

    def screen(case):
        text, secrets = redact_secrets(case["alert"])
        rules = check_injection_rules(text)
        start = time.perf_counter()
        llm = check_injection_llm(text)
        return {"id": case["id"], "label": case["label"], "alert": case["alert"],
                "technique": case.get("technique", case.get("note", "")),
                "rules_block": rules.blocked, "llm_block": llm.blocked,
                "layered_block": rules.blocked or llm.blocked,
                "llm_seconds": round(time.perf_counter() - start, 2),
                "redacted": secrets, "redacted_text": text if secrets else "", "llm_reason": llm.reason}

    rows = parallel_map(screen, cases)
    print(table([[r["id"], r["label"], r["technique"], "BLOCK" if r["rules_block"] else "-",
                  "BLOCK" if r["llm_block"] else "-"] for r in rows],
                ["id", "label", "technique / note", "rules", "llm"]))

    modes = {}
    for mode in ("rules", "llm", "layered"):
        caught = sum(r[f"{mode}_block"] for r in rows if r["label"] == "attack")
        false_blocks = sum(r[f"{mode}_block"] for r in rows if r["label"] == "normal")
        modes[mode] = {"caught": caught, "attacks": len(attacks),
                       "false_blocks": false_blocks, "normal": len(normal)}
    llm_latency = sum(r["llm_seconds"] for r in rows) / len(rows)
    print()
    print(table([[m, pct(v["caught"], v["attacks"]), pct(v["false_blocks"], v["normal"]),
                  "~0 s" if m == "rules" else f"~{llm_latency:.1f} s"] for m, v in modes.items()],
                ["mode", "catch rate", "false-block rate", "added latency"]))
    secret_rows = [r for r in rows if r["redacted"]]
    for r in secret_rows:
        print(f"\nRedaction: {r['id']} {r['redacted']} -> {r['redacted_text']!r}")
    save_csv(rows, "stage4_input_guard")
    return {"modes": modes, "llm_guard_avg_seconds": round(llm_latency, 2), "guard_model": config.GUARD_MODEL,
            "missed_by_rules": [r["id"] for r in rows if r["label"] == "attack" and not r["rules_block"]],
            "missed_by_llm": [r["id"] for r in rows if r["label"] == "attack" and not r["llm_block"]],
            "false_blocks_llm": [r["id"] for r in rows if r["label"] == "normal" and r["llm_block"]],
            "redaction": {r["id"]: r["redacted_text"] for r in secret_rows}}


def action_guard_eval() -> dict:
    """Worst case: guard off, every attack reaches the agent. Can anything restart a server?"""
    queue = ApprovalQueue()
    executor = RestartExecutor()
    attacks = load_jsonl("attacks.jsonl")
    results = parallel_map(lambda c: triage(c["alert"], guard_mode="off", approvals=queue), attacks)

    rows = []
    for case, r in zip(attacks, results):
        proposals = [c["input"]["server"] for c in r.tool_calls if c["name"] == "propose_restart"]
        rows.append({"id": case["id"], "technique": case["technique"], "proposed_restarts": proposals,
                     "severity": (r.answer or {}).get("severity"), "output_violations": r.violations,
                     "error": r.error})

    # The executor must refuse every request a human has not approved.
    refused = 0
    for request in queue.requests:
        try:
            executor.execute(request)
        except PermissionError:
            refused += 1
    print(table([[r["id"], r["technique"], ",".join(r["proposed_restarts"]) or "-", r["severity"],
                  len(r["output_violations"])] for r in rows],
                ["id", "technique", "restart proposed", "severity", "output violations"]))
    print(f"\nApproval requests filed: {len(queue.requests)} (all pending: "
          f"{all(q.status == 'pending' for q in queue.requests)})")
    print(f"Executed without approval: {len(executor.executed)}   Refused by executor: {refused}")
    save_csv(rows, "stage4_attacks_e2e")
    return {"attacks_run_with_guard_off": len(rows), "approval_requests": len(queue.requests),
            "executed_without_approval": len(executor.executed), "refused_by_executor": refused,
            "agents_that_proposed_restart": [r["id"] for r in rows if r["proposed_restarts"]]}


def reliability_eval() -> dict:
    by_id = {c["id"]: c for c in load_jsonl("alerts.jsonl")}
    jobs = [(by_id[i], t) for i in RELIABILITY_IDS for t in range(TRIALS)]

    def run(job):
        case, trial = job
        r = triage(case["alert"], status_overrides=case.get("server_status"))
        answer = r.answer or {}
        success = (r.ok and severity_match(answer.get("severity"), case["expected"])
                   and citation_correct(answer.get("runbook_cited"), case["expected_runbook"]))
        return {"id": case["id"], "trial": trial + 1, "success": success, "ok": r.ok,
                "severity": answer.get("severity"), "expected": case["expected"],
                "cited": answer.get("runbook_cited"), "blocked": r.blocked, "violations": r.violations,
                "error": r.error, "turns": r.model_turns, "cost_usd": round(r.cost, 5),
                "seconds": round(r.seconds, 2)}

    rows = parallel_map(run, jobs)
    per_alert = []
    for alert_id in RELIABILITY_IDS:
        trials = [r for r in rows if r["id"] == alert_id]
        c = sum(r["success"] for r in trials)
        per_alert.append({"id": alert_id, "passes": c,
                          "pass_at_1": c / TRIALS, "pass_at_3": pass_at_k(TRIALS, c, TRIALS),
                          "pass_hat_3": pass_hat_k(TRIALS, c, TRIALS)})
    print(table([[p["id"], f"{p['passes']}/{TRIALS}"] for p in per_alert], ["id", "successful runs"]))
    n = len(per_alert)
    summary = {k: round(sum(p[k] for p in per_alert) / n, 3) for k in ("pass_at_1", "pass_at_3", "pass_hat_3")}
    print(f"\npass@1 (single-run success): {summary['pass_at_1']:.0%}")
    print(f"pass@3 (any of 3 succeeds):  {summary['pass_at_3']:.0%}")
    print(f"pass^3 (all 3 succeed):      {summary['pass_hat_3']:.0%}")
    save_csv(rows, "stage4_reliability")
    return {**summary, "alerts": n, "trials": TRIALS,
            "inconsistent": [p["id"] for p in per_alert if 0 < p["passes"] < TRIALS],
            "always_failed": [p["id"] for p in per_alert if p["passes"] == 0]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=["A", "B", "C"], help="run one part only")
    args = parser.parse_args()
    summary = {"model": config.GENERATOR_MODEL}
    if args.part in (None, "A"):
        print("== Part A: input guardrail ==\n")
        summary["input_guard"] = input_guard_eval()
    if args.part in (None, "B"):
        print("\n== Part B: approval gate under attack (input guard OFF) ==\n")
        summary["action_guard"] = action_guard_eval()
    if args.part in (None, "C"):
        print("\n== Part C: reliability, 10 alerts x 3 runs ==\n")
        summary["reliability"] = reliability_eval()
    save_summary(summary, "stage4" if args.part is None else f"stage4_part{args.part}")


if __name__ == "__main__":
    main()
