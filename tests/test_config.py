import pytest
from pydantic import ValidationError

from quote_desk import config


def test_database_paths_live_in_data_dir():
    assert config.ERP_DB.parent == config.DATA_DIR
    assert config.APP_DB.parent == config.DATA_DIR
    assert config.MODELS_DIR.parent == config.DATA_DIR


def test_data_dir_can_be_overridden(tmp_data_dir):
    assert config.DATA_DIR == tmp_data_dir


def test_ensure_data_dir_creates_folder(tmp_data_dir):
    assert not tmp_data_dir.exists()
    assert config.ensure_data_dir() == tmp_data_dir
    assert tmp_data_dir.is_dir()


def test_default_provider_is_the_keyless_fake(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert config.Settings(_env_file=None).llm_provider == "fake"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_api_key_is_hidden_when_printed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-123")
    settings = config.Settings(_env_file=None)
    assert "secret-123" not in repr(settings)
    assert settings.gemini_api_key.get_secret_value() == "secret-123"
