"""Project-wide settings: file paths, random seed, and LLM provider choice.

Every other module imports from here instead of building paths or reading
environment variables itself. Values come from the environment or `.env`
(pydantic-settings validates their types); the module-level names below are
what the rest of the code uses.
"""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: src/quote_desk/config.py -> parents[2] is the project folder.
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed settings read from environment variables (or `.env`).

    Shell variables win over `.env`, so tests and Docker can override anything.
    """

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    quotedesk_data_dir: Path = ROOT / "data" / "generated"
    llm_provider: Literal["gemini", "ollama", "fake"] = "fake"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-4-hydrogen"
    ollama_model: str = "qwen2.5:3b"


settings = Settings()

# Where generated data lives. Override with QUOTEDESK_DATA_DIR (e.g. in Docker).
DATA_DIR = settings.quotedesk_data_dir
ERP_DB = DATA_DIR / "erp.sqlite"  # synthetic ERP, read-only after Foundation
APP_DB = DATA_DIR / "app.sqlite"  # event log, inbox, outbox, jobs
FOUNDATION_DB = DATA_DIR / "foundation.sqlite"  # cleaned tables, datasets, audit, quarantine
QUALITY_REPORT = DATA_DIR / "quality_report.md"  # human-readable Foundation report
MODELS_DIR = DATA_DIR / "models"  # trained models

# One seed for every random generator, so runs are reproducible.
SEED = 42

# LLM provider switch: "fake" (scripted, no key needed), "gemini" or "ollama".
LLM_PROVIDER = settings.llm_provider
GEMINI_API_KEY = settings.gemini_api_key  # SecretStr: .get_secret_value() to use it
GEMINI_MODEL = settings.gemini_model
OLLAMA_MODEL = settings.ollama_model


def ensure_data_dir() -> Path:
    """Create the data folder if it does not exist yet, and return it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
