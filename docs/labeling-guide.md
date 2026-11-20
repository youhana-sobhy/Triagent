# Severity criteria

Labels in `alerts.jsonl` are decided against these rules, written before any model is run.

| Severity | Definition | Response time |
| --- | --- | --- |
| `critical` | Users are affected now, or an outage or data loss will happen soon if no one acts. | Minutes |
| `warning` | Something is degraded or heading toward a problem, but users are not yet affected. | Hours |
| `info` | No action needed: success notices, resolved alerts, healthy metrics, or no usable signal. | None |

## Tie-break rules for tricky alerts

1. **Evidence beats labels.** If the alert text calls itself "CRITICAL" but the metric is healthy, go by the metric.
2. **User impact beats health checks.** If requests are failing, the service is down even if a health check says OK.
3. **No signal means `info`.** An empty or vague alert with no metric, server, or symptom gives nothing to act on. The explanation should say the alert is not actionable.
4. **Partial signal of a serious problem means `warning`.** If garbled text still hints at a serious problem, label it `warning` so a human looks. Do not label it `critical`, because nothing can be confirmed.
5. **Resolved and test alerts are `info`.**

## Runbook labels (`expected_runbook`)

Each alert lists the runbook(s) retrieval should find, as a list of runbook IDs (file names in `data/runbooks/` without `.md`).

1. **Current condition on a runbook topic:** label that runbook, even if the value is healthy (a11, a19). The runbook is still the relevant document; deciding that nothing is wrong is the classifier's job.
2. **No current condition:** success notices, resolved alerts, test alerts, and empty or vague alerts get `[]`.
3. **No runbook covers it:** for example the SMTP queue (a14), label `[]`.
4. **Two runbooks fit:** list both (a12). Retrieval counts as a hit if any of them is in the top 3.

Alerts labeled `[]` are left out of recall@3, because there is nothing to find.
