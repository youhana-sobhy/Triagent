import os
import sys
import tempfile
from pathlib import Path

# Tests never call the real API and never write to the real log file.
# These must be set before `triagent.config` is imported.
os.environ["TRIAGENT_OFFLINE"] = "1"
os.environ["TRIAGENT_LOG_PATH"] = str(Path(tempfile.gettempdir()) / "triagent_test_runs.jsonl")
os.environ.pop("TRIAGENT_FAKE_FAILURE_RATE", None)

# Make `triagent`, `evals` and `approvals` importable when running `pytest` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
