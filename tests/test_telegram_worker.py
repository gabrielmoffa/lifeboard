from unittest.mock import patch

from lifeboard.telegram_worker import TelegramWorker, _read_state, _write_state


TEST_GROUP_ID = "-1001234567890"


def test_processes_text_from_configured_group():
    handled = []
    worker = TelegramWorker(
        {
            "telegram_group_id": TEST_GROUP_ID,
            "ai_api_key": "fake-ai-key",
        },
        process_prompt=lambda text: handled.append(text) or None,
    )

    update = {
        "update_id": 10,
        "message": {
            "chat": {"id": int(TEST_GROUP_ID)},
            "text": "add buy milk to my todo list",
        },
    }

    worker._handle_update("fake-telegram-token", TEST_GROUP_ID, update)

    assert handled == ["add buy milk to my todo list"]


def test_ignores_text_from_other_chat():
    handled = []
    worker = TelegramWorker(
        {
            "telegram_group_id": TEST_GROUP_ID,
            "ai_api_key": "fake-ai-key",
        },
        process_prompt=lambda text: handled.append(text) or None,
    )

    update = {
        "update_id": 10,
        "message": {
            "chat": {"id": -1},
            "text": "add buy milk to my todo list",
        },
    }

    worker._handle_update("fake-telegram-token", TEST_GROUP_ID, update)

    assert handled == []


def test_sends_prompt_result_back_to_group():
    worker = TelegramWorker(
        {
            "telegram_group_id": TEST_GROUP_ID,
            "ai_api_key": "fake-ai-key",
        },
        process_prompt=lambda _text: "Which todo list?",
    )

    update = {
        "update_id": 10,
        "message": {
            "chat": {"id": int(TEST_GROUP_ID)},
            "text": "add a vague thing",
        },
    }

    with patch("lifeboard.telegram_worker._api_request") as request:
        worker._handle_update("fake-telegram-token", TEST_GROUP_ID, update)

    request.assert_called_once_with(
        "fake-telegram-token",
        "sendMessage",
        {"chat_id": TEST_GROUP_ID, "text": "Which todo list?"},
        timeout=10,
    )


def test_persists_last_update_state(tmp_config_dir):
    _write_state({"last_update_id": 123})

    assert _read_state() == {"last_update_id": 123}
