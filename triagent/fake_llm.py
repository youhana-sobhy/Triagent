"""Offline mode: a fake Anthropic client that returns simulated, deterministic responses.

Enabled with TRIAGENT_OFFLINE=1. It lets the whole pipeline (logging, retries, tools, approvals,
monitoring) run for free in CI and demos. Its answers come from the rule-based fallback, so they
say nothing about model quality, and every log line it produces is marked "simulated": true.

Fault injection for demos: TRIAGENT_FAKE_FAILURE_RATE=0.2 makes 20% of calls raise a 429/529.
"""

import json
import os
import random
import re
import threading
from types import SimpleNamespace

from triagent.fallback import rule_based_triage
from triagent.tools import DEFAULT_STATUS


class FakeAPIError(Exception):
    """Mimics an Anthropic APIStatusError (has .status_code)."""

    def __init__(self, status_code: int, message: str = "simulated error"):
        super().__init__(f"{status_code} {message}")
        self.status_code = status_code


def _usage(params: dict, out_text: str):
    return SimpleNamespace(input_tokens=len(json.dumps(params, default=str)) // 4,
                           output_tokens=max(1, len(out_text) // 4),
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


def _text(params: dict) -> str:
    """All text the model would see, flattened."""
    parts = [json.dumps(params.get("system", ""), default=str)]
    for m in params["messages"]:
        content = m["content"]
        parts.append(content if isinstance(content, str) else json.dumps(content, default=str))
    return "\n".join(parts)


class _Messages:
    def __init__(self, failure_rate: float, seed: int):
        self._failure_rate = failure_rate
        self._rng = random.Random(seed)
        self._lock = threading.Lock()

    def create(self, **params):
        with self._lock:
            roll = self._rng.random()
        if roll < self._failure_rate:
            raise FakeAPIError(429 if roll < self._failure_rate / 2 else 529)

        text = _text(params)
        alert_match = re.search(r"<alert>(.*?)</alert>", text, re.S)
        alert = alert_match.group(1).strip() if alert_match else ""
        schema = (params.get("output_config") or {}).get("format", {}).get("schema", {})
        props = schema.get("properties", {})

        # Agent turn 1: look up a server named in the alert.
        if params.get("tools") and len(params["messages"]) == 1:
            server = next((s for s in DEFAULT_STATUS if re.search(rf"\b{re.escape(s)}\b", alert)), None)
            if server:
                block = SimpleNamespace(type="tool_use", id="toolu_fake_1", name="get_server_status",
                                        input={"server": server})
                return SimpleNamespace(content=[block], stop_reason="tool_use", usage=_usage(params, server))

        if "is_injection" in props:
            out = {"is_injection": False, "reason": "simulated guard (offline mode)"}
        elif props:
            retrieved = re.findall(r'<runbook id=\\?"([a-z\-]+)\\?"', text)
            answer = rule_based_triage(alert, retrieved)
            answer["explanation"] = answer["explanation"].replace(
                "AI triage was unavailable; rule-based fallback used", "Simulated answer (offline mode)")
            out = {k: v for k, v in answer.items() if k in props}
        else:
            out = "<thinking>simulated grader (offline mode)</thinking><score>4</score>"
        out_text = out if isinstance(out, str) else json.dumps(out)
        block = SimpleNamespace(type="text", text=out_text)
        return SimpleNamespace(content=[block], stop_reason="end_turn", usage=_usage(params, out_text))


class FakeAnthropic:
    def __init__(self, failure_rate: float | None = None, seed: int = 7):
        rate = float(os.getenv("TRIAGENT_FAKE_FAILURE_RATE", "0")) if failure_rate is None else failure_rate
        self.messages = _Messages(rate, seed)
