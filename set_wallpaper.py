#!/usr/bin/env python3
"""
Set macOS Sequoia/Tahoe wallpaper by directly modifying the wallpaper plist.

Sequoia uses ~/Library/Application Support/com.apple.wallpaper/Store/Index.plist
instead of the old desktoppicture.db or NSWorkspace API (which only sets
the static layer behind animated wallpapers).
"""

import os
import sys
import plistlib
import subprocess
import datetime
import time
from pathlib import Path

PLIST_PATH = os.path.expanduser(
    "~/Library/Application Support/com.apple.wallpaper/Store/Index.plist"
)
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
NSWORKSPACE_HELPER = os.path.join(REPO_DIR, "set_wallpaper")


def image_file_url(image_path: str) -> str:
    return Path(image_path).absolute().as_uri()


def make_image_choice(image_path: str, config_blob: bytes | None = None) -> dict:
    """Create a wallpaper choice dict for a static image."""
    file_url = image_file_url(image_path)

    if config_blob is not None:
        try:
            config = plistlib.loads(config_blob)
            if isinstance(config, dict):
                config["type"] = "imageFile"
                config["url"] = {"relative": file_url}
                config_blob = plistlib.dumps(config, fmt=plistlib.FMT_BINARY)
        except Exception:
            config_blob = None

    if config_blob is None:
        # Build Configuration matching macOS's exact format:
        # placement=1 (fill), black background, colorSpace as nested bplist
        colorspace_bplist = plistlib.dumps("kCGColorSpaceGenericRGB", fmt=plistlib.FMT_BINARY)
        config_blob = plistlib.dumps(
            {
                "type": "imageFile",
                "url": {"relative": file_url},
                "placement": 1,
                "backgroundColor": {
                    "components": [0.0, 0.0, 0.0, 1.0],
                    "colorSpace": colorspace_bplist,
                },
            },
            fmt=plistlib.FMT_BINARY,
        )

    return {
        "Provider": "com.apple.wallpaper.choice.image",
        "Files": [{"relative": file_url}],
        "Configuration": config_blob,
    }


def make_content_block(image_path: str, config_blob: bytes | None = None) -> dict:
    """Create the Content dict wrapping a choice."""
    return {
        "Choices": [make_image_choice(image_path, config_blob)],
        "Shuffle": "$null",
    }


def make_desktop_entry(image_path: str, config_blob: bytes | None = None) -> dict:
    """Create a full Desktop entry with timestamps."""
    now = datetime.datetime.now()
    return {
        "Content": make_content_block(image_path, config_blob),
        "LastSet": now,
        "LastUse": now,
    }


def extract_working_config(plist: dict) -> bytes | None:
    """Try to find an existing working image config blob from the plist."""
    for space in plist.get("Spaces", {}).values():
        for section in [space.get("Default", {})] + list(space.get("Displays", {}).values()):
            desktop = section.get("Desktop", {})
            choices = desktop.get("Content", {}).get("Choices", [])
            for choice in choices:
                if choice.get("Provider") == "com.apple.wallpaper.choice.image":
                    config = choice.get("Configuration", b"")
                    if config and len(config) > 10:
                        return config
    return None


def apply_with_nsworkspace(image_path: str) -> bool:
    """Ask macOS to make this image the active visible desktop wallpaper."""
    if not os.path.exists(NSWORKSPACE_HELPER) or not os.access(NSWORKSPACE_HELPER, os.X_OK):
        return False

    result = subprocess.run([NSWORKSPACE_HELPER, image_path], capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        print(f"NSWorkspace wallpaper helper failed with exit code {result.returncode}")
        return False
    return True


def load_wallpaper_plist() -> dict:
    with open(PLIST_PATH, "rb") as f:
        return plistlib.load(f)


def save_wallpaper_plist(plist: dict):
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f, fmt=plistlib.FMT_BINARY)


def set_system_wallpaper_url(image_path: str) -> bool:
    """Update the legacy/system wallpaper URL used as a fallback by WallpaperAgent."""
    result = subprocess.run(
        [
            "defaults",
            "write",
            "com.apple.wallpaper",
            "SystemWallpaperURL",
            "-string",
            image_file_url(image_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        print(f"defaults SystemWallpaperURL write failed with exit code {result.returncode}")
        return False
    return True


def force_image_entries(plist: dict, image_path: str) -> bool:
    """Write Lifeboard's image into every known Desktop and Idle entry."""
    existing_config = extract_working_config(plist)
    if existing_config:
        print("Reusing existing wallpaper configuration blob")

    desktop_entry = make_desktop_entry(image_path, existing_config)
    # macOS 26 Tahoe may show the scenic default from the Idle layer unless it
    # is updated along with Desktop.
    idle_entry = make_desktop_entry(image_path, existing_config)

    # Set AllSpacesAndDisplays
    plist["AllSpacesAndDisplays"] = {
        "Desktop": desktop_entry,
        "Idle": idle_entry,
        "Type": "individual",
    }

    # Set SystemDefault
    plist["SystemDefault"] = {
        "Desktop": desktop_entry,
        "Idle": idle_entry,
        "Type": "individual",
    }

    # Update every display
    if "Displays" in plist:
        for display_id in plist["Displays"]:
            plist["Displays"][display_id] = {
                "Desktop": make_desktop_entry(image_path, existing_config),
                "Idle": idle_entry,
                "Type": "individual",
            }

    # Update every space and its displays
    if "Spaces" in plist:
        for space_id in plist["Spaces"]:
            space = plist["Spaces"][space_id]
            space["Default"] = {
                "Desktop": make_desktop_entry(image_path, existing_config),
                "Idle": idle_entry,
                "Type": "individual",
            }
            if "Displays" in space:
                for display_id in space["Displays"]:
                    space["Displays"][display_id] = {
                        "Desktop": make_desktop_entry(image_path, existing_config),
                        "Idle": idle_entry,
                        "Type": "individual",
                    }

    save_wallpaper_plist(plist)
    return True


def set_wallpaper(image_path: str):
    image_path = os.path.abspath(image_path)

    if not os.path.exists(image_path):
        print(f"Error: {image_path} not found")
        sys.exit(1)

    if not os.path.exists(PLIST_PATH):
        print(f"Error: {PLIST_PATH} not found")
        sys.exit(1)

    plist = load_wallpaper_plist()
    force_image_entries(plist, image_path)
    set_system_wallpaper_url(image_path)

    # Restart WallpaperAgent after writing the plist, then use NSWorkspace to
    # update the visible desktop layer. Finally rewrite the plist because
    # NSWorkspace may collapse AllSpacesAndDisplays to an Idle-only record.
    subprocess.run(["killall", "WallpaperAgent"], capture_output=True)
    helper_applied = apply_with_nsworkspace(image_path)
    if helper_applied:
        for delay in (1, 3, 8):
            time.sleep(delay)
            plist = load_wallpaper_plist()
            force_image_entries(plist, image_path)
            set_system_wallpaper_url(image_path)

    print(f"Wallpaper set to: {image_path}")
    print("WallpaperAgent restarted.")
    if helper_applied:
        print("NSWorkspace helper applied.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python set_wallpaper.py <image_path>")
        sys.exit(1)
    set_wallpaper(sys.argv[1])
