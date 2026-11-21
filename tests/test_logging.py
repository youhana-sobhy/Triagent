import json

from triagent.logging_utils import log_event, redact, run_context


def test_redact_fake_api_key_and_password():
    text = "auth failed: key=sk-ant-api03-FAKEFAKEFAKE1234567890 password=hunter2 token: abc.def.ghi"
    clean = redact(text)
    assert "sk-ant-api03" not in clean and "hunter2" not in clean and "abc.def.ghi" not in clean
    assert "[REDACTED]" in clean


def test_redact_walks_nested_structures():
    data = {"output": {"explanation": "found AKIAABCDEFGHIJKLMNOP in env"}, "calls": ["Bearer abcdefghijklmnop1234"]}
    clean = redact(data)
    assert "AKIA" not in json.dumps(clean) and "abcdefghijklmnop1234" not in json.dumps(clean)


def test_redact_leaves_normal_text_alone():
    text = "db-01: disk usage 95% on /var/lib/postgresql"
    assert redact(text) == text


def test_events_share_a_run_id_and_are_redacted(tmp_path):
    path = tmp_path / "runs.jsonl"
    with run_context("a01") as run:
        log_event("guardrail", path=path, guardrail="passed")
        log_event("agent", path=path, output={"explanation": "key sk-ant-FAKE1234567890abcd"})
        log_event("final", path=path, output={"severity": "critical"})
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [e["step"] for e in events] == ["guardrail", "agent", "final"]
    assert {e["run_id"] for e in events} == {run["run_id"]} and events[0]["alert_id"] == "a01"
    assert "sk-ant-FAKE" not in path.read_text()
    for field in ("timestamp", "model", "prompt_version", "input_tokens", "output_tokens",
                  "cache_creation_input_tokens", "cache_read_input_tokens", "seconds", "cost",
                  "tool_calls", "status", "error_type", "retries", "guardrail"):
        assert field in events[0]
