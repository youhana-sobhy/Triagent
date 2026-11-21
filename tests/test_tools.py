from approvals.store import ApprovalStore
from triagent.tools import TOOL_DEFINITIONS, StatusProvider, ToolRunner


def test_get_server_status_known_server():
    result, is_error = ToolRunner().run("get_server_status", {"server": "db-01"})
    assert not is_error and result["server"] == "db-01" and result["disk_used_pct"] == 95


def test_get_server_status_unknown_server_is_an_error_not_a_guess():
    result, is_error = ToolRunner().run("get_server_status", {"server": "db-99"})
    assert is_error and "unknown server" in result["error"]


def test_scenario_overrides():
    status = StatusProvider({"db-01": {"disk_used_pct": 12}})
    assert status.get("db-01")["disk_used_pct"] == 12


def test_propose_restart_only_files_a_pending_request():
    runner = ToolRunner(alert_id="a08")
    result, is_error = runner.run("propose_restart", {"server": "worker-04", "reason": "crash loop"})
    assert not is_error and result["status"] == "pending"
    assert [r.status for r in runner.approvals.list()] == ["pending"]


def test_retried_propose_restart_creates_exactly_one_request():
    runner = ToolRunner(approvals=ApprovalStore(), alert_id="a08")
    first, _ = runner.run("propose_restart", {"server": "worker-04", "reason": "crash loop"})
    second, _ = runner.run("propose_restart", {"server": "worker-04", "reason": "crash loop (retry)"})
    assert first["approval_request_id"] == second["approval_request_id"]
    assert second["duplicate"] is True
    assert len(runner.approvals.list()) == 1


def test_propose_restart_unknown_server_is_an_error():
    result, is_error = ToolRunner().run("propose_restart", {"server": "db-99", "reason": "x"})
    assert is_error


def test_agent_has_no_execute_tool():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {"get_server_status", "propose_restart"}


def test_tool_schemas_are_strict():
    for tool in TOOL_DEFINITIONS:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
