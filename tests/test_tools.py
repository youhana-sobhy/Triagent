import pytest

from triagent.tools import TOOL_DEFINITIONS, ApprovalQueue, RestartExecutor, StatusProvider, ToolRunner


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
    runner = ToolRunner()
    result, is_error = runner.run("propose_restart", {"server": "worker-04", "reason": "crash loop"})
    assert not is_error and result["status"] == "pending"
    assert [r.status for r in runner.approvals.requests] == ["pending"]


def test_executor_refuses_unapproved_restart():
    queue, executor = ApprovalQueue(), RestartExecutor()
    request = queue.propose("worker-04", "crash loop")
    with pytest.raises(PermissionError):
        executor.execute(request)
    assert executor.executed == []


def test_executor_runs_only_after_human_approval():
    queue, executor = ApprovalQueue(), RestartExecutor()
    request = queue.propose("worker-04", "crash loop")
    queue.approve(request.id, approver="on-call engineer")
    executor.execute(request)
    assert executor.executed == [request]


def test_approval_requires_a_named_human():
    queue = ApprovalQueue()
    request = queue.propose("worker-04", "crash loop")
    with pytest.raises(ValueError):
        queue.approve(request.id, approver="")


def test_agent_has_no_execute_tool():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {"get_server_status", "propose_restart"}


def test_tool_schemas_are_strict():
    for tool in TOOL_DEFINITIONS:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
