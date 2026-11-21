# next.md: Production-readiness tasks for Triagent (Day 9)

This file is a self-contained task spec. If you are Claude (or any engineer) reading it later without the earlier conversation, everything you need is here.

## 0. Context

**Triagent** is a learning project: an alert triage assistant. Input is a raw monitoring alert; output is structured JSON with `severity` (`critical` / `warning` / `info`), `explanation`, `recommended_action`, `runbook_cited`, `needs_approval`.

Runtime flow:
1. Input guardrail (prompt-injection check on the untrusted alert text).
2. Classify with the model (structured JSON output).
3. Retrieve the top 3 runbook chunks (RAG).
4. Agent loop with tools: `get_server_status(server)` (read-only, fake data) and `propose_restart(server)` (only creates an approval request, never executes).
5. Final structured answer.
6. Output guardrail (valid schema, no secrets, cited runbook was actually retrieved).

Already built by the user (Stages 1 to 4): the 20-alert dataset (`alerts.jsonl`), severity eval (exact match), explanation clarity eval (LLM grader with a 1 to 5 rubric, validated by hand labels), retrieval eval (recall@3), tool-call eval, guardrail evals (attack and normal sets, catch rate and false-block rate). See `project.md` for the full plan.

**This file covers the remaining production work (Stage 5 and the "Day 9" topics):** logging, monitoring, cost and latency, retries, human-in-the-loop, plus a short reliability write-up.

## 1. How to use this file (instructions for the implementer)

1. Read `project.md`, then inspect the existing code and folders before changing anything. Do not assume file names; adapt the paths below to what exists.
2. Work one task at a time, in the order below. After each task, run the existing evals and confirm nothing regressed.
3. Make small, reviewable changes. Reuse existing graders and scripts; do not rewrite them.
4. Do not hard-code prices, model limits or cache minimums. Put prices in a config file and tell the user to fill them from the current pricing page. Check the current Anthropic docs for prompt caching details.
5. If the project structure is unclear or a requirement conflicts with existing code, ask the user one short question instead of guessing.
6. Explain each change in plain language when done. The user is a beginner in AI who wants to understand, not just receive code.

**Global constraints**
- Python and the Anthropic SDK. No heavy new dependencies.
- All evals stay runnable with one command (target: `python evals/run_all.py`). Create this script if it does not exist.
- Never log secrets or personal data.
- Never auto-retry an action that changes state without protection against duplicates.

## 2. Task 1: Structured logging of prompts and tool calls

**Goal:** every request can be reconstructed later to understand why something went wrong.

**Requirements**
- Wrap every model call and every tool call in a logging function (for example `logged_call`).
- Append one JSON object per line to `logs/runs.jsonl` with at least:
  - `run_id` (one per alert run), `alert_id`, `timestamp`
  - `step` (`classify`, `retrieve`, `agent`, `final`, `guardrail`)
  - `model`, `prompt_version` (a simple string constant you bump when the prompt changes)
  - `input_tokens`, `output_tokens`, and the cache token fields if present (`cache_creation_input_tokens`, `cache_read_input_tokens`)
  - `seconds` (wall-clock time of the call)
  - `cost` (computed from tokens and the prices in the config file)
  - `tool_calls`: list of `{name, args, result_summary, error}`
  - `status` (`ok` or `error`), `error_type`, `retries`
  - `guardrail` outcome (`passed`, `blocked_input`, `failed_output`)
  - the final output JSON for the `final` step
- Redact secrets before writing: API keys, tokens, passwords, anything matching simple patterns. Add a small `redact()` function and a test for it.
- Read token counts from the response usage fields. Time calls with a monotonic clock.

**Deliverables:** `triagent/logging_utils.py` (or similar), `logs/` folder, `config/prices.yaml` (prices left for the user to fill), unit test for `redact()`.

**Acceptance checks**
- Running the 20 alerts produces at least 20 valid JSON lines.
- A single `run_id` shows all steps of one alert in order.
- A test string containing a fake API key is redacted in the log.

