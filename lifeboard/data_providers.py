"""
Data Providers — fetch live data and inject it into widgets before rendering.

Each provider knows how to fetch one type of data (time, weather, etc.).
Widgets declare which provider they use via the 'data_provider' field.
Before rendering, we run each widget's provider and merge the results into
the widget's data dict.
"""

import base64
import datetime
import hashlib
import io
import json
import logging
import math
import mimetypes
import os
import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


def _cache_path(provider: str, key_data: dict) -> str:
    from config import CONFIG_DIR, ensure_dirs
    ensure_dirs()
    cache_dir = os.path.join(CONFIG_DIR, "provider_cache", provider)
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{key}.json")


def _read_cache(provider: str, key_data: dict) -> dict | None:
    path = _cache_path(provider, key_data)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"{provider} cache read failed: {e}")
        return None


def _write_cache(provider: str, key_data: dict, payload: dict):
    path = _cache_path(provider, key_data)
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except OSError as e:
        logger.warning(f"{provider} cache write failed: {e}")


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _has_market_price(payload: dict) -> bool:
    return any(t.get("price") not in (None, "", "--", "No API key") for t in payload.get("tickers", []))


class DataProvider:
    """Base class for data providers."""

    def fetch(self, widget_data: dict) -> dict:
        """Fetch fresh data. Returns a dict to merge into widget data."""
        raise NotImplementedError


class DatetimeProvider(DataProvider):
    """Provides current date and time."""

    def fetch(self, widget_data: dict) -> dict:
        now = datetime.datetime.now()
        h = now.hour
        ampm = "PM" if h >= 12 else "AM"
        h = h % 12 or 12
        return {
            "time": f"{h}:{now.minute:02d} {ampm}",
            "date": now.strftime("%B %d, %Y"),
            "day_of_week": now.strftime("%A"),
            "hour": now.hour,
            "minute": now.minute,
            "year": now.year,
            "month": now.month,
            "day": now.day,
        }


class WeatherProvider(DataProvider):
    """Provides current weather using wttr.in (no API key needed)."""

    def fetch(self, widget_data: dict) -> dict:
        try:
            return self._fetch_weather(widget_data)
        except Exception as e:
            logger.warning(f"Weather fetch failed: {e}")
            units = _weather_units(widget_data)
            return {
                "temp": "--",
                "condition": "unavailable",
                "humidity": "--",
                "wind": "--",
                "location": widget_data.get("location", "unknown"),
                "units": units,
                "temp_unit": "C" if units == "metric" else "F",
                "wind_unit": "km/h" if units == "metric" else "mph",
            }

    def _fetch_weather(self, widget_data: dict) -> dict:
        location = widget_data.get("location", "")
        units = _weather_units(widget_data)
        unit_option = "m" if units == "metric" else "u"
        query_location = "" if location == "auto" else str(location)
        encoded_location = urllib.parse.quote(query_location)
        url = f"https://wttr.in/{encoded_location}?{unit_option}&format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        city = area.get("areaName", [{}])[0].get("value", location)
        temp_key = "temp_C" if units == "metric" else "temp_F"
        wind_key = "windspeedKmph" if units == "metric" else "windspeedMiles"

        return {
            "temp": int(current[temp_key]),
            "condition": current["weatherDesc"][0]["value"],
            "humidity": int(current["humidity"]),
            "wind": int(current[wind_key]),
            "location": city if location == "auto" else location,
            "units": units,
            "temp_unit": "C" if units == "metric" else "F",
            "wind_unit": "km/h" if units == "metric" else "mph",
        }


def _weather_units(widget_data: dict) -> str:
    units = str(widget_data.get("units", "imperial")).lower()
    if units in {"metric", "si", "c", "celsius"}:
        return "metric"
    return "imperial"


