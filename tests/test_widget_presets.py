import json
import os
import pytest
from lifeboard.widget_presets import list_presets, load_preset, instantiate_preset


class TestListPresets:
    def test_returns_list(self):
        presets = list_presets()
        assert isinstance(presets, list)
        assert len(presets) > 0

    def test_each_preset_has_required_fields(self):
        for preset in list_presets():
            assert "name" in preset
            assert "description" in preset

    def test_timer_presets_are_not_available(self):
        preset_names = {preset["name"] for preset in list_presets()}
        assert "pomodoro" not in preset_names
        assert "countdown" not in preset_names


class TestLoadPreset:
    def test_load_existing_preset(self):
        preset = load_preset("clock")
        assert preset is not None
        assert preset["name"] == "clock"
        assert "html_template" in preset
        assert "css" in preset

    def test_load_nonexistent_returns_none(self):
        assert load_preset("nonexistent_widget_xyz") is None

    def test_crypto_ticker_handles_formatted_price_strings(self):
        preset = load_preset("crypto_ticker")
        assert preset is not None
        assert "parseNum" in preset["html_template"]
        assert "replace(/,/g, '')" in preset["html_template"]
        assert "return Number.isFinite(v) ? v : null" in preset["html_template"]
        assert "Number(t.price)" not in preset["html_template"]

    def test_stock_ticker_handles_placeholder_prices(self):
        preset = load_preset("stock_ticker")
        assert preset is not None
        assert "parseNum" in preset["html_template"]
        assert "return Number.isFinite(v) ? v : null" in preset["html_template"]
        assert "Number(t.price)" not in preset["html_template"]
        assert "d.message" in preset["html_template"]
        assert "document.currentScript.parentElement" in preset["html_template"]
        assert "document.getElementById" not in preset["html_template"]

    def test_news_preset_uses_news_provider(self):
        preset = load_preset("news")
        assert preset is not None
        assert preset["data_provider"] == "news"
        assert preset["data"]["topic"] == "technology"

    def test_news_preset_is_safe_for_multiple_instances(self):
        preset = load_preset("news")
        assert preset is not None
        assert 'id=' not in preset["html_template"]
        assert "document.currentScript.parentElement" in preset["html_template"]
        assert "document.getElementById" not in preset["html_template"]

    def test_weather_preset_supports_units_without_global_ids(self):
        preset = load_preset("weather")
        assert preset is not None
        assert preset["data"]["units"] == "imperial"
        assert "temp_unit" in preset["html_template"]
        assert "wind_unit" in preset["html_template"]
        assert 'id=' not in preset["html_template"]
        assert "document.currentScript.parentElement" in preset["html_template"]


class TestInstantiatePreset:
    def test_instantiate_creates_widget_dict(self, tmp_config_dir, sample_board):
        from lifeboard.board_engine import save_board
        save_board(sample_board)
        widget = instantiate_preset("clock", position=[50, 10], size=[20, 15])
        assert widget is not None
        assert widget["id"].startswith("clock-")
        assert widget["position"] == [50, 10]
        assert widget["size"] == [20, 15]
        assert "html_template" in widget

    def test_instantiate_with_data_overrides(self, tmp_config_dir, sample_board):
        from lifeboard.board_engine import save_board
        save_board(sample_board)
        widget = instantiate_preset("weather", position=[10, 10], size=[20, 15], data_overrides={"location": "Tallinn", "units": "metric"})
        assert widget is not None
        assert widget["data"]["location"] == "Tallinn"
        assert widget["data"]["units"] == "metric"

    def test_instantiate_nonexistent_returns_none(self):
        assert instantiate_preset("nope", [0, 0], [10, 10]) is None

    def test_null_preset_z_index_defaults_to_zero(self):
        widget = instantiate_preset("clock", [0, 0])
        assert widget is not None
        assert widget["z_index"] == 0
