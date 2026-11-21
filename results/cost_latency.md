# Cost and latency (Task 3)

Method: measure first, change exactly one thing, rerun the same evals on the same data, keep or revert.
Status: **baseline and cost profile measured; the "after" run is not done yet** (paid runs were paused to
save API budget). The experiment is built and ready: `python -m evals.stage5_cost --experiment caching`.

## 1. Baseline (before)

Agent `claude-sonnet-5-5`, guard `claude-haiku-5-5`, judge `claude-opus-5-5`, prompt caching off.

| Metric | Before | Source |
| --- | --- | --- |
| Severity accuracy (20 alerts / held-out 10) | 20/20 · 8/10 | `stage1_v2.json`, `stage1_v2_held_out.json` |
| Retrieval recall@3 | 13/13 | `stage2.json` |
| Citation correct / grounded | 19/20 · 20/20 | `stage2.json` |
| Tool-call accuracy | 10/10 | `stage3.json` |
| Guardrail catch / false-block rate | 10/10 · 0/10 | `stage4_input_guard.csv` |
| Tokens per alert (in / out) | 5,848 / 631 | one full-pipeline run, `main.py --trace` |
| API calls per alert | 3 (guard, agent turn 1, agent turn 2) | same run |
| Cost per alert | $0.0162 | same run, prices from `config/prices.yaml` |
| Latency per alert | 11.0 s | same run |

Per-alert cost and latency come from a single real run, so treat them as indicative, not as an average.

## 2. Where the cost goes

Measured with the free token-counting endpoint (`python -m evals.token_profile`):

| Part of one agent request | Tokens | Changes per alert? |
| --- | --- | --- |
| Tool definitions | 659 | no |
| System prompt | 623 | no |
| **Static prefix (tools + system)** | **1,282** | no: identical for every alert |
| Alert + retrieved runbooks | 1,065 | yes |
| Full first agent request | 2,356 | 54% static |

The agent sends its request at least twice per alert (tool call, then answer), so about **2,564 input tokens
per alert are the same static text repeated**. That is the dominant waste, and it is above the 512-token
minimum that Sonnet 5.5 needs for prompt caching.

## 3. The one change: prompt caching

`config/settings.yaml` → `optimization.prompt_caching: true` (or `TRIAGENT_PROMPT_CACHING=1`).
The request is ordered tools → system → messages; `cache_control: {type: ephemeral}` goes on the system
prompt, the last static block, so the cached prefix covers tools + system. Everything that changes per
alert (alert text, retrieved runbooks) comes after it.

**Expected effect (estimate, not measured):** cache reads cost $0.10/M instead of $2.00/M on Sonnet 5.5,
so the 2,564 repeated tokens drop from ~$0.0051 to ~$0.0003 per alert: **about 30% cheaper per alert**
once the cache is warm (the first call in each 5-minute window pays a small write premium). Quality should
not change, because the model sees exactly the same text.

**How to verify:** `cache_creation_input_tokens > 0` on the first call and `cache_read_input_tokens > 0` on
later calls (both logged per call in `logs/runs.jsonl` and reported by the experiment). If both stay 0,
the prefix is below the model's minimum or something in it changes between calls.

## 4. After (to fill in after the paid run)

| Metric | Before | After (caching) |
| --- | --- | --- |
| Severity accuracy | | |
| Citation accuracy | | |
| Valid output rate | | |
| Avg cost / alert | | |
| Median / p90 latency | | |
| Avg cache read / write tokens | 0 / 0 | |

Decision rule: keep caching if cost drops and accuracy is unchanged; otherwise revert the flag.

## 5. Reflection

- **What I changed:** nothing in the prompts. Caching is a request option, so quality risk is close to zero; the risk is only that it silently doesn't apply, which the cache token fields reveal.
- **What it should save:** about 30% of cost per alert from not re-billing 1,282 static tokens on every agent call.
- **Second candidate:** model tiering (Haiku agent, `--experiment small`) would save far more (~95% on agent tokens), but it changes the model, so it needs the full eval suite to show what quality it costs. One change at a time.
- **Unexpected finding:** the rule-based fallback scores 18/20 and 8/10 held-out on severity (`fallback_baseline.json`), the same as Sonnet on held-out. Severity alone is cheap to get with rules; the model earns its cost through explanations, grounded runbook actions, tool use and handling messy input.
