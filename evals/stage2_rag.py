"""Stage 2: retrieval (RAG), judged separately from the answer.

Part A, retrieval only (free, no API calls): recall@1 and recall@3 against expected_runbook labels.
Part B, answers: the model gets the top 3 runbooks and must cite one (or "none").
         Code graders: citation correct, citation grounded, severity; plus a diagnosis of
         which layer failed ("retrieval failed" vs "model ignored good context").

Usage:
    python -m evals.stage2_rag --retrieval-only
    python -m evals.stage2_rag
"""

import argparse

from evals.common import load_jsonl, parallel_map, pct, save_csv, save_summary, table
from evals.grading import citation_correct, citation_grounded, diagnose, retrieval_hit, severity_match
from triagent import config
from triagent.classify import classify_with_runbooks
from triagent.retrieve import search


def retrieval_eval(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        hits = search(case["alert"])
        rows.append({"id": case["id"], "alert": case["alert"], "expected_runbook": case["expected_runbook"],
                     "retrieved": [rid for rid, _ in hits], "distances": [round(d, 3) for _, d in hits]})
    labeled = [r for r in rows if r["expected_runbook"]]
    at1 = sum(retrieval_hit(r["retrieved"], r["expected_runbook"], 1) for r in labeled)
    at3 = sum(retrieval_hit(r["retrieved"], r["expected_runbook"], 3) for r in labeled)
    misses = [r["id"] for r in labeled if not retrieval_hit(r["retrieved"], r["expected_runbook"], 3)]

    print(table([[r["id"], ",".join(r["expected_runbook"]) or "none", ",".join(r["retrieved"]),
                  r["distances"][0] if r["distances"] else "-"] for r in rows],
                ["id", "expected", "top 3", "top distance"]))
    print(f"\nrecall@1: {pct(at1, len(labeled))}")
    print(f"recall@3: {pct(at3, len(labeled))}")
    print(f"misses@3: {misses or 'none'}")
    save_csv(rows, "stage2_retrieval")
    return {"labeled": len(labeled), "recall_at_1": at1, "recall_at_3": at3, "misses_at_3": misses}


def answer_case(case: dict) -> dict:
    retrieved = [rid for rid, _ in search(case["alert"])]
    output = classify_with_runbooks(case["alert"], retrieved) or {}
    cited = output.get("runbook_cited", "INVALID JSON")
    expected = case["expected_runbook"]
    return {"id": case["id"], "alert": case["alert"], "expected_runbook": expected, "retrieved": retrieved,
            "cited": cited, "citation_ok": citation_correct(cited, expected),
            "grounded": citation_grounded(cited, retrieved), "diagnosis": diagnose(cited, expected, retrieved),
            "expected": case["expected"], "got": output.get("severity"),
            "severity_ok": severity_match(output.get("severity"), case["expected"]),
            "explanation": output.get("explanation", ""), "recommended_action": output.get("recommended_action", "")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cases = load_jsonl("alerts.jsonl", args.limit)

    print("== Part A: retrieval ==\n")
    summary = {"retrieval": retrieval_eval(cases)}

    if not args.retrieval_only:
        print("\n== Part B: answers with citations ==\n")
        rows = parallel_map(answer_case, cases)
        print(table([[r["id"], ",".join(r["expected_runbook"]) or "none", r["cited"],
                      "OK" if r["citation_ok"] else "WRONG", r["diagnosis"],
                      "PASS" if r["severity_ok"] else "FAIL"] for r in rows],
                    ["id", "expected", "cited", "citation", "diagnosis", "severity"]))
        n = len(rows)
        cit, grd, sev = (sum(r[k] for r in rows) for k in ("citation_ok", "grounded", "severity_ok"))
        print(f"\nCitation accuracy:  {pct(cit, n)}")
        print(f"Grounded citations: {pct(grd, n)}")
        print(f"Severity accuracy:  {pct(sev, n)}")
        print(f"Saved: {save_csv(rows, 'stage2')}")
        print("Next: python -m evals.faithfulness_check   (manual check of 5 answers)")
        summary["answers"] = {"model": config.GENERATOR_MODEL, "n": n, "citation_correct": cit, "grounded": grd,
                              "severity_correct": sev,
                              "not_ok": {r["id"]: r["diagnosis"] for r in rows if r["diagnosis"] != "ok"},
                              "severity_failures": [r["id"] for r in rows if not r["severity_ok"]]}
    save_summary(summary, "stage2_retrieval_only" if args.retrieval_only else "stage2")


if __name__ == "__main__":
    main()
