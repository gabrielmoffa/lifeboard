import json
import pytest
from unittest.mock import patch, MagicMock
from lifeboard.ai_interpreter import (
    _build_system_prompt,
    interpret,
    parse_ai_response,
    execute_commands,
)


class TestParseAiResponse:
    def test_parses_valid_json_array(self):
        raw = '[{"action": "set_theme", "theme": "minimal"}]'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "minimal"}]

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"action": "set_theme", "theme": "minimal"}]\n```'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "minimal"}]

    def test_strips_bare_fences(self):
        raw = '```\n[{"action": "set_theme", "theme": "hacker"}]\n```'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "hacker"}]

    def test_extracts_json_from_surrounding_text(self):
        raw = 'Sure! Here are the commands:\n[{"action": "set_theme", "theme": "minimal"}]\nLet me know if you need anything else.'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "minimal"}]

    def test_handles_trailing_comma(self):
        raw = '[{"action": "set_theme", "theme": "minimal"},]'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "minimal"}]

    def test_returns_message_on_total_failure(self):
        raw = "I don't understand what you want me to do."
        result = parse_ai_response(raw)
        assert len(result) == 1
        assert result[0]["action"] == "message"
        assert "couldn't understand" in result[0]["text"].lower() or raw in result[0]["text"]

    def test_handles_single_object_not_array(self):
        raw = '{"action": "set_theme", "theme": "minimal"}'
        result = parse_ai_response(raw)
        assert result == [{"action": "set_theme", "theme": "minimal"}]


class TestInterpretRetry:
    @patch("lifeboard.ai_interpreter.call_ai")
    def test_retries_on_parse_failure(self, mock_call):
        mock_call.side_effect = [
            "Sorry, here's what I think...",
            '[{"action": "set_theme", "theme": "hacker"}]',
        ]
        board = {"theme": "hacker", "resolution": [2560, 1600], "widgets": []}
        result = interpret("change theme", "fake-key", board)
        assert result == [{"action": "set_theme", "theme": "hacker"}]
        assert mock_call.call_count == 2

    @patch("lifeboard.ai_interpreter.call_ai")
    def test_gives_up_after_max_retries(self, mock_call):
        mock_call.return_value = "I can't help with that"
        board = {"theme": "hacker", "resolution": [2560, 1600], "widgets": []}
        result = interpret("do something", "fake-key", board)
        assert len(result) == 1
        assert result[0]["action"] == "message"


class TestExecuteCommands:
    def test_unknown_action_is_skipped(self, tmp_config_dir, sample_board):
        from lifeboard.board_engine import save_board
        save_board(sample_board)
        msg = execute_commands([{"action": "nonexistent_action"}], sample_board)
        assert msg is None

    def test_direct_add_widget_preserves_data_provider(self, tmp_config_dir):
        from lifeboard.board_engine import load_board, save_board

        board = {"theme": "slate", "resolution": [100, 100], "widgets": []}
        save_board(board)

        execute_commands([
            {
                "action": "add_widget",
                "id": "direct-weather",
                "description": "Weather",
                "position": [0, 0],
                "size": [20, 20],
                "data": {"location": "Tallinn"},
                "html_template": "<div>{{temp}}</div>",
                "css": "",
                "data_provider": "weather",
            }
        ], board)

        saved = load_board()
        assert saved["widgets"][0]["data_provider"] == "weather"


class TestSystemPrompt:
    def test_data_provider_list_is_generated_from_registry(self):
        prompt = _build_system_prompt()
        assert '"stock"' in prompt
        assert "requires finnhub_api_key" in prompt
        assert '"pomodoro"' not in prompt
        assert "countdown" not in prompt.lower()
