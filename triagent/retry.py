"""Application-level retries: only for transient failures, with exponential backoff and jitter.

Retry:      429 rate limit, 5xx server errors, 529 overloaded, timeouts, connection errors.
Don't:      4xx client errors (bad request, auth, not found): retrying cannot fix them.
Bounded by: a maximum number of attempts AND a maximum total time.

State-changing actions must be idempotent before they may be retried (see approvals.store).
"""

import random
import time
from dataclasses import dataclass

import anthropic

from triagent import config

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass
class RetryPolicy:
    max_attempts: int = config.RETRY["max_attempts"]
    base_delay_s: float = config.RETRY["base_delay_s"]
    max_delay_s: float = config.RETRY["max_delay_s"]
    max_total_s: float = config.RETRY["max_total_s"]


class RetryError(RuntimeError):
    """All attempts failed. `last_error` is the final exception, `retries` how many retries ran."""

    def __init__(self, last_error: Exception, retries: int):
        super().__init__(f"gave up after {retries} retries: {type(last_error).__name__}: {last_error}")
        self.last_error = last_error
        self.retries = retries


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (anthropic.APIConnectionError, TimeoutError, ConnectionError)):
        return True   # includes anthropic.APITimeoutError
    status = getattr(exc, "status_code", None)
    return status in RETRYABLE_STATUS or (isinstance(status, int) and status >= 500)


def backoff_delay(attempt: int, policy: RetryPolicy, rng=random.random) -> float:
    """Exponential backoff with full jitter: random between 0 and base * 2^attempt (capped)."""
    return rng() * min(policy.max_delay_s, policy.base_delay_s * 2 ** attempt)


def call_with_retry(fn, *args, policy: RetryPolicy | None = None, sleep=time.sleep, rng=random.random,
                    clock=time.monotonic, **kwargs):
    """Call fn(*args, **kwargs). Returns (result, retries). Raises RetryError or the non-retryable error."""
    policy = policy or RetryPolicy()
    start = clock()
    retries = 0
    while True:
        try:
            return fn(*args, **kwargs), retries
        except Exception as exc:
            if not is_retryable(exc):
                exc.retries = retries   # so the caller can log how many retries happened before it
                raise
            delay = backoff_delay(retries, policy, rng)
            out_of_attempts = retries + 1 >= policy.max_attempts
            out_of_time = clock() - start + delay > policy.max_total_s
            if out_of_attempts or out_of_time:
                raise RetryError(exc, retries) from exc
            sleep(delay)
            retries += 1
