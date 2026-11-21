"""Approval requests with a full audit trail.

Lifecycle:   pending --approve--> approved --execute--> executed
             pending --reject---> rejected                (never executed)

Rules enforced here, in code, not in a prompt:
  - The agent can only call `propose`. Approving and executing are separate, human-driven steps.
  - `propose` is idempotent: the same (server, alert_id) always maps to one request, so a retried
    agent step can never file a duplicate.
  - `execute_approved` only runs requests whose status is `approved`, then marks them `executed`,
    so each request runs at most once (approving twice still executes once).
  - Every status change is appended to an audit log that is never rewritten.

Storage: `requests.jsonl` holds the current state of each request; `audit.jsonl` is append-only.
With `directory=None` everything stays in memory (used by evals and tests).
"""

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InvalidTransition(ValueError):
    """The requested status change is not allowed (for example approving a rejected request)."""


@dataclass
class ApprovalRequest:
    request_id: str
    idempotency_key: str
    server: str
    reason: str
    alert_id: str | None
    requested_at: str
    status: str = "pending"            # pending | approved | rejected | executed
    reviewer: str | None = None
    reviewed_at: str | None = None
    note: str | None = None
    executed_at: str | None = None


def idempotency_key(server: str, alert_id: str | None) -> str:
    return hashlib.sha256(f"{server}|{alert_id}".encode()).hexdigest()[:16]


class ApprovalStore:
    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory else None
        self._lock = threading.RLock()
        self._requests: dict[str, ApprovalRequest] = {}
        self._audit: list[dict] = []
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._load()

    # --- persistence ---------------------------------------------------------
    @property
    def requests_path(self) -> Path | None:
        return self.directory / "requests.jsonl" if self.directory else None

    @property
    def audit_path(self) -> Path | None:
        return self.directory / "audit.jsonl" if self.directory else None

    def _load(self) -> None:
        if self.requests_path.exists():
            for line in self.requests_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    req = ApprovalRequest(**json.loads(line))
                    self._requests[req.request_id] = req
        if self.audit_path.exists():
            self._audit = [json.loads(l) for l in self.audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _save(self) -> None:
        if not self.directory:
            return
        tmp = self.requests_path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(asdict(r)) + "\n" for r in self._requests.values()), encoding="utf-8")
        tmp.replace(self.requests_path)   # atomic swap: a crash never leaves a half-written file

    def _audit_event(self, request: ApprovalRequest, action: str, actor: str, note: str | None = None) -> None:
        event = {"at": _now(), "request_id": request.request_id, "action": action, "actor": actor,
                 "server": request.server, "status": request.status, "note": note}
        self._audit.append(event)
        if self.directory:
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")

    # --- API -----------------------------------------------------------------
    def propose(self, server: str, reason: str, alert_id: str | None = None, actor: str = "agent") -> tuple[ApprovalRequest, bool]:
        """File a pending request. Returns (request, created). Duplicates return the existing one."""
        key = idempotency_key(server, alert_id)
        with self._lock:
            existing = next((r for r in self._requests.values() if r.idempotency_key == key), None)
            if existing:
                return existing, False
            request = ApprovalRequest(request_id=f"req-{key[:8]}", idempotency_key=key, server=server,
                                      reason=reason, alert_id=alert_id, requested_at=_now())
            self._requests[request.request_id] = request
            self._save()
            self._audit_event(request, "proposed", actor, reason)
            return request, True

    def get(self, request_id: str) -> ApprovalRequest:
        try:
            return self._requests[request_id]
        except KeyError:
            raise KeyError(f"no approval request {request_id!r}") from None

    def list(self, status: str | None = None) -> list[ApprovalRequest]:
        return [r for r in self._requests.values() if status is None or r.status == status]

    def _review(self, request_id: str, decision: str, reviewer: str, note: str | None) -> ApprovalRequest:
        if not reviewer or not reviewer.strip():
            raise ValueError("a reviewer name is required")
        with self._lock:
            request = self.get(request_id)
            if request.status == decision:
                return request                       # repeated click: no change, no duplicate audit
            if request.status != "pending":
                raise InvalidTransition(f"{request_id} is {request.status}; only pending requests can be reviewed")
            request.status, request.reviewer, request.reviewed_at, request.note = decision, reviewer, _now(), note
            self._save()
            self._audit_event(request, decision, reviewer, note)
            return request

    def approve(self, request_id: str, reviewer: str, note: str | None = None) -> ApprovalRequest:
        return self._review(request_id, "approved", reviewer, note)

    def reject(self, request_id: str, reviewer: str, note: str | None = None) -> ApprovalRequest:
        return self._review(request_id, "rejected", reviewer, note)

    def execute_approved(self, executor=None, actor: str = "executor") -> list[ApprovalRequest]:
        """Run every approved request exactly once. `executor(request)` performs the action.

        The default executor only records the action (this project never restarts real servers).
        """
        executor = executor or (lambda request: None)
        done = []
        with self._lock:
            for request in self.list("approved"):
                executor(request)
                request.status, request.executed_at = "executed", _now()
                self._save()
                self._audit_event(request, "executed", actor)
                done.append(request)
        return done

    def audit_log(self, request_id: str | None = None) -> list[dict]:
        return [e for e in self._audit if request_id is None or e["request_id"] == request_id]
