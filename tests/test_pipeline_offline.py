"""End-to-end pipeline tests with the fake client: retries, fallback, logging, approvals. No API calls."""

import json

import pytest

from approvals.store import ApprovalStore
from triagent import config, llm
from triagent.agent import triage
from triagent.fake_llm import FakeAnthropic, FakeAPIError
from triagent.fallback import rule_based_severity
from triagent.retry import RetryPolicy


class ScriptedClient:
    """Fails with the given errors first, then behaves like the normal fake client."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.inner = FakeAnthropic(failure_rate=0)
        self.messages = self

    def create(self, **params):
        if self.errors:
            raise self.errors.pop(0)
        return self.inner.messages.create(**params)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr("triagent.retry.time.sleep", lambda s: None)   # no real waiting in tests
    yield
    llm.set_client(None)


def events_for(run_id):
    lines = config.LOG_PATH.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["run_id"] == run_id]


def test_offline_pipeline_produces_answer_and_full_trace():
    llm.set_client(FakeAnthropic(failure_rate=0))
    result = triage("db-01: disk usage 95% on /var/lib/postgresql", alert_id="a01")
    assert result.ok and result.answer["severity"] == "critical"
    assert [c["name"] for c in result.tool_calls] == ["get_server_status"]
    steps = [e["step"] for e in events_for(result.run_id)]
    assert steps[0] == "guardrail" and steps[-1] == "final"
    assert {"retrieve", "agent", "tool"} <= set(steps)
    final = events_for(result.run_id)[-1]
    assert final["output"]["severity"] == "critical" and final["guardrail"] == "passed"


def test_429_then_success_is_retried_and_logged():
    llm.set_client(ScriptedClient(FakeAPIError(429)))
    result = triage("db-01: disk usage 95% on /var/lib/postgresql", alert_id="a01")
    assert result.ok and result.usage.retries == 1
    assert any(e["retries"] == 1 for e in events_for(result.run_id) if e["step"] == "guardrail")


def test_400_is_not_retried_and_degrades():
    client = ScriptedClient(FakeAPIError(400))
    llm.set_client(client)
    result = triage("db-01: disk usage 95% on /var/lib/postgresql", alert_id="a01")
    assert result.degraded and result.usage.retries == 0


def test_total_outage_returns_degraded_fallback_not_an_exception():
    llm.set_client(FakeAnthropic(failure_rate=1.0))
    result = triage("worker-04: process 'payment-worker' not running (crash loop)", alert_id="a08")
    assert result.degraded and not result.ok
    assert result.answer["severity"] == "critical"
    assert "unavailable" in result.answer["explanation"]
    assert result.needs_review and result.final_output()["needs_review"] is True
    assert events_for(result.run_id)[-1]["status"] == "degraded"


def test_secret_in_alert_never_reaches_the_log():
    llm.set_client(FakeAnthropic(failure_rate=0))
    result = triage("db-01: connection refused, password=hunter2 rejected", alert_id="n09")
    assert "hunter2" not in json.dumps(events_for(result.run_id))


def test_agent_restart_proposal_waits_for_a_human():
    store = ApprovalStore()
    store.propose("worker-04", "crash loop", alert_id="a08")
    assert store.execute_approved() == []


@pytest.mark.parametrize("alert, expected", [
    ("", "info"),
    ("RESOLVED: web-03 CPU back to 35%", "info"),
    ("db-01: disk usage 95% on /var/lib/postgresql", "critical"),
    ("CPU 78% on web-03 for 5 min", "warning"),
    ("web-01: TLS certificate expires in 3 days", "warning"),
    ("api-gw: TLS certificate expires in 21 days", "info"),
])
def test_rule_based_fallback_severity(alert, expected):
    assert rule_based_severity(alert)[0] == expected
