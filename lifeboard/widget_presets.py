"""
Widget Presets — pre-built widget templates that can be added to the board instantly.
"""

import json
import os
import uuid

PRESETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "widget_presets")


def list_presets() -> list[dict]:
    """Return a list of available presets with name and description."""
    presets = []
    if not os.path.isdir(PRESETS_DIR):
        return presets
    for filename in sorted(os.listdir(PRESETS_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(PRESETS_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)
        presets.append({
            "name": data["name"],
            "description": data.get("description", ""),
        })
    return presets


def load_preset(name: str) -> dict | None:
    """Load a preset by name. Returns the full preset dict or None."""
    filepath = os.path.join(PRESETS_DIR, f"{name}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath) as f:
        return json.load(f)


def instantiate_preset(
    name: str,
    position: list[float],
    size: list[float] | None = None,
    data_overrides: dict | None = None,
    refresh_interval: int | None = None,
) -> dict | None:
    """Create a widget dict from a preset, ready to add to the board."""
    preset = load_preset(name)
    if preset is None:
        return None

    widget_id = f"{name}-{str(uuid.uuid4())[:6]}"
    actual_size = size if size is not None else preset.get("default_size", [20, 15])

    data = dict(preset.get("data", {}))
    if data_overrides:
        data.update(data_overrides)

    return {
        "id": widget_id,
        "description": preset["description"],
        "position": position,
        "size": actual_size,
        "data": data,
        "data_provider": preset.get("data_provider"),
        "html_template": preset["html_template"],
        "css": preset["css"],
        "z_index": preset.get("z_index") if preset.get("z_index") is not None else 0,
        "refresh_interval": refresh_interval if refresh_interval is not None else preset.get("refresh_interval"),
    }
