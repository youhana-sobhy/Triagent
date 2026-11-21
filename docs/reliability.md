# Reliability: running Triagent like a production service

Triagent is an LLM application, but it is still a service that on-call engineers depend on. This page
frames it with the usual SRE tools (SLIs, SLOs, error budgets) and shows where an LLM app is different.
All targets below are **example values** to show the method; real targets come from real traffic.

## SLIs and SLOs

| SLI (what we measure) | How it is measured | Example SLO (target) |
| --- | --- | --- |
| **Availability**: share of alerts that get a result | `final` events with status `ok` or `degraded` ÷ all runs | 99.5% over 28 days |
| **Full-quality availability**: share answered by the model, not the fallback | status `ok` ÷ all runs | 98% |
| **Latency**: end-to-end time per alert | `run_seconds` on `final` events, p95 | p95 < 30 s |
| **Quality**: share of answers above the quality bar | online sample scored with the clarity rubric (≥ 4/5) by a different model | 90% of sampled answers ≥ 4 |
| **Grounding**: answers cite only retrieved runbooks | code check on every `final` event | 100% (any miss is a bug) |
| **Safety**: restarts executed without human approval | approval audit trail | 0, always (not a budget, a hard rule) |

`python -m monitor.summarize_logs` computes all of these from `logs/runs.jsonl` and prints `WARN` lines
using the limits in `config/thresholds.yaml`.

## Error budget

An SLO of 99.5% availability leaves an error budget of 0.5%: about 1 failed alert in 200. Two things spend it:

- **Errors**: no result at all (model and fallback both failed, or a bug).
- **Low-quality answers**: for an LLM app, a fluent but wrong answer is an outage too. Sampled answers that score below the bar spend the quality budget.

While budget remains, ship prompt and model changes (each one must pass the eval suite first). When it is
spent, freeze changes and work on reliability. Safety has no budget: one unapproved restart is an incident.

## Fallback strategy

| Situation | What happens | Logged as |
| --- | --- | --- |
| 429, 5xx, 529, timeout, connection error | Retry with exponential backoff and jitter, at most 4 attempts and 45 s in total | `retries` on the event |
| Still failing after retries, or a 4xx client error | **Degraded mode**: rule-based severity from keywords and thresholds, explanation says the AI step was unavailable, `needs_review: true` | `status: degraded` |
| Guard model down | Run fails over to degraded mode (rules already passed the text) | `status: degraded` |
| Output fails validation | Answer is returned but flagged `needs_review` | `guardrail: failed_output` |

Degraded mode is measured, not assumed: it scores 18/20 on the main set and 8/10 on the held-out set for
severity (`results/fallback_baseline.json`). It gives no runbook-based action beyond "a human should review".

## What is different from a normal service

- **Non-deterministic output.** The same alert can get a different answer on the next run. Uptime alone says nothing about correctness, so quality is a first-class SLI with its own continuous measurement (online sample + pass^k on a fixed set).
- **Silent failure mode.** A normal service fails loudly (5xx). An LLM fails with a confident, well-formatted wrong answer. Hence grounding checks, schema validation and sampled grading on live traffic.
- **Cost is a reliability concern.** Tokens scale with prompt size and retries. A prompt change can double cost without any error, so cost per alert is monitored like latency.
- **Changes are prompts and models, not only code.** Every prompt or model change goes through the same eval suite as a code change (`python evals/run_all.py`), and `prompt_version` in every log line ties answers to the prompt that produced them.
- **Untrusted input can steer the system.** Prompt injection has no real equivalent in a classic service, so input guardrails and architectural limits (propose-only tools, human approval) are part of reliability.

## Tasks mapped to SRE concepts

| Task | What was built | SRE concept |
| --- | --- | --- |
| 1. Structured logging | One JSON trace event per model/tool call, shared `run_id`, tokens, cost, retries, redaction | Structured logs, request tracing |
| 2. Monitoring | Health table, percentiles, quality sample, threshold `WARN`s | Metrics, SLIs, alerting |
| 3. Cost and latency | Token profile, one-change experiments, before/after table | Capacity planning, cost management |
| 4. Retries and fallback | Retry only transient errors, backoff + jitter, idempotent proposals, degraded mode | Timeouts, retries, graceful degradation |
| 5. Human approval | Propose-only tool, review CLI, execute-once, append-only audit trail | Change management, approval gates, audit |
