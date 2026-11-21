"""Where do the input tokens go? Uses the free token-counting endpoint (no generation, no cost).

Splits one agent request into its static part (tool definitions + system prompt, identical for
every alert) and its per-alert part (alert text + retrieved runbooks), to decide whether prompt
caching is worth it.

Usage:
    python -m evals.token_profile
"""

from triagent import config
from triagent.agent import SYSTEM_PROMPT, USER_TEMPLATE
from triagent.llm import client
from triagent.retrieve import format_runbooks, search
from triagent.tools import TOOL_DEFINITIONS

SAMPLE_ALERT = "db-01: disk usage 95% on /var/lib/postgresql"


def count(model: str, **params) -> int:
    return client().messages.count_tokens(model=model, **params).input_tokens


def main() -> None:
    if config.OFFLINE:
        raise SystemExit("Token counting needs the real API (it is free). Unset TRIAGENT_OFFLINE.")
    model = config.GENERATOR_MODEL
    user = USER_TEMPLATE.format(alert=SAMPLE_ALERT, runbooks=format_runbooks([r for r, _ in search(SAMPLE_ALERT)]))
    tiny = [{"role": "user", "content": "x"}]

    baseline = count(model, messages=tiny)
    with_tools = count(model, messages=tiny, tools=TOOL_DEFINITIONS)
    with_system = count(model, messages=tiny, tools=TOOL_DEFINITIONS, system=SYSTEM_PROMPT)
    full = count(model, messages=[{"role": "user", "content": user}], tools=TOOL_DEFINITIONS, system=SYSTEM_PROMPT)

    static = with_system - baseline
    per_alert = full - with_system
    print(f"model: {model}")
    print(f"tool definitions:            {with_tools - baseline:>5} tokens")
    print(f"system prompt:               {with_system - with_tools:>5} tokens")
    print(f"static prefix (cacheable):   {static:>5} tokens")
    print(f"per-alert part (runbooks):   {per_alert:>5} tokens")
    print(f"full first agent request:    {full:>5} tokens  ({static / full:.0%} static)")


if __name__ == "__main__":
    main()
