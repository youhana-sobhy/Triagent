"""Degraded mode: a rule-based triage used when the model is unavailable.

It is deliberately simple (keywords and numeric thresholds from the labeling guide), so the
system still returns something useful instead of crashing, and always flags it for a human.
Its accuracy is measured on the same dataset: python -m evals.fallback_baseline
"""

import re

# Keyword -> runbook, used only if that runbook was actually retrieved (keeps the citation grounded).
RUNBOOK_KEYWORDS = {
    "database-disk-full": ["disk", "postgres", "/var/lib", "wal"],
    "high-cpu": ["cpu", "load average"],
    "certificate-expiring": ["certificate", "tls", "ssl", "cert"],
    "memory-leak": ["memory", "oom", "heap"],
    "service-down": ["5xx", "503", "crash", "not running", "health check", "down", "timing out"],
}

INFO_MARKERS = ["resolved", "completed successfully", "test alert", "health checks passing",
                "finished", "back to"]
CRITICAL_MARKERS = ["crash loop", "not running", "oom", "expired", "5xx", "503", "failing",
                    "timing out", "users reporting", "security errors"]


def _max_percent(text: str) -> float | None:
    values = [float(v) for v in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", text)]
    return max(values) if values else None


def _days_left(text: str) -> int | None:
    match = re.search(r"expires? in (\d+) days?", text)
    return int(match.group(1)) if match else None


def rule_based_severity(alert: str) -> tuple[str, str]:
    """Returns (severity, reason)."""
    text = alert.lower().strip()
    if not text:
        return "info", "the alert is empty"
    if any(m in text for m in INFO_MARKERS):
        return "info", "the alert reports success, recovery or a test"
    days = _days_left(text)
    if days is not None:
        return ("warning", f"certificate expires in {days} days") if days <= 7 else (
            "info", f"certificate expires in {days} days")
    pct = _max_percent(text)
    if any(m in text for m in CRITICAL_MARKERS):
        return "critical", "the alert contains a sign of user impact or failure"
    if pct is not None and pct >= 90 and "error" not in text:
        return "critical", f"a metric is at {pct:.0f}%"
    if pct is not None and pct >= 75:
        return "warning", f"a metric is at {pct:.0f}%"
    if any(w in text for w in ["queue", "delayed", "increasing", "growing", "grew"]):
        return "warning", "something is degrading"
    return "info", "no clear sign of a problem"


def rule_based_runbook(alert: str, retrieved: list[str]) -> str:
    text = alert.lower()
    for runbook, words in RUNBOOK_KEYWORDS.items():
        if runbook in retrieved and any(w in text for w in words):
            return runbook
    return "none"


def rule_based_triage(alert: str, retrieved: list[str]) -> dict:
    """A complete answer in the same shape as the model's, marked as degraded."""
    severity, reason = rule_based_severity(alert)
    runbook = rule_based_runbook(alert, retrieved)
    return {
        "severity": severity,
        "explanation": f"AI triage was unavailable; rule-based fallback used: {reason}.",
        "recommended_action": (f"A human should review this alert using the '{runbook}' runbook."
                               if runbook != "none" else "A human should review this alert."),
        "runbook_cited": runbook,
        "needs_approval": False,
    }
