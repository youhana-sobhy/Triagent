"""Shared helpers for the eval scripts: loading data, saving results, printing tables."""

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from triagent import config

PARALLEL_WORKERS = 4


def load_jsonl(name: str, limit: int | None = None) -> list[dict]:
    path = config.DATA_DIR / name
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit]


def save_csv(rows: list[dict], name: str) -> Path:
    config.RESULTS_DIR.mkdir(exist_ok=True)
    path = config.RESULTS_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    return path


def save_summary(summary: dict, name: str) -> Path:
    """Save headline metrics as JSON, stamped with time and models, for the README tables."""
    config.RESULTS_DIR.mkdir(exist_ok=True)
    path = config.RESULTS_DIR / f"{name}.json"
    summary = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **summary}
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def parallel_map(fn, items: list, workers: int = PARALLEL_WORKERS) -> list:
    """Run fn over items in parallel, keeping the input order."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def table(rows: list[list], headers: list[str]) -> str:
    """Plain-text table for the terminal."""
    cells = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def pct(num: int, den: int) -> str:
    return f"{num}/{den} = {num / den:.0%}" if den else "n/a"
