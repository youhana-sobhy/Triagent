"""Paths and settings. Tunable values live in config/*.yaml, not in code."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RUNBOOKS_DIR = DATA_DIR / "runbooks"
RESULTS_DIR = ROOT / "results"
CHROMA_DIR = ROOT / "chroma_db"
APPROVALS_DIR = ROOT / "approvals"

# The API key is read from .env at the project root (never committed).
load_dotenv(ROOT / ".env")


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8")) or {}


SETTINGS = _load("settings.yaml")
PRICES: dict[str, dict] = _load("prices.yaml").get("models", {})
THRESHOLDS: dict = _load("thresholds.yaml")

_models = SETTINGS["models"]
GENERATOR_MODEL = os.getenv("TRIAGENT_MODEL", _models["agent"])
CLASSIFY_MODEL = os.getenv("TRIAGENT_MODEL", _models["classify"])
GUARD_MODEL = _models["guard"]
GRADER_MODEL = _models["grader"]
SMALL_MODEL = _models["small"]

PROMPT_VERSION = SETTINGS["prompt_version"]
TOP_K = SETTINGS["retrieval"]["top_k"]

_rel = SETTINGS["reliability"]
REQUEST_TIMEOUT_S = _rel["request_timeout_s"]
SDK_MAX_RETRIES = _rel["sdk_max_retries"]
RETRY = _rel["retry"]
MAX_AGENT_TURNS = _rel["max_agent_turns"]

PROMPT_CACHING = os.getenv("TRIAGENT_PROMPT_CACHING", str(SETTINGS["optimization"]["prompt_caching"])).lower() in (
    "1", "true", "yes")

# Offline mode: a fake client returns simulated answers. Free, deterministic, used by CI and demos.
OFFLINE = os.getenv("TRIAGENT_OFFLINE", "0").lower() in ("1", "true", "yes")
LOG_PATH = ROOT / (SETTINGS["logging"]["offline_path"] if OFFLINE else SETTINGS["logging"]["path"])
if os.getenv("TRIAGENT_LOG_PATH"):
    LOG_PATH = Path(os.environ["TRIAGENT_LOG_PATH"])
