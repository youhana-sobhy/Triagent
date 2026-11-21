# Eval suite summary (free)

Run at 2026-11-21T21:25:00+00:00. Command: `python evals/run_all.py --free`

| Step | Command | Result | Time |
| --- | --- | --- | --- |
| Unit tests (guardrails, approvals, retries, logging, graders) | `python -m pytest -q` | PASS | 10s |
| Stage 2 retrieval recall@3 | `python -m evals.stage2_rag --retrieval-only` | PASS | 8s |
| Degraded-mode fallback accuracy | `python -m evals.fallback_baseline` | PASS | 0s |
| Offline pipeline, 20 alerts with injected 429/529s | `python -m evals.run_pipeline` | PASS | 10s |
| Offline pipeline, 10 attacks | `python -m evals.run_pipeline --dataset attacks.jsonl` | PASS | 7s |
| Monitoring report on offline logs | `python -m monitor.summarize_logs --log logs/runs_offline.jsonl --save` | PASS | 10s |

Paid steps not run: Stage 1 classify, prompt v1, Stage 1 classify, prompt v2, Stage 1 held-out set, Stage 2 RAG answers, Stage 3 tool calls, Stage 4 guardrails + pass^3, Stage 5 cost: prompt caching before/after, Pipeline on 20 alerts (real logs), Monitoring report with online quality sample.
Their latest saved results are in `results/*.json`.
