"""Human-in-the-loop approvals for state-changing actions (restarts)."""

from approvals.store import ApprovalStore, InvalidTransition

__all__ = ["ApprovalStore", "InvalidTransition"]