**Interview line:** "I log structured traces for every model and tool call, with tokens, latency, cost and outcome, so any bad answer can be reconstructed and replayed."

## 3. Task 2: Monitoring from the logs

**Goal:** turn raw logs into a small set of numbers that tell you whether the system is healthy, including quality.

**Requirements**
- Script `monitor/summarize_logs.py` reads `logs/runs.jsonl` and prints a table:
  - total requests, error rate
  - latency: average, p50, p95
  - tokens and cost: total, average per alert
  - tool-call failure rate
  - guardrail block rate
  - total retries
- **Online quality check:** sample N logged runs (default 10), score them with the existing LLM graders (reuse the Stage 1 clarity rubric and, if applicable, the grounding check), and report the average score.
- **Thresholds:** `config/thresholds.yaml` with example limits (error rate, p95 latency, daily cost, minimum quality score). The script prints `WARN` lines when a metric crosses a threshold. Values are placeholders for the user to tune.

**Deliverables:** `monitor/summarize_logs.py`, `config/thresholds.yaml`, a sample output saved to `results/monitoring_example.md`.

**Acceptance checks**
- The script runs on the real log file and prints the table.
- Lowering a threshold in the config makes a `WARN` appear.
- The quality sample uses a different model as grader than the one that generated the output, as in the earlier evals.

**Interview line:** "I monitor the usual service signals plus quality: I sample live traffic and score it with the same graders I use offline."

## 4. Task 3: Cost and latency optimization

**Goal:** reduce cost or time per alert without reducing quality, and prove it.

**Requirements**
1. **Baseline.** Run all evals and save a table in `results/cost_latency.md`: severity accuracy, recall@3, tool-call accuracy, guardrail catch and false-block rates, average tokens, average cost, average seconds per alert.
2. **Find the dominant cost** from the logs (usually repeated input: system prompt, tools, runbooks).
3. **Change exactly one thing at a time.** Options:
   - Model tiering: a smaller, cheaper model for the simple classification step, a larger one for final reasoning. Make the model per step a config value.
   - Prompt caching: order the prompt as tools, then system prompt, then messages, and put `cache_control` (type `ephemeral`) on the last static block. The per-alert content (alert text, retrieved chunks that change per alert) goes after the cached part. Verify with the `cache_creation_input_tokens` and `cache_read_input_tokens` usage fields: the first call should write, later calls should read. Check current docs for minimum cacheable size and expiry; if both counts are 0, the prompt is probably too short.
   - Shorter outputs (lower `max_tokens`, terse explanations).
4. **Rerun all evals** and add an "After" column. Keep or revert the change based on the data.
5. Write 3 to 5 lines of reflection: what changed, what it saved, what it cost in quality.

**Deliverables:** updated `results/cost_latency.md` with before and after, config values for models, the caching change if chosen.

**Acceptance checks**
- Same dataset and same eval scripts before and after.
- The conclusion is stated with numbers, including any quality loss.

**Interview line:** "I measure first, change one thing at a time, and rerun the full eval suite as a regression check before deciding."

## 5. Task 4: Retries, timeouts and fallbacks

**Goal:** temporary failures should not become failed requests, and retries must never cause damage.

**Requirements**
- Set `max_retries` and `timeout` on the Anthropic client (the SDK retries some errors itself). Make both config values.
- Add an application-level retry helper for tool calls and other steps:
  - retry only retryable failures: rate limits (429), server errors (5xx), timeouts, connection errors
  - do not retry client errors (4xx such as invalid requests)
  - exponential backoff with jitter, a maximum number of attempts, a maximum total time
  - log the number of retries per step (feeds Task 1)
- **Idempotency:** `propose_restart` must not create duplicate requests if a step is retried. Use a deterministic key (for example hash of server and alert id) and ignore duplicates.
- **Fallback when the model is unavailable:** return a degraded result instead of crashing, for example a simple rule-based severity (keywords and thresholds) with `explanation` stating that the AI step was unavailable, and mark the run `degraded` in the logs.
- **Tests with a fake client** that raises errors: verify retries happen for 429 and 5xx, do not happen for 4xx, stop after the maximum, and the fallback is used.

