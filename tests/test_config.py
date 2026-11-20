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
