import os

from lifeboard import renderer


def test_macos_wallpaper_path_creates_unique_copies(tmp_path):
    rendered = tmp_path / "wallpaper.png"
    rendered.write_bytes(b"png")

    first = renderer._macos_wallpaper_path(str(rendered))
    second = renderer._macos_wallpaper_path(str(rendered))

    assert first != second
    assert os.path.exists(first)
    assert os.path.exists(second)


def test_reapply_current_wallpaper_uses_stable_wallpaper(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stable = output_dir / "wallpaper.png"
    stable.write_bytes(b"png")
    calls = []

    monkeypatch.setattr(renderer, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(renderer, "set_wallpaper", lambda path: calls.append(path))

    assert renderer.reapply_current_wallpaper() == str(stable)
    assert len(calls) == 1
    assert os.path.basename(calls[0]).startswith("wallpaper_macos_")


def test_reapply_current_wallpaper_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(renderer, "set_wallpaper", lambda path: (_ for _ in ()).throw(AssertionError(path)))

    assert renderer.reapply_current_wallpaper() is None


def test_cleanup_old_macos_wallpapers_keeps_protected_path(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(renderer, "MACOS_WALLPAPER_KEEP", 1)
    latest = tmp_path / "wallpaper_macos_latest.png"
    protected = tmp_path / "wallpaper_macos_protected.png"
    old = tmp_path / "wallpaper_macos_old.png"
    latest.write_bytes(b"latest")
    protected.write_bytes(b"protected")
    old.write_bytes(b"old")
    os.utime(old, (1, 1))
    os.utime(protected, (2, 2))
    os.utime(latest, (3, 3))

    renderer._cleanup_old_macos_wallpapers(protected_path=str(protected))

    assert latest.exists()
    assert protected.exists()
    assert not old.exists()
