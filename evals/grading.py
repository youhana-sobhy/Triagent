"""Code graders: deterministic checks for answers that have one right value.

Pure functions, no API calls, covered by tests/test_grading.py.
"""

from math import comb

SEVERITIES = {"critical", "warning", "info"}


def severity_match(got: str | None, expected: str) -> bool:
    """Exact match on a valid label."""
    return got in SEVERITIES and got == expected.lower()


def retrieval_hit(retrieved: list[str], expected: list[str], k: int) -> bool:
    """Any expected runbook in the top k results."""
    return any(r in retrieved[:k] for r in expected)


def citation_correct(cited: str | None, expected: list[str]) -> bool:
    """Cited one of the labeled runbooks, or 'none' when the label is empty."""
    return cited in expected if expected else cited == "none"


def citation_grounded(cited: str | None, retrieved: list[str]) -> bool:
    """Never cite a runbook that was not retrieved."""
    return cited == "none" or cited in retrieved


def diagnose(cited: str | None, expected: list[str], retrieved: list[str]) -> str:
    """Which layer failed: retrieval, or the model's use of good context?"""
    if citation_correct(cited, expected):
        return "ok"
    if expected and not retrieval_hit(retrieved, expected, len(retrieved)):
        return "retrieval failed"
    if expected:
        return "model ignored good context"
    return "cited a runbook when none fits"


def tool_call_grade(calls: list[dict], expected_tool: str | None, expected_server: str | None) -> str:
    """Grade the status lookups of one run.

    Returns 'correct', 'missing call', 'wrong server', 'guessed server' or 'unexpected call'.
    """
    status_calls = [c for c in calls if c["name"] == "get_server_status"]
    if expected_tool is None:
        return "correct" if not status_calls else "guessed server"
    if not status_calls:
        return "missing call"
    servers = [c["input"].get("server") for c in status_calls]
    return "correct" if servers[0] == expected_server else "wrong server"


def pass_at_k(n: int, c: int, k: int) -> float:
    """P(at least one of k samples passes), unbiased estimator from n trials with c passes."""
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """P(all k samples pass), estimated from n trials with c passes (pass^k)."""
    if c < k:
        return 0.0
    return comb(c, k) / comb(n, k)
