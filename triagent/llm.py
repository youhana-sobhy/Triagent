"""Thin wrapper around the Anthropic Messages API.

Every call goes through `create_message`, which:
  - retries transient failures (triagent/retry.py) and counts the retries,
  - times the call with a monotonic clock and reads token usage from the response,
  - computes cost from config/prices.yaml,
  - writes one structured log event (triagent/logging_utils.py),
  - records usage for the eval scripts (track_usage).
"""

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import anthropic

from triagent import config
from triagent.logging_utils import log_event
from triagent.retry import RetryError, call_with_retry


class RefusalError(RuntimeError):
    """The model declined the request (stop_reason == "refusal").

    No automatic fallback to another model on purpose: in an eval, a refusal must
    count as a failure of the model under test, not be hidden by a different model.
    """


class LLMUnavailable(RuntimeError):
    """The model could not be reached after retries (or returned a client error)."""

    def __init__(self, error: Exception, retries: int):
        super().__init__(f"{type(error).__name__}: {error}")
        self.error, self.retries = error, retries


def price_of(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    p = config.PRICES.get(model)
    if not p:
        return 0.0   # unknown model or prices not filled in config/prices.yaml
    return (input_tokens * p["input"] + output_tokens * p["output"]
            + cache_read * p["cache_read"] + cache_write * p["cache_write"]) / 1_000_000


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    seconds: float
    stop_reason: str
    retries: int = 0

    @property
    def cost(self) -> float:
        return price_of(self.model, self.input_tokens, self.output_tokens,
                        self.cache_read_tokens, self.cache_write_tokens)


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

    @property
    def retries(self) -> int:
        return sum(c.retries for c in self.calls)


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


_client = None
_client_lock = threading.Lock()


def client():
    global _client
    with _client_lock:
        if _client is None:
            if config.OFFLINE:
                from triagent.fake_llm import FakeAnthropic
                _client = FakeAnthropic()
            else:
                _client = anthropic.Anthropic(timeout=config.REQUEST_TIMEOUT_S, max_retries=config.SDK_MAX_RETRIES)
    return _client


def set_client(new_client) -> None:
    """Swap the client (used by tests to inject failures)."""
    global _client
    _client = new_client


def create_message(
    *,
    model: str,
    messages: list[dict],
    step: str = "agent",
    system: str | None = None,
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
    cache_static_prefix: bool = False,
    log_fields: dict | None = None,
):
    """One Messages API call with retries, logging and usage tracking. Returns the raw response.

    cache_static_prefix: mark the system prompt as cacheable. Render order is tools -> system ->
    messages, so the cached prefix covers the tool definitions and the system prompt; everything
    that changes per alert (alert text, retrieved runbooks) comes after it, in `messages`.
    """
    params: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        params["system"] = ([{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                            if cache_static_prefix else system)
    if tools:
        params["tools"] = tools
    if schema:
        # Structured output: the final text is guaranteed to match this JSON schema.
        params["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

    start = time.monotonic()
    try:
        response, retries = call_with_retry(client().messages.create, **params)
    except Exception as exc:
        retries = exc.retries if isinstance(exc, RetryError) else getattr(exc, "retries", 0)
        error = exc.last_error if isinstance(exc, RetryError) else exc
        log_event(step, model=model, seconds=round(time.monotonic() - start, 3), status="error",
                  error_type=type(error).__name__, retries=retries, **(log_fields or {}))
        raise LLMUnavailable(error, retries) from exc
    seconds = time.monotonic() - start

    u = response.usage
    record = CallRecord(
        model=model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        seconds=seconds,
        stop_reason=response.stop_reason,
        retries=retries,
    )
    _record(record)
    refused = response.stop_reason == "refusal"
    log_event(step, model=model, input_tokens=record.input_tokens, output_tokens=record.output_tokens,
              cache_creation_input_tokens=record.cache_write_tokens,
              cache_read_input_tokens=record.cache_read_tokens,
              seconds=round(seconds, 3), cost=round(record.cost, 6), retries=retries,
              status="error" if refused else "ok", error_type="refusal" if refused else None,
              stop_reason=response.stop_reason, **(log_fields or {}))
    if refused:
        raise RefusalError(f"{model} refused the request")
    return response


def text_of(response) -> str:
    """Join the text blocks of a response (skips thinking and tool_use blocks)."""
    return "".join(block.text for block in response.content if block.type == "text").strip()


def complete_text(prompt: str, *, model: str, step: str = "grader", max_tokens: int = 8000) -> str:
    response = create_message(model=model, step=step, messages=[{"role": "user", "content": prompt}],
                              max_tokens=max_tokens)
    return text_of(response)


def complete_json(prompt: str, *, schema: dict, model: str, step: str = "classify",
                  max_tokens: int = 8000) -> dict | None:
    """One call constrained to `schema`. Returns None if the reply isn't valid JSON."""
    response = create_message(model=model, step=step, messages=[{"role": "user", "content": prompt}],
                              schema=schema, max_tokens=max_tokens)
    try:
        return json.loads(text_of(response))
    except json.JSONDecodeError:
        return None
