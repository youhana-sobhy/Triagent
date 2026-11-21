"""Structured trace logging: one JSON object per line in logs/runs.jsonl.

Every model call, retrieval, tool call and guardrail decision is an event tagged with the
run_id of the alert it belongs to, so a single bad answer can be reconstructed step by step:

    grep '"run_id": "3f9c..."' logs/runs.jsonl

Secrets are redacted before anything is written.
"""

import json
import re
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from triagent import config

# Patterns for things that must never reach a log file. Kept simple on purpose.
_SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer [REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED KEY]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)(\s*[=:]\s*)(?!\[REDACTED)[^\s,;\"']+"),
     r"\1\2[REDACTED]"),
]


def redact(value):
    """Recursively redact secrets in strings, lists and dicts."""
    if isinstance(value, str):
        for pattern, replacement in _SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


# The current run, set once per alert. ContextVar works across threads in parallel evals.
_run: ContextVar[dict | None] = ContextVar("triagent_run", default=None)
_write_lock = threading.Lock()


@contextmanager
def run_context(alert_id: str | None = None):
    """Everything logged inside this block shares one run_id."""
    token = _run.set({"run_id": uuid.uuid4().hex[:12], "alert_id": alert_id})
    try:
        yield _run.get()
    finally:
        _run.reset(token)


def current_run() -> dict:
    return _run.get() or {"run_id": None, "alert_id": None}


EVENT_DEFAULTS = {
    "model": None, "prompt_version": config.PROMPT_VERSION,
    "input_tokens": 0, "output_tokens": 0,
    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    "seconds": 0.0, "cost": 0.0, "tool_calls": [],
    "status": "ok", "error_type": None, "retries": 0,
    "guardrail": None, "output": None,
}


def log_event(step: str, path: Path | None = None, **fields) -> dict:
    """Append one event. step: classify | retrieve | agent | tool | final | guardrail | grader."""
    run = current_run()
    event = {
        "run_id": run["run_id"], "alert_id": run["alert_id"],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "step": step, "simulated": config.OFFLINE,
        **EVENT_DEFAULTS, **fields,
    }
    event = redact(event)
    path = path or config.LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, default=str)
    with _write_lock, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return event


def summarize_result(result, limit: int = 200) -> str:
    """Short, redacted string form of a tool result for the log."""
    text = json.dumps(result, default=str)
    return redact(text if len(text) <= limit else text[:limit] + "...")