**Deliverables:** `triagent/retry.py`, fallback function, `tests/test_retry.py`.

**Acceptance checks**
- Simulated 429 then success: succeeds after retry and logs `retries=1`.
- Simulated 400: no retry.
- Retried `propose_restart` creates exactly one pending request.
- Simulated total outage: degraded fallback result, not an exception.

**Interview line:** "I retry only transient errors with backoff and jitter, make state-changing actions idempotent, and degrade gracefully when the model is down."

## 6. Task 5: Human-in-the-loop approval

**Goal:** a person must approve any action that changes a production system, with an audit trail.

**Requirements**
- `propose_restart(server, reason)` writes a pending request to `approvals/requests.jsonl` with: `request_id`, `server`, `reason`, `alert_id`, `requested_at`, `status` (`pending`).
- CLI `approvals/review.py` with subcommands: `list` (show pending), `approve <id>`, `reject <id>`. Approve and reject record the reviewer name, time and optional note.
- A separate `execute_approved()` step (a fake executor that only prints or records the action) runs **only** requests with status `approved`, and marks them `executed` so they run once.
- Add a `needs_review` flag in the final output for cases that deserve a human look even without an action: for example severity `critical` combined with a tool failure, or an output guardrail failure.
- Keep an append-only audit trail of every status change.

**Deliverables:** `approvals/` module, CLI, tests.

**Acceptance checks (write as tests)**
- A restart is never executed without approval.
- A rejected request is never executed.
- Approving twice executes once.
- The audit log shows who approved what and when.

**Interview line:** "Read-only tools run automatically; state-changing actions are only proposed, and a human approves them with a full audit trail."

## 7. Task 6: Reliability write-up (link to uptime and SRE experience)

**Goal:** a short document that frames the LLM app like a production service.

Write `docs/reliability.md` (about one page) covering:
- **SLIs and SLOs** for availability (share of alerts that get a result), latency (for example p95 under a chosen limit), and quality (share of outputs scoring above a threshold in the online eval). Use placeholder targets and say they are examples.
- **Error budget** idea applied to errors and low-quality answers.
- **Fallback strategy** from Task 4 and when it triggers.
- **What differs from a normal service:** outputs are non-deterministic, so quality needs continuous measurement, not only uptime.
- A table mapping each of Tasks 1 to 5 to the SRE concept it corresponds to (structured logs, metrics and alerting, capacity and cost, retries and timeouts, change approval).

## 8. Final steps

1. Run the full eval suite with one command and save the result to `results/day9_summary.md`.
2. Update `README.md`: a short section describing logging, monitoring, retries, approvals, and the before and after cost table.
3. Add a simple CI workflow (GitHub Actions) that runs the tests and the offline evals on every push, if the user wants it. Keep API-key usage out of the repo and use CI secrets.
4. Give the user a short plain-language summary of what was built and how to explain it in an interview.

## 9. Overall definition of done

- [ ] Logs exist for every model and tool call, with redaction.
- [ ] A monitoring summary prints health and quality numbers with threshold warnings.
- [ ] A before and after cost and latency table exists, with quality unchanged or the loss explained.
- [ ] Retries, timeouts, idempotency and a fallback are implemented and tested.
- [ ] Restarts can never run without approval, and the audit trail works.
- [ ] `docs/reliability.md` exists.
- [ ] All earlier evals still pass at their previous levels.

## 10. Questions the user should be able to answer afterwards

- How do you log and monitor an LLM application, and what is different from a normal service?
- How do you reduce cost without hurting quality, and how do you prove it?
- Which errors do you retry, which not, and why must restarts be idempotent?
- How does human approval work, and what do you keep for auditing?
- How would you define availability, latency and quality targets for this system?
