"""Review restart requests from the command line.

Usage:
    python -m approvals.review list                 # pending requests
    python -m approvals.review list --all
    python -m approvals.review approve req-1a2b3c4d --reviewer "Youhana" --note "checked logs"
    python -m approvals.review reject  req-1a2b3c4d --reviewer "Youhana" --note "not needed"
    python -m approvals.review execute              # run approved requests (fake executor)
    python -m approvals.review audit [request_id]
"""

import argparse
import sys

from approvals.store import ApprovalStore, InvalidTransition
from triagent import config


def fake_executor(request) -> None:
    print(f"  [fake executor] would restart {request.server} now (request {request.request_id})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review restart requests proposed by Triagent.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("request_id")
        p.add_argument("--reviewer", required=True, help="your name, recorded in the audit trail")
        p.add_argument("--note")
    sub.add_parser("execute")
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("request_id", nargs="?")
    args = parser.parse_args()

    store = ApprovalStore(config.APPROVALS_DIR)
    try:
        if args.command == "list":
            requests = store.list(None if args.all else "pending")
            if not requests:
                print("No requests." if args.all else "No pending requests.")
            for r in requests:
                print(f"{r.request_id}  {r.status:<9} {r.server:<10} alert={r.alert_id}  {r.requested_at}  {r.reason}")
        elif args.command in ("approve", "reject"):
            r = getattr(store, args.command)(args.request_id, args.reviewer, args.note)
            print(f"{r.request_id} is now {r.status} (by {r.reviewer} at {r.reviewed_at})")
        elif args.command == "execute":
            done = store.execute_approved(fake_executor)
            print(f"Executed {len(done)} approved request(s).")
        elif args.command == "audit":
            for e in store.audit_log(args.request_id):
                print(f"{e['at']}  {e['request_id']}  {e['action']:<9} by {e['actor']:<10} {e['note'] or ''}")
    except (KeyError, ValueError, InvalidTransition) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
