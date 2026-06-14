"""
Board Engine — the single source of truth for all board state.

Every entry point (menu bar, MCP, CLI) goes through this module.
The board is a list of widgets. Each widget has:
  - id: unique identifier
  - description: what this widget is (used by AI to understand context)
  - position: [x, y] as percentage of screen (0-100)
  - size: [w, h] as percentage of screen (0-100)
  - data: arbitrary JSON (the widget's content/state)
  - html_template: Jinja2-style HTML that renders the widget
  - css: scoped CSS for this widget
"""

import json
import math
import os
import uuid
from copy import deepcopy

import shutil

from config import BOARD_FILE, DEFAULT_THEME, ensure_dirs, get_default_resolution

BACKUP_FILE = BOARD_FILE + ".prev"
THEMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "themes")
DEFAULT_BASE_ROW_HEIGHT = 18.0
DEFAULT_LAYOUT_GUTTER = 2.0
MIN_WIDGET_SIZE = 3.0


def _empty_board() -> dict:
    return {
        "theme": DEFAULT_THEME,
        "resolution": get_default_resolution(),
        "widgets": [],
    }


def load_board() -> dict:
    ensure_dirs()
    if os.path.exists(BOARD_FILE):
        with open(BOARD_FILE) as f:
            return json.load(f)
    return _empty_board()


def save_board(board: dict):
    """Persist the board to disk.

    Does not touch the backup. Backups are explicit — call
    checkpoint_for_undo() at the start of each user-facing operation
    so multiple internal saves within one operation share one snapshot.
    """
    ensure_dirs()
    with open(BOARD_FILE, "w") as f:
        json.dump(board, f, indent=2)


def checkpoint_for_undo():
    """Snapshot the current saved board to BACKUP_FILE.

    Call once at the start of each user-facing operation (one AI command
    plan, one MCP tool invocation). Subsequent save_board calls during
    the same operation will not disturb this snapshot, so undo restores
    the pre-operation state rather than an intermediate one.
    """
    ensure_dirs()
    if os.path.exists(BOARD_FILE):
        shutil.copy2(BOARD_FILE, BACKUP_FILE)


def undo_board() -> bool:
    """Restore the previous board state. Returns True if restored."""
    if not os.path.exists(BACKUP_FILE):
        return False
    shutil.copy2(BACKUP_FILE, BOARD_FILE)
    os.remove(BACKUP_FILE)
    return True


def list_available_themes() -> list[str]:
    """Return sorted list of theme directories that exist on disk."""
    if not os.path.isdir(THEMES_DIR):
        return []
    return sorted(
        d for d in os.listdir(THEMES_DIR)
        if os.path.isdir(os.path.join(THEMES_DIR, d)) and not d.startswith(".")
    )


def get_widget(board: dict, widget_id: str) -> dict | None:
    for w in board["widgets"]:
        if w["id"] == widget_id:
            return w
    return None


def _widgets_overlap(a_pos, a_size, b_pos, b_size) -> bool:
    """Check if two widgets overlap. Positions and sizes are [x, y] percentages."""
    a_left, a_top = a_pos
    a_right, a_bottom = a_left + a_size[0], a_top + a_size[1]
    b_left, b_top = b_pos
    b_right, b_bottom = b_left + b_size[0], b_top + b_size[1]
    return a_left < b_right and a_right > b_left and a_top < b_bottom and a_bottom > b_top


def _widgets_too_close(a_pos, a_size, b_pos, b_size, gutter: float = DEFAULT_LAYOUT_GUTTER) -> bool:
    """Return True when normal widgets overlap or have less than gutter space."""
    a_left, a_top = a_pos
    a_right, a_bottom = a_left + a_size[0], a_top + a_size[1]
    b_left, b_top = b_pos
    b_right, b_bottom = b_left + b_size[0], b_top + b_size[1]
    return (
        a_left < b_right + gutter
        and a_right + gutter > b_left
        and a_top < b_bottom + gutter
        and a_bottom + gutter > b_top
    )


