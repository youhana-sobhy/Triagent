# Monitoring example

> Generated from **simulated** offline runs (fake model, injected 429/529 errors), so the numbers show the monitoring mechanics, not model quality or real latency.

Command: `python -m monitor.summarize_logs --log logs/runs_offline.jsonl --save`

```text
Triagent health report: runs_offline.jsonl

Runs (alerts)                 30  (30 simulated)
Error rate                    0%
Degraded (fallback) rate      0%
Latency avg / p50 / p95       0.79s / 0.65s / 2.10s
Tokens total / avg per alert  72,647 / 2,422
Cost total / avg per alert    $0.1453 / $0.0048
Tool calls / failure rate     17 / 0%
Input guardrail block rate    27%
Output guardrail failures     0
Retries (total)               15
Flagged needs_review          0
Grounded citations            100%
Online quality sample         4.00 / 5  (n=10, grader claude-opus-5-5, generator claude-sonnet-5-5)

WARN guardrail block rate 27% above limit 20%
```
