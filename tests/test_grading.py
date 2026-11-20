import json
from pathlib import Path

import pytest

from evals.grading import (citation_correct, citation_grounded, diagnose, pass_at_k, pass_hat_k,
                           retrieval_hit, severity_match, tool_call_grade)

DATA = Path(__file__).resolve().parent.parent / "data"


def test_severity_match_is_exact_and_validated():
    assert severity_match("critical", "critical")
    assert not severity_match("Critical", "critical")
    assert not severity_match("high", "high")
    assert not severity_match(None, "info")


def test_retrieval_hit_respects_k():
    assert retrieval_hit(["a", "b", "c"], ["c"], 3)
    assert not retrieval_hit(["a", "b", "c"], ["c"], 1)
    assert retrieval_hit(["a", "b"], ["x", "a"], 1)


def test_citation_rules():
    assert citation_correct("memory-leak", ["memory-leak", "service-down"])
    assert citation_correct("none", [])
    assert not citation_correct("high-cpu", [])
    assert citation_grounded("none", [])
    assert not citation_grounded("high-cpu", ["memory-leak"])


@pytest.mark.parametrize("cited, expected, retrieved, diagnosis", [
    ("a", ["a"], ["a", "b"], "ok"),
    ("b", ["x"], ["a", "b"], "retrieval failed"),
    ("b", ["a"], ["a", "b"], "model ignored good context"),
    ("a", [], ["a", "b"], "cited a runbook when none fits"),
])
def test_diagnose_names_the_failing_layer(cited, expected, retrieved, diagnosis):
    assert diagnose(cited, expected, retrieved) == diagnosis


def call(server):
    return {"name": "get_server_status", "input": {"server": server}}


def test_tool_call_grades():
    assert tool_call_grade([call("db-01")], "get_server_status", "db-01") == "correct"
    assert tool_call_grade([], "get_server_status", "db-01") == "missing call"
    assert tool_call_grade([call("db-02")], "get_server_status", "db-01") == "wrong server"
    assert tool_call_grade([call("db-02")], None, None) == "guessed server"
    assert tool_call_grade([], None, None) == "correct"


def test_pass_at_k_and_pass_hat_k():
    assert pass_at_k(3, 1, 3) == 1.0 and pass_hat_k(3, 1, 3) == 0.0
    assert pass_at_k(3, 3, 3) == 1.0 and pass_hat_k(3, 3, 3) == 1.0
    assert pass_at_k(3, 0, 3) == 0.0
    assert pass_hat_k(10, 9, 3) == pytest.approx(84 / 120)


def test_datasets_are_well_formed():
    runbooks = {p.stem for p in (DATA / "runbooks").glob("*.md")}
    for name in ("alerts.jsonl", "held_out.jsonl"):
        rows = [json.loads(l) for l in (DATA / name).read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len({r["id"] for r in rows}) == len(rows)
        for r in rows:
            assert r["expected"] in {"critical", "warning", "info"}
            assert set(r["expected_runbook"]) <= runbooks
    alerts = [json.loads(l) for l in (DATA / "alerts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(alerts) == 20 and sum(r["tricky"] for r in alerts) >= 5