def _normalize_geometry_pair(value, field_name: str) -> list[float]:
    """Accept API-friendly geometry objects and store canonical [a, b] pairs."""
    if isinstance(value, dict):
        if field_name == "position":
            keys = ("x", "y")
        else:
            keys = ("width", "height") if "width" in value or "height" in value else ("w", "h")
        if not all(key in value for key in keys):
            raise ValueError(f"{field_name} must include {keys[0]!r} and {keys[1]!r}")
        value = [value[keys[0]], value[keys[1]]]

    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field_name} must be a two-item list")

    try:
        pair = [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} values must be numbers") from exc

    if not all(math.isfinite(item) for item in pair):
        raise ValueError(f"{field_name} values must be finite numbers")
    return pair


def _resolve_position(
    board: dict,
    position: list[float],
    size: list[float],
    exclude_id: str | None = None,
    gutter: float = DEFAULT_LAYOUT_GUTTER,
) -> list[float]:
    """Find a position with at least gutter space from other normal widgets."""
    position = _clamp_position(position, size)
    existing = [
        (w["position"], w["size"])
        for w in board["widgets"]
        if w["id"] != exclude_id and not _is_layout_background(w)
    ]

    if not any(_widgets_too_close(position, size, ep, es, gutter) for ep, es in existing):
        return position

    best = None
    best_dist = float("inf")
    max_x = max(0, math.floor(100.0 - size[0]))
    max_y = max(0, math.floor(100.0 - size[1]))
    for y in range(0, max_y + 1):
        for x in range(0, max_x + 1):
            candidate = [float(x), float(y)]
            if any(_widgets_too_close(candidate, size, ep, es, gutter) for ep, es in existing):
                continue
            dist = (x - position[0]) ** 2 + (y - position[1]) ** 2
            if dist < best_dist:
                best = candidate
                best_dist = dist
                if dist == 0:
                    return best
    return best if best is not None else position


def _clamp_size(size: list[float]) -> list[float]:
    width = min(100.0, max(MIN_WIDGET_SIZE, float(size[0])))
    height = min(100.0, max(MIN_WIDGET_SIZE, float(size[1])))
    return [round(width, 3), round(height, 3)]


def _clamp_position(position: list[float], size: list[float]) -> list[float]:
    left = min(100.0 - size[0], max(0.0, float(position[0])))
    top = min(100.0 - size[1], max(0.0, float(position[1])))
    return [round(left, 3), round(top, 3)]


def _normalize_widget_size(widget: dict, size: list[float]) -> list[float]:
    size = _clamp_size(size)
    if _widget_kind(widget) == "todo":
        size[1] = round(min(100.0, max(MIN_WIDGET_SIZE, _todo_height(widget, DEFAULT_BASE_ROW_HEIGHT))), 3)
    return size