class CryptoProvider(DataProvider):
    """Fetches crypto prices from CoinGecko."""

    def fetch(self, widget_data: dict) -> dict:
        try:
            result = self._fetch_prices(widget_data)
            if _has_market_price(result):
                _write_cache("crypto", self._cache_key(widget_data), result)
            return result
        except Exception as e:
            logger.warning(f"Crypto fetch failed: {e}")
            cached = _read_cache("crypto", self._cache_key(widget_data))
            if cached:
                return cached
            symbols = widget_data.get("symbols", ["bitcoin"])
            return {"tickers": [{"symbol": s, "price": "--", "change_24h": 0} for s in symbols]}

    def _cache_key(self, widget_data: dict) -> dict:
        return {
            "symbols": widget_data.get("symbols", ["bitcoin"]),
            "currency": widget_data.get("currency", "usd"),
        }

    def _fetch_prices(self, widget_data: dict) -> dict:
        from config import load_config
        config = load_config()
        api_key = widget_data.get("coingecko_api_key") or config.get("coingecko_api_key", "")
        symbols = widget_data.get("symbols", ["bitcoin"])
        currency = widget_data.get("currency", "usd")
        ids = ",".join(symbols)
        if api_key:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies={currency}&include_24hr_change=true&x_cg_demo_api_key={api_key}"
        else:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies={currency}&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        tickers = []
        for symbol in symbols:
            info = data.get(symbol, {})
            price = info.get(currency, 0)
            change = info.get(f"{currency}_24h_change", 0)
            tickers.append({
                "symbol": symbol,
                "price": f"{price:,.2f}" if _is_finite_number(price) else "--",
                "change_24h": round(change, 2) if _is_finite_number(change) else 0,
            })
        return {"tickers": tickers, "currency": currency.upper()}


class StockProvider(DataProvider):
    """Fetches stock prices from Finnhub (free API key required)."""

    def fetch(self, widget_data: dict) -> dict:
        try:
            result = self._fetch_prices(widget_data)
            if _has_market_price(result):
                _write_cache("stock", self._cache_key(widget_data), result)
            return result
        except Exception as e:
            logger.warning(f"Stock fetch failed: {e}")
            cached = _read_cache("stock", self._cache_key(widget_data))
            if cached:
                return cached
            symbols = widget_data.get("symbols", ["AAPL"])
            return {"tickers": [{"symbol": s, "price": "--", "change": 0, "change_pct": 0} for s in symbols]}

    def _cache_key(self, widget_data: dict) -> dict:
        return {"symbols": widget_data.get("symbols", ["AAPL"])}

    def _fetch_prices(self, widget_data: dict) -> dict:
        from config import load_config
        config = load_config()
        api_key = widget_data.get("finnhub_api_key") or config.get("finnhub_api_key", "")
        if not api_key:
            return {
                "tickers": [
                    {"symbol": s, "price": "No API key", "change": 0, "change_pct": 0}
                    for s in widget_data.get("symbols", ["AAPL"])
                ],
                "message": "Set a Finnhub API key to show live stock prices.",
                "requires_config": "finnhub_api_key",
            }

        symbols = widget_data.get("symbols", ["AAPL"])
        tickers = []
        for symbol in symbols:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            price = data.get("c")
            change = data.get("d", 0)
            change_pct = data.get("dp", 0)
            tickers.append({
                "symbol": symbol,
                "price": f"{price:,.2f}" if _is_finite_number(price) and price else "--",
                "change": round(change, 2) if _is_finite_number(change) else 0,
                "change_pct": round(change_pct, 2) if _is_finite_number(change_pct) else 0,
            })
        return {"tickers": tickers}


