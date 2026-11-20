"""Run the whole eval suite (the regression check to run after every change).

Usage:
    python -m evals.run_evals            # everything (costs a few dollars of API usage)
    python -m evals.run_evals --free     # only checks with no API calls: unit tests + retrieval
"""

import argparse
import subprocess
import sys

FREE = [
    ["-m", "pytest", "-q"],
    ["-m", "evals.stage2_rag", "--retrieval-only"],
]
PAID = [
    ["-m", "evals.stage1_classify", "--prompt", "v1"],
    ["-m", "evals.stage1_classify", "--prompt", "v2"],
    ["-m", "evals.stage1_classify", "--prompt", "v2", "--dataset", "held_out.jsonl"],
    ["-m", "evals.stage2_rag"],
    ["-m", "evals.stage3_tools"],
    ["-m", "evals.stage4_guardrails"],
    ["-m", "evals.stage5_cost"],
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--free", action="store_true", help="skip everything that calls the API")
    args = parser.parse_args()
    # The full stage 2 eval already includes the retrieval part, so it replaces FREE[1].
    steps = FREE if args.free else [FREE[0]] + PAID
    failed = []
    for step in steps:
        print(f"\n{'=' * 70}\n$ python {' '.join(step)}\n{'=' * 70}", flush=True)
        if subprocess.run([sys.executable, *step]).returncode != 0:
            failed.append(" ".join(step))
    print(f"\n{len(steps) - len(failed)}/{len(steps)} steps succeeded")
    for f in failed:
        print(f"  FAILED: {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