def _normalize_z_index(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_programmatic_layout(board: dict) -> dict:
    """Clamp AI/MCP-written geometry and resolve normal-widget overlaps."""
    placed = []
    for widget in board.get("widgets", []):
        try:
            position = _normalize_geometry_pair(widget.get("position", [0, 0]), "position")
            size = _normalize_geometry_pair(widget.get("size", [20, 15]), "size")
        except ValueError:
            position = [0.0, 0.0]
            size = [20.0, 15.0]

        size = _normalize_widget_size(widget, size)
        position = _clamp_position(position, size)
        if not _is_layout_background(widget):
            position = _resolve_position({"widgets": placed}, position, size, exclude_id=widget.get("id"))

        widget["position"] = position
        widget["size"] = size
        widget["z_index"] = _normalize_z_index(widget.get("z_index", 0))
        placed.append(widget)

    return board


def add_widget(
    board: dict,
    description: str,
    position: list[float],
    size: list[float],
    data: dict,
    html_template: str,
    css: str,
    widget_id: str | None = None,
    data_provider: str | None = None,
    z_index: int = 0,
    refresh_interval: int | None = None,
) -> dict:
    """Add a new widget to the board. Automatically resolves overlaps. Returns the new widget."""
    wid = widget_id or str(uuid.uuid4())[:8]
    position = _normalize_geometry_pair(position, "position")
    size = _normalize_geometry_pair(size, "size")
    pending_widget = {
        "id": wid,
        "description": description,
        "data": data,
        "data_provider": data_provider,
    }
    size = _normalize_widget_size(pending_widget, size)
    position = _clamp_position(position, size)
    resolved_pos = _resolve_position(board, position, size, exclude_id=wid)
    widget = {
        "id": wid,
        "description": description,
        "position": resolved_pos,
        "size": size,
        "data": data,
        "html_template": html_template,
        "css": css,
        "z_index": _normalize_z_index(z_index),
    }
    if data_provider:
        widget["data_provider"] = data_provider
    if refresh_interval:
        widget["refresh_interval"] = refresh_interval
    board["widgets"].append(widget)
    save_board(board)
    return widget


def update_widget(board: dict, widget_id: str, updates: dict) -> dict | None:
    """Update fields on an existing widget. Resolves overlaps if position/size change. Returns updated widget or None."""
    widget = get_widget(board, widget_id)
    if not widget:
        return None
    updates = updates.copy()
    if "position" in updates:
        updates["position"] = _normalize_geometry_pair(updates["position"], "position")
    if "size" in updates:
        updates["size"] = _normalize_geometry_pair(updates["size"], "size")
    for key, value in updates.items():
        if key == "id":
            continue  # don't allow id changes
        if key == "z_index":
            value = _normalize_z_index(value)
        if key == "data" and isinstance(value, dict) and isinstance(widget.get("data"), dict):
            widget["data"].update(value)
        else:
            widget[key] = value
    # Re-check layout only for geometry edits and widget kinds whose data affects size.
    if "position" in updates or "size" in updates or ("data" in updates and _widget_kind(widget) == "todo"):
        widget["size"] = _normalize_widget_size(widget, widget["size"])
        widget["position"] = _clamp_position(widget["position"], widget["size"])
        if "position" in updates or "size" in updates:
            widget["position"] = _resolve_position(
                board, widget["position"], widget["size"], exclude_id=widget_id
            )
    save_board(board)
    return widget


def remove_widget(board: dict, widget_id: str) -> bool:
    """Remove a widget by id. Returns True if found and removed."""
    original_len = len(board["widgets"])
    board["widgets"] = [w for w in board["widgets"] if w["id"] != widget_id]
    if len(board["widgets"]) < original_len:
        save_board(board)
        return True
    return False


def set_theme(board: dict, theme: str):
    available = list_available_themes()
    if theme not in available:
        raise ValueError(
            f"Theme '{theme}' not found. Available: {', '.join(available) or '(none)'}"
        )
    board["theme"] = theme
    save_board(board)


def set_resolution(board: dict, width: int, height: int):
    board["resolution"] = [width, height]
    save_board(board)


def replace_board(board: dict, new_board: dict):
    """Full board replacement — used when the AI rewrites everything."""
    board.clear()
    board.update(new_board)
    normalize_programmatic_layout(board)
    save_board(board)


def apply_layout_edits(board: dict, edits: list[dict]) -> dict:
    """Apply exact manual position/size edits from the layout editor."""
    by_id = {w.get("id"): w for w in board.get("widgets", [])}
    for edit in edits:
        widget = by_id.get(edit.get("id"))
        if not widget:
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
        widget["position"] = [round(left, 3), round(top, 3)]
        widget["size"] = [round(width, 3), round(height, 3)]

    save_board(board)
    return board


def get_board_summary(board: dict) -> str:
    """Human-readable summary of the board for the AI to reason about."""
    lines = [f"Theme: {board['theme']}, Resolution: {board['resolution']}"]
    lines.append(f"Widgets ({len(board['widgets'])}):")
    for w in board["widgets"]:
        refresh = f" refresh={w['refresh_interval']}s" if w.get('refresh_interval') else ""
        lines.append(
            f"  - [{w['id']}] \"{w['description']}\" "
            f"at ({w['position'][0]}%, {w['position'][1]}%) "
            f"size ({w['size'][0]}%x{w['size'][1]}%) "
            f"z={_normalize_z_index(w.get('z_index', 0))}{refresh} "
            f"data={json.dumps(w['data'], default=str)[:200]}"
        )
    return "\n".join(lines)


def _widget_kind(widget: dict) -> str:
    provider = widget.get("data_provider")
    if provider in {"stock", "crypto"}:
        return "market"
    if provider in {"datetime", "weather"}:
        return "status"
    if provider in {"image", "photo_library"}:
        return "media"
    if "to-do" in widget.get("description", "").lower() or "todo" in widget.get("id", "").lower():
        return "todo"
    return "content"


def _has_media_source(widget: dict) -> bool:
    data = widget.get("data", {})
    provider = widget.get("data_provider")
    if provider == "image":
        return bool(data.get("file_path"))
    if provider == "photo_library":
        source = data.get("source")
        if source == "folder":
            return bool(data.get("folder_path"))
        if source == "topic":
            return bool(data.get("topic"))
    return True


def _is_layout_background(widget: dict) -> bool:
    return _normalize_z_index(widget.get("z_index", 0)) < 0 and _has_media_source(widget)


def _todo_height(widget: dict, base_row_height: float) -> float:
    items = widget.get("data", {}).get("items", [])
    item_count = len(items) if isinstance(items, list) else 0
    return max(14.0, 14.0 + item_count * 3.0)


def auto_layout(
    board: dict,
    columns: int = 4,
    gutter: float = 2.0,
    base_row_height: float = 18.0,
    preserve_spans: bool = True,
    top_margin: float = 6.0,
) -> dict:
    """Re-organize widgets into a tidy grid layout.

    - columns: number of columns across the screen
    - gutter: percentage gap between items and screen edges
    - base_row_height: base height for a 1x1 tile (in percent)
    - preserve_spans: try to approximate current widget size as multi-span tiles
    - top_margin: percentage inset from the top edge, leaving room for the menu bar

    Returns the updated board dict (and persists it).
    """
    widgets = [w for w in board.get("widgets", []) if not _is_layout_background(w)]
    if not widgets:
        return board

    # Compute column width in percent
    total_gutter = gutter * (columns + 1)
    col_w = max(1.0, (100.0 - total_gutter) / columns)

    # Sort status/content widgets before market tickers so finance widgets do not
    # dominate the top row after a cleanup pass.
    def _area(w):
        s = w.get("size", [20.0, 15.0])
        return float(s[0]) * float(s[1])

    widgets_sorted = sorted(
        widgets,
        key=lambda w: (
            {"status": 0, "todo": 1, "content": 2, "market": 3, "media": 4}.get(_widget_kind(w), 2),
            -_normalize_z_index(w.get("z_index", 0)),
            -_area(w),
        ),
    )

    column_bottoms = [top_margin] * columns

    def find_slot(span_w: int) -> tuple[float, int]:
        best_col = 0
        best_top = float("inf")
        for col in range(0, columns - span_w + 1):
            top = max(column_bottoms[col:col + span_w])
            if top < best_top:
                best_top = top
                best_col = col
        return best_top, best_col

    def to_span_w(size_w: float) -> int:
        # Round to nearest number of columns, min 1, max columns
        raw = max(1, round((size_w + gutter) / (col_w + gutter)))
        return int(min(columns, max(1, raw)))

    def to_span_h(size_h: float) -> int:
        # Round to nearest number of base rows
        raw = max(1, round(size_h / base_row_height))
        return int(max(1, raw))

    for w in widgets_sorted:
        size = w.get("size", [col_w, base_row_height])
        kind = _widget_kind(w)
        if kind == "market":
            span_w = 1
            span_h = 1
        elif kind == "todo":
            span_w = 1
            span_h = math.ceil(_todo_height(w, base_row_height) / base_row_height)
        elif kind == "media" and not _has_media_source(w):
            span_w = 1
            span_h = 1
            w["z_index"] = max(0, _normalize_z_index(w.get("z_index", 0)))
        elif kind == "media":
            span_w = 1
            span_h = 2
        elif preserve_spans:
            span_w = to_span_w(float(size[0]))
            span_h = to_span_h(float(size[1]))
        else:
            span_w = 1
            span_h = 1

        # Cap overly large spans
        span_w = max(1, min(columns, span_w))
        # Let todo rows grow with task count so list items are not clipped.
        if kind == "todo":
            span_h = max(1, span_h)
        else:
            span_h = max(1, min(4, span_h))

        width = span_w * col_w + (span_w - 1) * gutter
        height = span_h * base_row_height + (span_h - 1) * gutter
        if kind == "todo":
            height = _todo_height(w, base_row_height)

        top, col = find_slot(span_w)
        left = gutter + col * (col_w + gutter)
        w["position"] = [round(left, 3), round(top, 3)]
        w["size"] = [round(width, 3), round(height, 3)]
        bottom = top + height + gutter
        for occupied_col in range(col, col + span_w):
            column_bottoms[occupied_col] = bottom

    save_board(board)
    return board
