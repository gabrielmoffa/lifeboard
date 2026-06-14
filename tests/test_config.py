import json

import config


def test_load_config_merges_public_config_and_secrets(tmp_config_dir):
    (tmp_config_dir / "config.json").write_text(
        json.dumps({"theme": "hacker", "telegram_group_id": "-500"})
    )
    (tmp_config_dir / "secrets.json").write_text(
        json.dumps({"ai_api_key": "ai-secret", "finnhub_api_key": "market-secret"})
    )

    loaded = config.load_config()

    assert loaded["theme"] == "hacker"
    assert loaded["telegram_group_id"] == "-500"
    assert loaded["ai_api_key"] == "ai-secret"
    assert loaded["finnhub_api_key"] == "market-secret"


def test_load_config_keeps_legacy_secrets_from_config_json(tmp_config_dir):
    (tmp_config_dir / "config.json").write_text(
        json.dumps({"theme": "hacker", "ai_api_key": "legacy-secret"})
    )

    loaded = config.load_config()

    assert loaded["theme"] == "hacker"
    assert loaded["ai_api_key"] == "legacy-secret"


def test_save_config_writes_secrets_to_secrets_file(tmp_config_dir):
    config.save_config(
        {
            "theme": "hacker",
            "ai_api_key": "ai-secret",
            "finnhub_api_key": "market-secret",
            "telegram_group_id": "-500",
        }
    )

    public_config = json.loads((tmp_config_dir / "config.json").read_text())
    secrets = json.loads((tmp_config_dir / "secrets.json").read_text())

    assert public_config == {"theme": "hacker", "telegram_group_id": "-500"}
    assert secrets == {
        "ai_api_key": "ai-secret",
        "finnhub_api_key": "market-secret",
    }
