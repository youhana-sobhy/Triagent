"""Tools the agent may call, and the human approval gate for restarts.

- get_server_status(server): fake, hard-coded monitoring data.
- propose_restart(server, reason): only files an approval request. It never restarts anything.

The agent has no access to RestartExecutor. A restart can only run after a human
approves the request, and the executor refuses anything that is not approved.
"""

import copy
import itertools
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Current state of each known server (fake data for the project).
# Eval cases can override a server's status to match their scenario.
DEFAULT_STATUS: dict[str, dict] = {
    "db-01": {"role": "postgres primary", "state": "up", "disk_used_pct": 95,
              "disk_growth_pct_per_hour": 1.0, "cpu_pct": 35, "memory_pct": 61},
    "db-02": {"role": "postgres replica", "state": "up", "disk_used_pct": 71,
              "disk_growth_pct_per_day": 0.5, "cpu_pct": 22, "memory_pct": 55},
    "web-01": {"role": "web frontend", "state": "up", "cpu_pct": 31, "http_5xx_rate_pct": 0.1,
               "tls_cert_days_left": 3},
    "web-02": {"role": "web frontend", "state": "up", "cpu_pct": 28, "http_5xx_rate_pct": 0.2,
               "tls_cert_days_left": 0, "tls_cert_expired": True},
    "web-03": {"role": "web frontend", "state": "up", "cpu_pct": 100, "cpu_high_for_min": 30,
               "p99_latency_ms": 8000},
    "api-gw": {"role": "api gateway", "state": "degraded", "http_5xx_rate_pct": 42,
               "health_check": "failing"},
    "cache-02": {"role": "redis cache", "state": "up", "memory_pct": 82,
                 "memory_growth_pct_per_hour": 2.0, "maxmemory_policy": "noeviction"},
    "worker-04": {"role": "payment worker host", "state": "up", "services": {
        "payment-worker": {"state": "crash_loop", "restarts_last_10_min": 5}}},
    "auth-01": {"role": "auth service", "state": "up", "memory_pct": 91, "oom_kills_last_hour": 2},
    "mail-01": {"role": "smtp relay", "state": "up", "smtp_queue_length": 1200, "smtp_queue_normal_max": 100},
}


class StatusProvider:
    """Answers get_server_status from DEFAULT_STATUS plus per-scenario overrides."""

    def __init__(self, overrides: dict[str, dict] | None = None):
        self._status = copy.deepcopy(DEFAULT_STATUS)
        for server, status in (overrides or {}).items():
            self._status[server] = status

    def get(self, server: str) -> dict:
        if server not in self._status:
            return {"error": f"unknown server '{server}'. Use the exact server name from the alert."}
        return {"server": server, **self._status[server]}

    def known(self, server: str) -> bool:
        return server in self._status


@dataclass
class ApprovalRequest:
    id: int
    server: str
    reason: str
    created_at: str
    status: str = "pending"          # pending -> approved | rejected
    approved_by: str | None = None


class ApprovalQueue:
    """Where proposed restarts wait for a human."""

    _ids = itertools.count(1)

    def __init__(self):
        self.requests: list[ApprovalRequest] = []
        self._lock = threading.Lock()

    def propose(self, server: str, reason: str) -> ApprovalRequest:
        with self._lock:
            request = ApprovalRequest(id=next(self._ids), server=server, reason=reason,
                                      created_at=datetime.now(timezone.utc).isoformat())
            self.requests.append(request)
            return request

    def approve(self, request_id: int, approver: str) -> ApprovalRequest:
        """Called by a human, never by the agent."""
        if not approver:
            raise ValueError("an approver name is required")
        request = next(r for r in self.requests if r.id == request_id)
        request.status, request.approved_by = "approved", approver
        return request


class RestartExecutor:
    """The only code path that could restart a server. Not exposed to the agent."""

    def __init__(self):
        self.executed: list[ApprovalRequest] = []

    def execute(self, request: ApprovalRequest) -> None:
        if request.status != "approved" or not request.approved_by:
            raise PermissionError(f"restart of {request.server} is not approved by a human")
        self.executed.append(request)   # a real system would call the orchestrator here


# Tool definitions sent to the model. strict=True guarantees inputs match the schema.
TOOL_DEFINITIONS = [
    {
        "name": "get_server_status",
        "description": (
            "Get the current monitoring data for one server: state, CPU, memory, disk, error rates, "
            "and service health. Use the exact server name as it appears in the alert (for example "
            "'db-01'). Do not call it if the alert names no server, and never guess a name."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Exact server name, e.g. db-01"}},
            "required": ["server"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_restart",
        "description": (
            "File a request for a human to approve restarting a service on a server. This does NOT "
            "restart anything; a human must approve it. Only propose a restart when the cited runbook "
            "recommends one for this situation (a stuck, crash-looping, runaway or leaking service)."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Exact server name, e.g. worker-04"},
                "reason": {"type": "string", "description": "One sentence: why a restart is needed"},
            },
            "required": ["server", "reason"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class ToolRunner:
    """Executes the agent's tool calls against the fake backends."""
    status: StatusProvider = field(default_factory=StatusProvider)
    approvals: ApprovalQueue = field(default_factory=ApprovalQueue)

    def run(self, name: str, tool_input: dict) -> tuple[dict, bool]:
        """Returns (result, is_error)."""
        if name == "get_server_status":
            result = self.status.get(tool_input["server"])
            return result, "error" in result
        if name == "propose_restart":
            server = tool_input["server"]
            if not self.status.known(server):
                return {"error": f"unknown server '{server}'"}, True
            request = self.approvals.propose(server, tool_input["reason"])
            return {"approval_request_id": request.id, "status": request.status,
                    "note": "Restart NOT executed. Waiting for human approval."}, False
        return {"error": f"unknown tool '{name}'"}, True
