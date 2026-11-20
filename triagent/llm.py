"""Thin wrapper around the Anthropic Messages API.

Every call is timed and its token usage and cost are recorded, so each eval can
report cost and latency per alert (Stage 5).
"""

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from anthropic import Anthropic

from triagent import config


class RefusalError(RuntimeError):
    """The model declined the request (stop_reason == "refusal").

    No automatic fallback to another model on purpose: in an eval, a refusal must
    count as a failure of the model under test, not be hidden by a different model.
    """


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    seconds: float
    stop_reason: str

    @property
    def cost(self) -> float:
        price_in, price_out, price_cache_read = config.PRICES.get(self.model, (0.0, 0.0, 0.0))
        return (
            self.input_tokens * price_in
            + self.output_tokens * price_out
            + self.cache_read_tokens * price_cache_read
            + self.cache_write_tokens * price_in * 1.25
        ) / 1_000_000


@dataclass
class Usage:
    """Sum of every API call made while tracking was on."""
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def n_calls(self) -> int:
        return len(self.calls)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens + c.cache_read_tokens + c.cache_write_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def cost(self) -> float:
        return sum(c.cost for c in self.calls)

    @property
    def api_seconds(self) -> float:
        return sum(c.seconds for c in self.calls)


# Usage trackers are per thread, so evals can run alerts in parallel.
_local = threading.local()


@contextmanager
def track_usage():
    """Record every API call made inside the `with` block (in this thread)."""
    usage = Usage()
    stack = getattr(_local, "stack", [])
    _local.stack = stack
    stack.append(usage)
    try:
        yield usage
    finally:
        stack.remove(usage)


def _record(record: CallRecord) -> None:
    for usage in getattr(_local, "stack", []):
        usage.calls.append(record)


_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        # Reads ANTHROPIC_API_KEY from the environment (.env is loaded in config).
        _client = Anthropic(timeout=config.REQUEST_TIMEOUT_S, max_retries=config.MAX_RETRIES)
    return _client


def create_message(
    *,
    model: str,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
):
    """One Messages API call. Returns the raw response; records usage and latency."""
    params: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        params["system"] = system
    if tools:
        params["tools"] = tools
    if schema:
        # Structured output: the final text is guaranteed to match this JSON schema.
        params["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

    start = time.perf_counter()
    response = client().messages.create(**params)
    seconds = time.perf_counter() - start

    u = response.usage
    _record(CallRecord(
        model=model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        seconds=seconds,
        stop_reason=response.stop_reason,
    ))
    if response.stop_reason == "refusal":
        raise RefusalError(f"{model} refused the request")
    return response


def text_of(response) -> str:
    """Join the text blocks of a response (skips thinking and tool_use blocks)."""
    return "".join(block.text for block in response.content if block.type == "text").strip()


def complete_text(prompt: str, *, model: str, max_tokens: int = 8000) -> str:
    response = create_message(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)
    return text_of(response)


def complete_json(prompt: str, *, schema: dict, model: str, max_tokens: int = 8000) -> dict | None:
    """One call constrained to `schema`. Returns None if the reply isn't valid JSON."""
    response = create_message(
        model=model, messages=[{"role": "user", "content": prompt}], schema=schema, max_tokens=max_tokens
    )
    try:
        return json.loads(text_of(response))
    except json.JSONDecodeError:
        return None
