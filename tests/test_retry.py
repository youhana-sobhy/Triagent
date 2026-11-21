import pytest

from triagent.retry import RetryError, RetryPolicy, backoff_delay, call_with_retry, is_retryable


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class Flaky:
    """Raises the given errors in order, then returns 'ok'."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


FAST = RetryPolicy(max_attempts=4, base_delay_s=1, max_delay_s=8, max_total_s=60)
no_sleep = lambda s: None


@pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
def test_transient_errors_are_retryable(status):
    assert is_retryable(StatusError(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retryable(status):
    assert not is_retryable(StatusError(status))


def test_timeouts_and_connection_errors_are_retryable():
    assert is_retryable(TimeoutError()) and is_retryable(ConnectionError())


def test_429_then_success_retries_once():
    fn = Flaky(StatusError(429))
    result, retries = call_with_retry(fn, policy=FAST, sleep=no_sleep)
    assert result == "ok" and retries == 1 and fn.calls == 2


def test_5xx_is_retried():
    fn = Flaky(StatusError(503), StatusError(500))
    assert call_with_retry(fn, policy=FAST, sleep=no_sleep) == ("ok", 2)


def test_400_is_not_retried():
    fn = Flaky(StatusError(400))
    with pytest.raises(StatusError):
        call_with_retry(fn, policy=FAST, sleep=no_sleep)
    assert fn.calls == 1


def test_stops_after_max_attempts():
    fn = Flaky(*[StatusError(529)] * 10)
    with pytest.raises(RetryError) as exc:
        call_with_retry(fn, policy=FAST, sleep=no_sleep)
    assert fn.calls == FAST.max_attempts and exc.value.retries == FAST.max_attempts - 1


def test_stops_when_total_time_budget_is_spent():
    now = [0.0]
    fn = Flaky(*[StatusError(529)] * 10)

    def sleep(seconds):
        now[0] += seconds

    policy = RetryPolicy(max_attempts=100, base_delay_s=4, max_delay_s=4, max_total_s=10)
    with pytest.raises(RetryError):
        call_with_retry(fn, policy=policy, sleep=sleep, rng=lambda: 1.0, clock=lambda: now[0])
    assert now[0] <= 10


def test_backoff_grows_exponentially_and_is_capped():
    full = lambda: 1.0
    assert [backoff_delay(a, FAST, full) for a in range(5)] == [1, 2, 4, 8, 8]
    assert backoff_delay(3, FAST, lambda: 0.25) == 2   # jitter scales the delay down randomly
