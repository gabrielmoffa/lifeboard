import io
import json
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
from lifeboard.data_providers import (
    CryptoProvider,
    get_provider,
    run_provider,
    inject_data_into_board,
    DatetimeProvider,
    NewsProvider,
    PhotoLibraryProvider,
    StockProvider,
    WeatherProvider,
)


class TestDatetimeProvider:
    def test_returns_time_fields(self):
        provider = DatetimeProvider()
        result = provider.fetch({})
        assert "time" in result
        assert "date" in result
        assert "day_of_week" in result
        assert "hour" in result
        assert "minute" in result

    def test_time_format(self):
        provider = DatetimeProvider()
        result = provider.fetch({})
        assert ":" in result["time"]


class TestWeatherProvider:
    @patch("lifeboard.data_providers.WeatherProvider._fetch_weather")
    def test_returns_weather_fields(self, mock_fetch):
        mock_fetch.return_value = {
            "temp": 72,
            "condition": "Sunny",
            "humidity": 45,
            "wind": 8,
            "location": "San Francisco",
        }
        provider = WeatherProvider()
        result = provider.fetch({"location": "San Francisco"})
        assert result["temp"] == 72
        assert result["condition"] == "Sunny"

    @patch("lifeboard.data_providers.WeatherProvider._fetch_weather")
    def test_fetch_failure_returns_defaults(self, mock_fetch):
        mock_fetch.side_effect = Exception("Network error")
        provider = WeatherProvider()
        result = provider.fetch({"location": "NYC"})
        assert result["condition"] == "unavailable"

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_metric_units_use_celsius_and_kmh(self, mock_urlopen):
        class FakeResp:
            def read(self):
                return json.dumps({
                    "current_condition": [{
                        "temp_C": "17",
                        "temp_F": "63",
                        "humidity": "39",
                        "windspeedKmph": "30",
                        "windspeedMiles": "19",
                        "weatherDesc": [{"value": "Sunny"}],
                    }],
                    "nearest_area": [{"areaName": [{"value": "Oleviste"}]}],
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.return_value = FakeResp()
        provider = WeatherProvider()
        result = provider.fetch({"location": "Tallinn", "units": "metric"})

        assert result["temp"] == 17
        assert result["wind"] == 30
        assert result["location"] == "Tallinn"
        assert result["temp_unit"] == "C"
        assert result["wind_unit"] == "km/h"
        assert "?m&format=j1" in mock_urlopen.call_args.args[0].full_url


class TestMarketProviders:
    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_crypto_fetch_failure_uses_cached_prices(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))

        class FakeResp:
            def read(self):
                return b'{"bitcoin":{"usd":65000.25,"usd_24h_change":1.234}}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.side_effect = [FakeResp(), OSError("network down")]
        provider = CryptoProvider()
        widget_data = {"symbols": ["bitcoin"], "currency": "usd"}

        first = provider.fetch(widget_data)
        second = provider.fetch(widget_data)

        assert first["tickers"][0]["price"] == "65,000.25"
        assert second == first

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_crypto_provider_replaces_non_finite_api_values(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))

        class FakeResp:
            def read(self):
                return b'{"bitcoin":{"usd":NaN,"usd_24h_change":NaN}}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.return_value = FakeResp()
        provider = CryptoProvider()
        result = provider.fetch({"symbols": ["bitcoin"], "currency": "usd"})

        assert result["tickers"] == [{"symbol": "bitcoin", "price": "--", "change_24h": 0}]

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_stock_fetch_failure_uses_cached_prices(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
        monkeypatch.setattr("config.load_config", lambda: {"finnhub_api_key": "key"})

        class FakeResp:
            def read(self):
                return b'{"c":195.12,"d":1.2,"dp":0.62}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.side_effect = [FakeResp(), OSError("network down")]
        provider = StockProvider()
        widget_data = {"symbols": ["AAPL"]}

        first = provider.fetch(widget_data)
        second = provider.fetch(widget_data)

        assert first["tickers"][0]["price"] == "195.12"
        assert second == first

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_stock_provider_replaces_non_finite_api_values(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
        monkeypatch.setattr("config.load_config", lambda: {"finnhub_api_key": "key"})

        class FakeResp:
            def read(self):
                return b'{"c":NaN,"d":NaN,"dp":NaN}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.return_value = FakeResp()
        provider = StockProvider()
        result = provider.fetch({"symbols": ["AAPL"]})

        assert result["tickers"] == [{"symbol": "AAPL", "price": "--", "change": 0, "change_pct": 0}]

    def test_stock_provider_returns_setup_message_without_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
        monkeypatch.setattr("config.load_config", lambda: {"finnhub_api_key": ""})

        provider = StockProvider()
        result = provider.fetch({"symbols": ["AAPL"]})

        assert result["requires_config"] == "finnhub_api_key"
        assert "Finnhub API key" in result["message"]
        assert result["tickers"][0]["price"] == "No API key"


class TestNewsProvider:
    def test_parse_rss_returns_articles(self):
        raw = b"""<?xml version="1.0" encoding="UTF-8" ?>
        <rss><channel>
          <item>
            <title>First headline - Example News</title>
            <link>https://news.google.com/rss/articles/1</link>
            <pubDate>Tue, 28 Apr 2026 10:00:00 GMT</pubDate>
          </item>
          <item>
            <title>Second headline</title>
            <source url="https://example.com">Example Source</source>
            <link>https://news.google.com/rss/articles/2</link>
          </item>
        </channel></rss>"""
        provider = NewsProvider()
        articles = provider._parse_rss(raw, 5)
        assert articles == [
            {
                "title": "First headline",
                "source": "Example News",
                "published": "Tue, 28 Apr 2026 10:00:00 GMT",
                "url": "https://news.google.com/rss/articles/1",
            },
            {
                "title": "Second headline",
                "source": "Example Source",
                "published": "",
                "url": "https://news.google.com/rss/articles/2",
            },
        ]

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_fetch_news_uses_topic_and_locale(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value.read.return_value = b"<rss><channel></channel></rss>"
        mock_urlopen.return_value = mock_resp
        provider = NewsProvider()
        result = provider.fetch({
            "topic": "artificial intelligence",
            "country": "EE",
            "language": "en",
            "max_items": 20,
        })
        request = mock_urlopen.call_args.args[0]
        assert "q=artificial+intelligence" in request.full_url
        assert "hl=en-EE" in request.full_url
        assert "gl=EE" in request.full_url
        assert "ceid=EE%3Aen" in request.full_url
        assert result["message"] == "no news found"

    @patch("lifeboard.data_providers.NewsProvider._fetch_news")
    def test_fetch_failure_returns_empty_articles(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
        mock_fetch.side_effect = Exception("Network error")
        provider = NewsProvider()
        result = provider.fetch({"topic": "AI"})
        assert result == {
            "topic": "AI",
            "articles": [],
            "message": "news unavailable",
        }

    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_fetch_failure_uses_cached_articles(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))

        class FakeResp:
            def read(self):
                return b"""<rss><channel><item>
                <title>Cached headline - Example News</title>
                <link>https://news.google.com/rss/articles/1</link>
                </item></channel></rss>"""
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.side_effect = [FakeResp(), OSError("network down")]
        provider = NewsProvider()
        widget_data = {"topic": "AI", "max_items": 5, "country": "US", "language": "en"}

        first = provider.fetch(widget_data)
        second = provider.fetch(widget_data)

        assert first["articles"][0]["title"] == "Cached headline"
        assert second["articles"][0]["title"] == "Cached headline"
        assert second["message"] == ""


class TestPhotoLibraryProvider:
    @patch("lifeboard.data_providers.urllib.request.urlopen")
    def test_topic_failure_uses_cached_image(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
        img = io.BytesIO()
        Image.new("RGB", (800, 600), (10, 20, 30)).save(img, format="JPEG")
        img_bytes = img.getvalue()

        class FakeResp:
            def read(self):
                return img_bytes
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        widget_data = {
            "source": "topic",
            "topic": "new york",
            "fetch_size": [800, 600],
        }
        mock_urlopen.side_effect = [FakeResp(), OSError("network down"), OSError("network down")]
        provider = PhotoLibraryProvider()

        first = provider.fetch(widget_data)
        second = provider.fetch(widget_data)

        assert first["image_data_uri"].startswith("data:image/jpeg;base64,")
        assert second["image_data_uri"] == first["image_data_uri"]
        assert second["caption"] == "new york"


class TestGetProvider:
    def test_datetime_provider(self):
        provider = get_provider("datetime")
        assert isinstance(provider, DatetimeProvider)

    def test_weather_provider(self):
        provider = get_provider("weather")
        assert isinstance(provider, WeatherProvider)

    def test_news_provider(self):
        provider = get_provider("news")
        assert isinstance(provider, NewsProvider)

    def test_unknown_returns_none(self):
        assert get_provider("nonexistent") is None


class TestInjectData:
    def test_injects_data_into_widget_with_provider(self):
        board = {
            "theme": "hacker",
            "resolution": [2560, 1600],
            "widgets": [{
                "id": "clock-1",
                "description": "Clock",
                "position": [0, 0],
                "size": [20, 10],
                "data": {},
                "data_provider": "datetime",
                "html_template": "<div>{{time}}</div>",
                "css": "",
            }],
        }
        inject_data_into_board(board)
        assert "time" in board["widgets"][0]["data"]
        assert "date" in board["widgets"][0]["data"]

    def test_skips_widgets_without_provider(self):
        board = {
            "theme": "hacker",
            "resolution": [2560, 1600],
            "widgets": [{
                "id": "static-1",
                "description": "Static",
                "position": [0, 0],
                "size": [20, 10],
                "data": {"title": "Hello"},
                "html_template": "<div>{{title}}</div>",
                "css": "",
            }],
        }
        inject_data_into_board(board)
        assert board["widgets"][0]["data"] == {"title": "Hello"}
