import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from lifeboard.data_providers import PhotoLibraryProvider, get_provider


def _make_image(path, size=(40, 30), color=(200, 100, 50)):
    Image.new("RGB", size, color).save(path, format="JPEG")


@pytest.fixture
def photo_dir(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    _make_image(folder / "a.jpg", size=(40, 30))
    _make_image(folder / "b.jpg", size=(60, 40))
    _make_image(folder / "c.jpg", size=(20, 30))
    return folder


class TestRegistry:
    def test_photo_library_provider_registered(self):
        provider = get_provider("photo_library")
        assert isinstance(provider, PhotoLibraryProvider)


class TestFolderMode:
    def test_returns_data_uri_and_dimensions(self, photo_dir):
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": str(photo_dir)})
        assert result["image_data_uri"].startswith("data:image/")
        assert "base64," in result["image_data_uri"]
        assert isinstance(result["image_width"], int)
        assert isinstance(result["image_height"], int)
        assert result["image_width"] > 0
        assert result["image_height"] > 0

    def test_returns_caption_with_filename(self, photo_dir):
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": str(photo_dir)})
        assert result["caption"] in {"a.jpg", "b.jpg", "c.jpg"}

    def test_records_last_shown_path(self, photo_dir):
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": str(photo_dir)})
        assert result["last_shown"].endswith(".jpg")
        assert str(photo_dir) in result["last_shown"]

    def test_avoids_immediate_repeat(self, photo_dir):
        provider = PhotoLibraryProvider()
        last = str(photo_dir / "a.jpg")
        for _ in range(20):
            result = provider.fetch({
                "source": "folder",
                "folder_path": str(photo_dir),
                "last_shown": last,
            })
            assert result["last_shown"] != last

    def test_single_image_allows_repeat(self, tmp_path):
        folder = tmp_path / "single"
        folder.mkdir()
        _make_image(folder / "only.jpg")
        provider = PhotoLibraryProvider()
        path = str(folder / "only.jpg")
        result = provider.fetch({
            "source": "folder",
            "folder_path": str(folder),
            "last_shown": path,
        })
        assert result["last_shown"] == path
        assert result["image_data_uri"].startswith("data:image/")

    def test_expands_user_home(self, photo_dir, monkeypatch):
        monkeypatch.setenv("HOME", str(photo_dir.parent))
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": "~/photos"})
        assert result["image_data_uri"].startswith("data:image/")

    def test_missing_folder_returns_placeholder(self):
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": "/no/such/dir"})
        assert result["image_data_uri"] == ""
        assert "message" in result

    def test_empty_folder_returns_placeholder(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": str(empty)})
        assert result["image_data_uri"] == ""
        assert "message" in result

    def test_ignores_non_image_files(self, tmp_path):
        folder = tmp_path / "mixed"
        folder.mkdir()
        (folder / "notes.txt").write_text("hi")
        _make_image(folder / "pic.jpg")
        provider = PhotoLibraryProvider()
        result = provider.fetch({"source": "folder", "folder_path": str(folder)})
        assert result["caption"] == "pic.jpg"


class TestTopicMode:
    def test_topic_uses_loremflickr(self):
        img_bytes = io.BytesIO()
        Image.new("RGB", (800, 600), (10, 20, 30)).save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()

        class FakeResp:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with patch("lifeboard.data_providers.urllib.request.urlopen") as mock:
            mock.return_value = FakeResp(img_bytes)
            provider = PhotoLibraryProvider()
            result = provider.fetch({
                "source": "topic",
                "topic": "mountains",
                "fetch_size": [800, 600],
            })
            called_url = mock.call_args[0][0].full_url
            assert "loremflickr.com" in called_url
            assert "800/600" in called_url
            assert "mountains" in called_url

        assert result["image_data_uri"].startswith("data:image/")
        assert result["image_width"] == 800
        assert result["image_height"] == 600
        assert result["caption"] == "mountains"

    def test_topic_url_encodes_multiple_tags(self):
        img_bytes = io.BytesIO()
        Image.new("RGB", (640, 480)).save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()

        class FakeResp:
            def read(self): return img_bytes
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("lifeboard.data_providers.urllib.request.urlopen") as mock:
            mock.return_value = FakeResp()
            PhotoLibraryProvider().fetch({
                "source": "topic",
                "topic": "sunset, beach",
                "fetch_size": [640, 480],
            })
            called_url = mock.call_args[0][0].full_url
            assert "sunset" in called_url
            assert "beach" in called_url

    def test_topic_network_failure_returns_placeholder(self):
        with patch("lifeboard.data_providers.urllib.request.urlopen", side_effect=OSError("net down")):
            provider = PhotoLibraryProvider()
            result = provider.fetch({"source": "topic", "topic": "cats"})
            assert result["image_data_uri"] == ""
            assert "message" in result

    def test_topic_falls_back_to_commons_when_loremflickr_fails(self):
        img_bytes = io.BytesIO()
        Image.new("RGB", (800, 600), (10, 20, 30)).save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()
        commons_payload = {
            "query": {
                "pages": {
                    "1": {
                        "imageinfo": [{
                            "thumburl": "https://upload.wikimedia.org/example.jpg",
                            "mime": "image/jpeg",
                        }]
                    }
                }
            }
        }

        class FakeResp:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=10):
            url = req.full_url
            if "loremflickr.com" in url:
                raise OSError("blocked")
            if "commons.wikimedia.org" in url:
                return FakeResp(json.dumps(commons_payload).encode("utf-8"))
            return FakeResp(img_bytes)

        with patch("lifeboard.data_providers.urllib.request.urlopen", side_effect=fake_urlopen):
            result = PhotoLibraryProvider().fetch({
                "source": "topic",
                "topic": "singapore",
                "fetch_size": [800, 600],
            })

        assert result["image_data_uri"].startswith("data:image/jpeg;base64,")
        assert result["image_width"] == 800
        assert result["image_height"] == 600
        assert result["caption"] == "singapore"

    def test_empty_topic_uses_fallback(self):
        img_bytes = io.BytesIO()
        Image.new("RGB", (800, 600)).save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()

        class FakeResp:
            def read(self): return img_bytes
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("lifeboard.data_providers.urllib.request.urlopen") as mock:
            mock.return_value = FakeResp()
            PhotoLibraryProvider().fetch({"source": "topic", "topic": ""})
            called_url = mock.call_args[0][0].full_url
            assert "nature" in called_url


class TestUnknownSource:
    def test_defaults_to_folder_mode(self, photo_dir):
        provider = PhotoLibraryProvider()
        result = provider.fetch({"folder_path": str(photo_dir)})
        assert result["image_data_uri"].startswith("data:image/")
