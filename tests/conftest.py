import importlib

import pytest

from quote_desk import config


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Point config at a throwaway folder for one test, then restore it."""
    monkeypatch.setenv("QUOTEDESK_DATA_DIR", str(tmp_path / "data"))
    importlib.reload(config)
    yield tmp_path / "data"
    monkeypatch.delenv("QUOTEDESK_DATA_DIR")
    importlib.reload(config)
