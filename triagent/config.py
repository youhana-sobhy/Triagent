"""Paths, model choices and prices. Everything tunable lives here."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNBOOKS_DIR = DATA_DIR / "runbooks"
RESULTS_DIR = ROOT / "results"
CHROMA_DIR = ROOT / "chroma_db"

# The API key is read from .env at the project root (never committed).
load_dotenv(ROOT / ".env")

# --- Models -------------------------------------------------------------
# Generator: writes the triage answers. Override with TRIAGENT_MODEL.
GENERATOR_MODEL = os.getenv("TRIAGENT_MODEL", "claude-sonnet-5-5")
# Grader: scores explanation clarity. Must differ from the generator,
# because a model tends to rate its own writing too highly.
GRADER_MODEL = "claude-opus-5-5"
# Guard: cheap, fast model that screens alert text for prompt injection.
GUARD_MODEL = "claude-haiku-5-5"
# Small model used in the Stage 5 cost optimization.
SMALL_MODEL = "claude-haiku-5-5"

# --- Retrieval ----------------------------------------------------------
TOP_K = 3

# --- Reliability --------------------------------------------------------
REQUEST_TIMEOUT_S = 120     # per API request
MAX_RETRIES = 3             # SDK retries 429 / 5xx / connection errors with backoff
MAX_AGENT_TURNS = 6         # hard stop for the tool-use loop

# --- Prices (USD per 1M tokens), Anthropic API list prices, Nov 2026 ------
# (input, output, cache read). Cache writes cost 1.25x input.
PRICES = {
    "claude-opus-5-5":   (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5":  (0.10, 0.50, 0.01),
}
