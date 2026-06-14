import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("config.CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr("config.SECRETS_FILE", str(tmp_path / "secrets.json"))
    monkeypatch.setattr("config.BOARD_FILE", str(tmp_path / "board.json"))
    monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
    # Also patch the copies imported into board_engine, otherwise
    # save_board / load_board still hit the real ~/.lifeboard/ paths.
    monkeypatch.setattr("lifeboard.board_engine.BOARD_FILE", str(tmp_path / "board.json"))
    monkeypatch.setattr("lifeboard.board_engine.BACKUP_FILE", str(tmp_path / "board.json.prev"))
    return tmp_path

@pytest.fixture
def sample_board():
    return {
        "theme": "hacker",
        "resolution": [2560, 1600],
        "widgets": [{
            "id": "test-widget",
            "description": "A test widget",
            "position": [10, 10],
            "size": [30, 20],
            "data": {"title": "Test"},
            "html_template": "<div>{{title}}</div>",
            "css": "",
        }],
    }