class NewsProvider(DataProvider):
    """Fetches topic-based headlines from Google News RSS."""

    def fetch(self, widget_data: dict) -> dict:
        try:
            return self._fetch_news(widget_data)
        except Exception as e:
            logger.warning(f"News fetch failed: {e}")
            topic = (widget_data.get("topic") or "technology").strip() or "technology"
            cached = _read_cache("news", self._cache_key(widget_data))
            if cached:
                return cached
            return {
                "topic": topic,
                "articles": [],
                "message": "news unavailable",
            }

    def _fetch_news(self, widget_data: dict) -> dict:
        topic = (widget_data.get("topic") or "technology").strip() or "technology"
        max_items = int(widget_data.get("max_items", 5))
        max_items = max(1, min(max_items, 10))
        language = (widget_data.get("language") or "en").strip() or "en"
        country = (widget_data.get("country") or "US").strip().upper() or "US"
        locale = widget_data.get("locale") or f"{language}-{country}"
        ceid = widget_data.get("ceid") or f"{country}:{language}"
        params = urllib.parse.urlencode({
            "q": topic,
            "hl": locale,
            "gl": country,
            "ceid": ceid,
        })
        url = f"https://news.google.com/rss/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()

        articles = self._parse_rss(raw, max_items)
        result = {
            "topic": topic,
            "articles": articles,
            "message": "" if articles else "no news found",
        }
        if articles:
            _write_cache("news", self._cache_key(widget_data), result)
        return result

    def _cache_key(self, widget_data: dict) -> dict:
        topic = (widget_data.get("topic") or "technology").strip() or "technology"
        language = (widget_data.get("language") or "en").strip() or "en"
        country = (widget_data.get("country") or "US").strip().upper() or "US"
        return {
            "topic": topic,
            "max_items": int(widget_data.get("max_items", 5)),
            "language": language,
            "country": country,
            "locale": widget_data.get("locale") or f"{language}-{country}",
            "ceid": widget_data.get("ceid") or f"{country}:{language}",
        }

    def _parse_rss(self, raw: bytes, max_items: int) -> list[dict]:
        root = ET.fromstring(raw)
        articles = []
        for item in root.findall("./channel/item")[:max_items]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or "").strip()
            source = ""
            source_el = item.find("source")
            if source_el is not None and source_el.text:
                source = source_el.text.strip()
            if not source and " - " in title:
                title, source = title.rsplit(" - ", 1)
                title = title.strip()
                source = source.strip()
            if title:
                articles.append({
                    "title": title,
                    "source": source,
                    "published": published,
                    "url": link,
                })
        return articles


class ImageProvider(DataProvider):
    """Reads a local image file and returns it as a base64 data URI."""

    def fetch(self, widget_data: dict) -> dict:
        file_path = widget_data.get("file_path", "")
        file_path = os.path.expanduser(file_path)
        if not file_path or not os.path.exists(file_path):
            logger.warning(f"Image file not found: {file_path}")
            return {"image_data_uri": ""}
        mime_type = mimetypes.guess_type(file_path)[0] or "image/png"
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return {"image_data_uri": f"data:{mime_type};base64,{encoded}"}


class PhotoLibraryProvider(DataProvider):
    """Picks one image per render from a local folder or LoremFlickr topic.

    Cadence is controlled by the widget's refresh_interval (default 1h in the
    preset). Returns image_data_uri + image_width/height so the frame can
    match the photo's natural aspect ratio. Avoids immediate repeats by
    persisting last_shown into widget data.
    """

    EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

    def fetch(self, widget_data: dict) -> dict:
        try:
            if widget_data.get("source") == "topic":
                return self._fetch_topic(widget_data)
            return self._fetch_folder(widget_data)
        except Exception as e:
            logger.warning(f"PhotoLibrary fetch failed: {e}")
            if widget_data.get("source") == "topic":
                cached = _read_cache("photo_library", self._topic_cache_key(widget_data))
                if cached:
                    return cached
            return self._placeholder("unavailable")

    def _fetch_folder(self, d: dict) -> dict:
        folder = os.path.expanduser(d.get("folder_path", ""))
        if not folder or not os.path.isdir(folder):
            return self._placeholder("folder not found")
        files = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in self.EXTS
        )
        if not files:
            return self._placeholder("no images")
        last = d.get("last_shown", "")
        choices = [f for f in files if f != last] or files
        path = random.choice(choices)
        with open(path, "rb") as f:
            raw = f.read()
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        encoded = self._encode_bytes(raw, mime)
        return {**encoded, "last_shown": path, "caption": os.path.basename(path)}

    def _fetch_topic(self, d: dict) -> dict:
        topic = (d.get("topic") or "").strip() or "nature"
        size = d.get("fetch_size") or [800, 600]
        w, h = int(size[0]), int(size[1])
        tag = urllib.parse.quote(topic, safe=",")
        url = f"https://loremflickr.com/{w}/{h}/{tag}"
        req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            encoded = self._encode_bytes(raw, "image/jpeg")
        except Exception as e:
            logger.warning(f"PhotoLibrary LoremFlickr fetch failed: {e}")
            encoded = self._fetch_commons_topic(topic, w)
        result = {**encoded, "caption": topic}
        _write_cache("photo_library", self._topic_cache_key(d), result)
        return result

    def _topic_cache_key(self, d: dict) -> dict:
        topic = (d.get("topic") or "").strip() or "nature"
        size = d.get("fetch_size") or [800, 600]
        return {
            "source": "topic",
            "topic": topic,
            "fetch_size": [int(size[0]), int(size[1])],
        }

    def _fetch_commons_topic(self, topic: str, width: int) -> dict:
        params = urllib.parse.urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{topic} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": "10",
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "iiurlwidth": str(width),
            "format": "json",
            "origin": "*",
        })
        url = f"https://commons.wikimedia.org/w/api.php?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "lifeboard/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)

        candidates = []
        pages = payload.get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            image_url = info.get("thumburl") or info.get("url")
            if image_url and mime in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                candidates.append((image_url, mime))
        if not candidates:
            raise ValueError(f"No Commons images found for topic: {topic}")

        image_url, mime = random.choice(candidates)
        image_req = urllib.request.Request(image_url, headers={"User-Agent": "lifeboard/1.0"})
        with urllib.request.urlopen(image_req, timeout=10) as resp:
            raw = resp.read()
        return self._encode_bytes(raw, mime)

    def _encode_bytes(self, raw: bytes, mime: str) -> dict:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
        b64 = base64.b64encode(raw).decode("ascii")
        return {
            "image_data_uri": f"data:{mime};base64,{b64}",
            "image_width": width,
            "image_height": height,
        }

    def _placeholder(self, message: str) -> dict:
        return {
            "image_data_uri": "",
            "image_width": 4,
            "image_height": 3,
            "caption": "",
            "message": message,
        }


