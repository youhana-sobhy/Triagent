"""Stage 1 and Stage 2 prompts: classify an alert, optionally grounded in runbooks.

The full pipeline with tools and guardrails is in agent.py; these single-call
versions exist so each stage can be evaluated on its own.
"""

from triagent import config
from triagent.llm import complete_json
from triagent.retrieve import format_runbooks

SEVERITIES = ["critical", "warning", "info"]

# --- Stage 1 ---------------------------------------------------------------

# v1: baseline. Scored 20/20 severity, 4.65/5 clarity.
CLASSIFY_PROMPT_V1 = """
Review this monitoring alert and classify how serious it is.

<alert>{alert}</alert>

Return:
- severity: one of critical, warning, info
- explanation: a one-line explanation of the severity you chose
"""

# v2: every clarity 4 in v1 was missing the "where" (server name) or was too long.
# Only the explanation instructions changed (one change at a time).
CLASSIFY_PROMPT_V2 = """
You are triaging a monitoring alert for an on-call engineer.

<alert>{alert}</alert>

Return:
- severity: one of critical, warning, info
- explanation: one or two plain sentences that say
  1. what is wrong,
  2. where it is (name the server or service from the alert),
  3. why it matters (the impact, or why there is none).
  If the alert is empty, garbled, or too vague to act on, say so plainly.
"""

PROMPTS = {"v1": CLASSIFY_PROMPT_V1, "v2": CLASSIFY_PROMPT_V2}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": SEVERITIES},
        "explanation": {"type": "string"},
    },
    "required": ["severity", "explanation"],
    "additionalProperties": False,
}


def classify(alert: str, version: str = "v2", model: str = config.GENERATOR_MODEL) -> dict | None:
    """One call -> {"severity", "explanation"}. None if the reply isn't valid JSON."""
    return complete_json(PROMPTS[version].format(alert=alert), schema=CLASSIFY_SCHEMA, model=model)


# --- Stage 2 ---------------------------------------------------------------

RAG_PROMPT = """
You are triaging a monitoring alert for an on-call engineer.

<alert>{alert}</alert>

These runbooks were retrieved by search for this alert. They may not all be relevant,
and none of them may fit.
<runbooks>
{runbooks}
</runbooks>

Return:
- severity: one of critical, warning, info
- explanation: one or two plain sentences that say
  1. what is wrong,
  2. where it is (name the server or service from the alert),
  3. why it matters (the impact, or why there is none).
  If the alert is empty, garbled, or too vague to act on, say so plainly.
- recommended_action: one or two sentences of concrete next steps, taken from the runbook you cite.
  Do not add steps that the runbook does not contain. If you cite "none", say what a human should check.
- runbook_cited: the id of the one runbook you based the action on, exactly as written in its id attribute,
  or "none" if no retrieved runbook fits this alert (for example success, resolved, or test alerts).
"""

RAG_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": SEVERITIES},
        "explanation": {"type": "string"},
        "recommended_action": {"type": "string"},
        # Plain string on purpose: code checks the citation was actually retrieved.
        "runbook_cited": {"type": "string"},
    },
    "required": ["severity", "explanation", "recommended_action", "runbook_cited"],
    "additionalProperties": False,
}


def classify_with_runbooks(alert: str, retrieved_ids: list[str],
                           model: str = config.GENERATOR_MODEL) -> dict | None:
    prompt = RAG_PROMPT.format(alert=alert, runbooks=format_runbooks(retrieved_ids))
    return complete_json(prompt, schema=RAG_SCHEMA, model=model)
