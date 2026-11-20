"""Triage one alert from the command line.

Usage:
    python main.py "db-01: disk usage 95% on /var/lib/postgresql"
    python main.py "web-03: CPU 100% for 30 min" --model claude-haiku-5-5 --trace

Evals live in evals/ (see README).
"""

import argparse
import json
import sys

from triagent import config
from triagent.agent import triage


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage a monitoring alert.")
    parser.add_argument("alert", help="alert text")
    parser.add_argument("--model", default=config.GENERATOR_MODEL, help="model for the agent")
    parser.add_argument("--guard", default="layered", choices=["off", "rules", "llm", "layered"],
                        help="input guardrail mode")
    parser.add_argument("--trace", action="store_true", help="also print retrieval, tool calls and usage")
    args = parser.parse_args()

    result = triage(args.alert, model=args.model, guard_mode=args.guard)

    if result.blocked:
        print(f"BLOCKED by input guardrail ({result.block_reason})")
        return 2
    if result.error:
        print(f"ERROR: {result.error}")
        return 1

    print(json.dumps(result.answer, indent=2))
    if result.violations:
        print("\nOutput guardrail violations:")
        for v in result.violations:
            print(f"  - {v}")
    if args.trace:
        print(f"\nretrieved:   {result.retrieved}")
        for call in result.tool_calls:
            print(f"tool call:   {call['name']}({json.dumps(call['input'])}) -> {json.dumps(call['result'])}")
        for req in result.approval_requests:
            print(f"approval:    #{req['id']} restart {req['server']} [{req['status']}] {req['reason']}")
        if result.redacted:
            print(f"redacted:    {result.redacted}")
        print(f"usage:       {result.model_turns} agent turns, {result.usage.n_calls} API calls, "
              f"{result.usage.input_tokens} in / {result.usage.output_tokens} out tokens, "
              f"${result.cost:.4f}, {result.seconds:.1f}s")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