PROVIDER_REGISTRY = {
    "datetime": DatetimeProvider,
    "weather": WeatherProvider,
    "crypto": CryptoProvider,
    "stock": StockProvider,
    "news": NewsProvider,
    "image": ImageProvider,
    "photo_library": PhotoLibraryProvider,
}

PROVIDER_METADATA = {
    "datetime": {
        "description": "injects time, date, day_of_week, hour, minute, year, month, day",
        "widget_data": "no required data",
    },
    "weather": {
        "description": "injects temp, condition, humidity, wind, location, temp_unit, wind_unit from wttr.in",
        "widget_data": "location such as 'Tallinn' or 'auto'; optional units 'metric' or 'imperial'",
    },
    "crypto": {
        "description": "fetches crypto prices from CoinGecko and injects tickers with symbol, price, change_24h",
        "widget_data": "symbols as CoinGecko ids, currency such as 'usd'; API key is optional",
    },
    "stock": {
        "description": "fetches stock prices from Finnhub and injects tickers with symbol, price, change, change_pct",
        "widget_data": "symbols as ticker strings such as ['AAPL']; requires finnhub_api_key in config",
    },
    "news": {
        "description": "fetches Google News RSS headlines and injects articles, topic, and message",
        "widget_data": "topic, max_items, country, language",
    },
    "image": {
        "description": "reads a local image file and injects image_data_uri",
        "widget_data": "file_path plus optional fit",
    },
    "photo_library": {
        "description": "selects one local folder image or internet topic image per render",
        "widget_data": "source 'folder' with folder_path, or source 'topic' with topic; optional show_caption",
    },
}


def get_provider(name: str) -> DataProvider | None:
    """Look up a provider by name."""
    cls = PROVIDER_REGISTRY.get(name)
    return cls() if cls else None


def list_provider_specs() -> list[dict]:
    """Return provider descriptions from the runtime provider registry."""
    specs = []
    for name in sorted(PROVIDER_REGISTRY):
        meta = PROVIDER_METADATA.get(name, {})
        specs.append({
            "name": name,
            "description": meta.get("description", ""),
            "widget_data": meta.get("widget_data", ""),
        })
    return specs


def run_provider(name: str, widget_data: dict) -> dict:
    """Run a named provider and return the fetched data."""
    provider = get_provider(name)
    if provider is None:
        return {}
    return provider.fetch(widget_data)


def inject_data_into_board(board: dict):
    """Walk all widgets, run their data providers, merge results into widget data.

    Mutates the board dict in place. Called before rendering.
    """
    for widget in board.get("widgets", []):
        provider_name = widget.get("data_provider")
        if not provider_name:
            continue
        fresh_data = run_provider(provider_name, widget.get("data", {}))
        if fresh_data:
            widget.setdefault("data", {}).update(fresh_data)
