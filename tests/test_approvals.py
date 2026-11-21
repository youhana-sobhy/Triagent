import pytest

from approvals.store import ApprovalStore, InvalidTransition


@pytest.fixture
def store(tmp_path):
    return ApprovalStore(tmp_path)


def test_restart_is_never_executed_without_approval(store):
    store.propose("worker-04", "crash loop", alert_id="a08")
    executed = []
    store.execute_approved(executed.append)
    assert executed == []
    assert store.list()[0].status == "pending"


def test_rejected_request_is_never_executed(store):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    store.reject(request.request_id, reviewer="alice", note="not needed")
    executed = []
    store.execute_approved(executed.append)
    assert executed == [] and store.get(request.request_id).status == "rejected"
    with pytest.raises(InvalidTransition):
        store.approve(request.request_id, reviewer="bob")


def test_approving_twice_executes_once(store):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    store.approve(request.request_id, reviewer="alice")
    store.approve(request.request_id, reviewer="alice")       # double click
    executed = []
    store.execute_approved(executed.append)
    store.execute_approved(executed.append)                   # second executor run
    assert [r.request_id for r in executed] == [request.request_id]
    assert store.get(request.request_id).status == "executed"


def test_audit_log_shows_who_did_what_and_when(store):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    store.approve(request.request_id, reviewer="alice", note="checked logs")
    store.execute_approved()
    audit = store.audit_log(request.request_id)
    assert [e["action"] for e in audit] == ["proposed", "approved", "executed"]
    approved = audit[1]
    assert approved["actor"] == "alice" and approved["note"] == "checked logs" and approved["at"]


def test_audit_trail_is_append_only_on_disk(store, tmp_path):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    store.approve(request.request_id, reviewer="alice")
    lines_before = (tmp_path / "audit.jsonl").read_text().splitlines()
    store.execute_approved()
    lines_after = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert lines_after[:len(lines_before)] == lines_before and len(lines_after) == len(lines_before) + 1


def test_state_survives_a_restart_of_the_process(store, tmp_path):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    store.approve(request.request_id, reviewer="alice")
    reloaded = ApprovalStore(tmp_path)
    assert reloaded.get(request.request_id).status == "approved"
    assert len(reloaded.audit_log()) == 2


def test_propose_is_idempotent_per_server_and_alert(store):
    a, created_a = store.propose("worker-04", "crash loop", alert_id="a08")
    b, created_b = store.propose("worker-04", "crash loop again", alert_id="a08")
    c, created_c = store.propose("worker-04", "other alert", alert_id="a99")
    assert a.request_id == b.request_id and created_a and not created_b
    assert c.request_id != a.request_id and created_c


def test_review_requires_a_named_reviewer(store):
    request, _ = store.propose("worker-04", "crash loop", alert_id="a08")
    with pytest.raises(ValueError):
        store.approve(request.request_id, reviewer=" ")
