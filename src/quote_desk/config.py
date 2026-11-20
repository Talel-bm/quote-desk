"""Project-wide settings: file paths, random seed, and LLM provider choice.

Every other module imports from here instead of building paths or reading
environment variables itself.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Read .env (if present) into the environment. Variables already set in the
# shell win, so tests and Docker can override anything here.
load_dotenv()

# Repo root: src/quote_desk/config.py -> parents[2] is the project folder.
ROOT = Path(__file__).resolve().parents[2]

# Where generated data lives. Override with QUOTEDESK_DATA_DIR (e.g. in Docker).
DATA_DIR = Path(os.getenv("QUOTEDESK_DATA_DIR", ROOT / "data" / "generated"))
ERP_DB = DATA_DIR / "erp.sqlite"  # synthetic ERP, read-only after Foundation
APP_DB = DATA_DIR / "app.sqlite"  # approval inbox, feedback, quote state
FOUNDATION_DB = DATA_DIR / "foundation.sqlite"  # cleaned tables, datasets, audit, quarantine
QUALITY_REPORT = DATA_DIR / "quality_report.md"  # human-readable Foundation report
MODELS_DIR = DATA_DIR / "models"  # trained LightGBM / neighbors models

# One seed for every random generator, so runs are reproducible.
SEED = 42

# LLM provider switch: "gemini" or "ollama".
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


def ensure_data_dir() -> Path:
    """Create the data folder if it does not exist yet, and return it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
