import plistlib

import set_wallpaper


def test_force_image_entries_restores_desktop_and_idle(tmp_path, monkeypatch):
    plist_path = tmp_path / "Index.plist"
    image_path = str(tmp_path / "wallpaper.png")
    plist = {
        "AllSpacesAndDisplays": {
            "Type": "idle",
            "Idle": {
                "Content": {
                    "Choices": [{
                        "Provider": "com.apple.wallpaper.choice.image",
                        "Files": [{"relative": "file:///old.png"}],
                        "Configuration": b"existing-config",
                    }],
                    "Shuffle": "$null",
                },
            },
        },
        "Displays": {
            "display-1": {},
        },
        "Spaces": {
            "space-1": {
                "Default": {},
                "Displays": {
                    "display-1": {},
                },
            },
        },
    }
    plist_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY))
    monkeypatch.setattr(set_wallpaper, "PLIST_PATH", str(plist_path))

    set_wallpaper.force_image_entries(plist, image_path)
    updated = plistlib.loads(plist_path.read_bytes())

    for entry in [
        updated["AllSpacesAndDisplays"],
        updated["SystemDefault"],
        updated["Displays"]["display-1"],
        updated["Spaces"]["space-1"]["Default"],
        updated["Spaces"]["space-1"]["Displays"]["display-1"],
    ]:
        assert entry["Type"] == "individual"
        for layer in ("Desktop", "Idle"):
            choice = entry[layer]["Content"]["Choices"][0]
            assert choice["Provider"] == "com.apple.wallpaper.choice.image"
            assert choice["Files"][0]["relative"] == f"file://{image_path}"
            config = plistlib.loads(choice["Configuration"])
            assert config["url"]["relative"] == (tmp_path / "wallpaper.png").as_uri()


def test_set_system_wallpaper_url_updates_fallback(tmp_path, monkeypatch):
    image_path = tmp_path / "wallpaper with spaces.png"
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(set_wallpaper.subprocess, "run", fake_run)

    assert set_wallpaper.set_system_wallpaper_url(str(image_path))
    assert calls == [
        (
            [
                "defaults",
                "write",
                "com.apple.wallpaper",
                "SystemWallpaperURL",
                "-string",
                image_path.as_uri(),
            ],
            {"capture_output": True, "text": True},
        )
    ]
