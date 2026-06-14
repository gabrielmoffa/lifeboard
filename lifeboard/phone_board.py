"""
Phone board — a projection of the Mac board sized for an iPhone.

Stores only references to Mac widget IDs plus per-widget layout overrides
(position, size, z_index). Widget content (data, html_template, css,
provider, etc.) is read live from the Mac board at render time, so
content edits sync automatically. Layout is independent.

File: ~/.lifeboard/board_phone.json
Schema: { "widgets": [ {"id": str, "position": [x,y], "size": [w,h], "z_index": int} ] }
"""

import json
import os
from copy import deepcopy

from config import (
    DEFAULT_THEME,
    PHONE_BOARD_FILE,
    ensure_dirs,
    get_iphone_resolution,
    get_iphone_scale,
    load_config,
)


def _empty_projection() -> dict:
    return {"widgets": []}


def load_phone_projection() -> dict:
    ensure_dirs()
    if os.path.exists(PHONE_BOARD_FILE):
        with open(PHONE_BOARD_FILE) as f:
            return json.load(f)
    return _empty_projection()


def save_phone_projection(projection: dict):
    ensure_dirs()
    with open(PHONE_BOARD_FILE, "w") as f:
        json.dump(projection, f, indent=2)


def add_widget_to_phone(
    mac_widget_id: str,
    position: list[float] | None = None,
    size: list[float] | None = None,
    z_index: int = 0,
) -> dict:
    """Add a Mac widget reference to the phone projection. Idempotent on id."""
    projection = load_phone_projection()
    for ref in projection["widgets"]:
        if ref["id"] == mac_widget_id:
            return ref
    final_size = size if size is not None else [94.0, 14.0]
    final_position = position if position is not None else find_free_phone_position(final_size)
    ref = {
        "id": mac_widget_id,
        "position": final_position,
        "size": final_size,
        "z_index": z_index,
    }
    projection["widgets"].append(ref)
    save_phone_projection(projection)
    return ref


def remove_widget_from_phone(mac_widget_id: str) -> bool:
    projection = load_phone_projection()
    original_len = len(projection["widgets"])
    projection["widgets"] = [w for w in projection["widgets"] if w["id"] != mac_widget_id]
    if len(projection["widgets"]) < original_len:
        save_phone_projection(projection)
        return True
    return False


def apply_phone_layout_edits(edits: list[dict]) -> dict:
    """Apply manual position/size edits to the phone projection. Mirrors apply_layout_edits."""
    projection = load_phone_projection()
    by_id = {ref["id"]: ref for ref in projection["widgets"]}
    for edit in edits:
        ref = by_id.get(edit.get("id"))
        if not ref:
            continue
        position = edit.get("position")
        size = edit.get("size")
        if (
            not isinstance(position, list)
            or not isinstance(size, list)
            or len(position) != 2
            or len(size) != 2
        ):
            continue
        width = min(100.0, max(3.0, float(size[0])))
        height = min(100.0, max(3.0, float(size[1])))
        left = min(100.0 - width, max(0.0, float(position[0])))
        top = min(100.0 - height, max(0.0, float(position[1])))
        ref["position"] = [round(left, 3), round(top, 3)]
        ref["size"] = [round(width, 3), round(height, 3)]
    save_phone_projection(projection)
    return projection


def auto_layout_phone(gutter: float = 3.0, top_margin: float = 4.0, default_height: float = 14.0) -> dict:
    """Stack phone widgets full-width vertically in current order. Persists."""
    projection = load_phone_projection()
    cursor_y = top_margin
    for ref in projection["widgets"]:
        height = max(3.0, float(ref.get("size", [0, default_height])[1]))
        if cursor_y + height > 100.0:
            height = max(3.0, 100.0 - cursor_y)
        ref["position"] = [round(gutter, 3), round(cursor_y, 3)]
        ref["size"] = [round(100.0 - 2 * gutter, 3), round(height, 3)]
        cursor_y += height + gutter
    save_phone_projection(projection)
    return projection


def find_free_phone_position(size: list[float]) -> list[float]:
    """Find a non-overlapping placement for a new widget on the phone canvas."""
    projection = load_phone_projection()
    existing = [(r["position"], r["size"]) for r in projection["widgets"]]

    def overlaps(pos):
        a_l, a_t = pos
        a_r, a_b = a_l + size[0], a_t + size[1]
        for ep, es in existing:
            b_l, b_t = ep
            b_r, b_b = b_l + es[0], b_t + es[1]
            if a_l < b_r and a_r > b_l and a_t < b_b and a_b > b_t:
                return True
        return False

    candidate = [3.0, 3.0]
    if not overlaps(candidate):
        return candidate
    # Try stacking below the lowest existing widget.
    if existing:
        bottom = max(p[1] + s[1] for p, s in existing) + 2.0
        if bottom + size[1] <= 100.0:
            return [3.0, round(bottom, 3)]
    # Last resort — top-left, may overlap.
    return [3.0, 3.0]


def list_available_mac_widgets(mac_board: dict) -> list[dict]:
    """Return Mac widgets not yet on the phone, with minimal info for sidebar UI."""
    projection = load_phone_projection()
    on_phone = {ref["id"] for ref in projection["widgets"]}
    return [
        {
            "id": w["id"],
            "description": w.get("description", ""),
            "data_provider": w.get("data_provider", ""),
        }
        for w in mac_board.get("widgets", [])
        if w["id"] not in on_phone
    ]


def resolve_phone_board(mac_board: dict, config: dict | None = None) -> dict:
    """Build a render-ready board by joining the phone projection against the Mac board.

    - Inherits theme from the Mac board.
    - Resolution comes from the configured iPhone model.
    - Widget content (html, css, data, provider) is copied from Mac.
    - Position, size, z_index come from the phone projection.
    - Orphan refs (Mac widget no longer exists) are auto-pruned and persisted.
    """
    projection = load_phone_projection()
    mac_by_id = {w["id"]: w for w in mac_board.get("widgets", [])}

    resolved_widgets = []
    surviving_refs = []
    for ref in projection["widgets"]:
        mac_widget = mac_by_id.get(ref["id"])
        if not mac_widget:
            continue
        widget = deepcopy(mac_widget)
        widget["position"] = ref.get("position", [0.0, 0.0])
        widget["size"] = ref.get("size", [20.0, 15.0])
        widget["z_index"] = int(ref.get("z_index", 0) or 0)
        resolved_widgets.append(widget)
        surviving_refs.append(ref)

    if len(surviving_refs) != len(projection["widgets"]):
        projection["widgets"] = surviving_refs
        save_phone_projection(projection)

    return {
        "theme": mac_board.get("theme", DEFAULT_THEME),
        "resolution": get_iphone_resolution(config),
        "device_scale_factor": get_iphone_scale(config),
        "widgets": resolved_widgets,
    }
