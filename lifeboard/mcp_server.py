"""
Lifeboard MCP Server — exposes the board engine as tools for Claude Code / Codex.

Run with: python -m lifeboard.mcp_server
Or add to Claude Code's MCP config.
"""

import asyncio
import json
import os
import sys

from mcp.server.fastmcp import FastMCP

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lifeboard.board_engine import (
    load_board, save_board, get_board_summary, get_widget,
    add_widget, update_widget, remove_widget, set_theme, set_resolution,
    undo_board, checkpoint_for_undo, list_available_themes,
    auto_layout,
)
from config import load_config, save_config
from lifeboard.renderer import render_and_set_wallpaper
from lifeboard.widget_presets import list_presets, instantiate_preset

mcp = FastMCP("lifeboard")


@mcp.tool()
def get_board() -> str:
    """Get the current board state as a readable summary. Use this to understand what's on the wallpaper before making changes."""
    board = load_board()
    return get_board_summary(board)


@mcp.tool()
def get_board_json() -> str:
    """Get the full board state as JSON. Use this when you need the complete data including HTML templates."""
    board = load_board()
    return json.dumps(board, indent=2)



@mcp.tool()
async def add_widget_to_board(
    widget_id: str,
    description: str,
    position_x: float,
    position_y: float,
    width: float,
    height: float,
    data_json: str,
    html_template: str,
    css: str,
    z_index: int = 0,
    refresh_interval: int = 0,
    data_provider: str = "",
) -> str:
    """Add a widget directly to the board. Positions and sizes are percentages (0-100). Programmatic placement keeps a default 2% gap between normal widgets; use the layout editor for exact manual placement. data_json is a JSON string of the widget's data. html_template can use {{key}} placeholders from data. z_index controls layering (lower = behind, default 0, use -1 for background images). refresh_interval is seconds between auto-refreshes (0 = no refresh). data_provider enables live data injection (datetime, weather, crypto, stock, news, image, photo_library)."""
    checkpoint_for_undo()
    board = load_board()
    data = json.loads(data_json)
    widget = add_widget(board, description, [position_x, position_y], [width, height], data, html_template, css, widget_id, z_index=z_index, refresh_interval=refresh_interval or None, data_provider=data_provider or None)
    await render_and_set_wallpaper(board)
    return f"Added widget '{widget['id']}': {widget['description']}"


@mcp.tool()
async def update_widget_on_board(widget_id: str, updates_json: str) -> str:
    """Update an existing widget. updates_json is a JSON string with any of: data, position, size, html_template, css, description, refresh_interval, data_provider, z_index. Programmatic position/size changes keep a default 2% gap between normal widgets."""
    checkpoint_for_undo()
    board = load_board()
    updates = json.loads(updates_json)
    result = update_widget(board, widget_id, updates)
    if result:
        await render_and_set_wallpaper(board)
        return f"Updated widget '{widget_id}'"
    return f"Widget '{widget_id}' not found"


@mcp.tool()
async def remove_widget_from_board(widget_id: str) -> str:
    """Remove a widget from the board by its ID."""
    checkpoint_for_undo()
    board = load_board()
    if remove_widget(board, widget_id):
        await render_and_set_wallpaper(board)
        return f"Removed widget '{widget_id}'"
    return f"Widget '{widget_id}' not found"


@mcp.tool()
async def change_theme(theme_name: str) -> str:
    """Change the board's visual theme. Use list_themes to see available options."""
    checkpoint_for_undo()
    board = load_board()
    try:
        set_theme(board, theme_name)
    except ValueError as e:
        return str(e)
    await render_and_set_wallpaper(board)
    return f"Theme changed to '{theme_name}'"


@mcp.tool()
def list_themes() -> str:
    """List all available visual themes."""
    themes = list_available_themes()
    if not themes:
        return "No themes found."
    return "Available themes: " + ", ".join(themes)



@mcp.tool()
async def set_board_resolution(width: int, height: int) -> str:
    """Override the auto-detected wallpaper resolution in pixels. Re-renders after changing."""
    checkpoint_for_undo()
    board = load_board()
    set_resolution(board, width, height)
    await render_and_set_wallpaper(board)
    return f"Resolution set to {width}x{height}"


@mcp.tool()
async def undo_last_change() -> str:
    """Undo the last board change, restoring the previous state. Re-renders the wallpaper after restoring."""
    if undo_board():
        board = load_board()
        await render_and_set_wallpaper(board)
        return "Restored previous board state and re-rendered wallpaper."
    return "No previous state to restore."


@mcp.tool()
async def render_wallpaper() -> str:
    """Re-render the wallpaper from current board state. Use this to refresh data providers (clock, weather, images) without changing any widgets."""
    board = load_board()
    png_path = await render_and_set_wallpaper(board)
    return f"Wallpaper re-rendered: {png_path}"


@mcp.tool()
async def reorganize_layout(
    columns: int = 4,
    gutter: float = 2.0,
    base_row_height: float = 18.0,
    preserve_spans: bool = True,
    top_margin: float = 6.0,
) -> str:
    """Clean up the current board layout into a tidy grid. Market widgets are kept compact, background widgets stay in place, the configured gutter is kept between widgets, and the wallpaper is re-rendered."""
    checkpoint_for_undo()
    board = load_board()
    auto_layout(
        board,
        columns=columns,
        gutter=gutter,
        base_row_height=base_row_height,
        preserve_spans=preserve_spans,
        top_margin=top_margin,
    )
    await render_and_set_wallpaper(board)
    return "Layout reorganized and wallpaper re-rendered."


@mcp.tool()
async def log_habit(habit_name: str, date: str = "") -> str:
    """Quick shortcut to log a habit entry. If no date is given, uses today. Finds the habit widget by name and adds the date to its entries."""
    import datetime
    if not date:
        date = datetime.date.today().isoformat()

    checkpoint_for_undo()
    board = load_board()
    for widget in board["widgets"]:
        if habit_name.lower() in widget.get("description", "").lower():
            entries = widget.get("data", {}).get("entries", [])
            if date not in entries:
                entries.append(date)
                update_widget(board, widget["id"], {"data": {"entries": entries}})
                await render_and_set_wallpaper(board)
                return f"Logged '{habit_name}' for {date}"
            return f"'{habit_name}' already logged for {date}"

    return f"No habit widget found matching '{habit_name}'. Add one first."


@mcp.tool()
def list_widget_presets() -> str:
    """List all available widget presets. Returns names and descriptions."""
    presets = list_presets()
    if not presets:
        return "No presets available."
    lines = [f"- {p['name']}: {p['description']}" for p in presets]
    return "Available presets:\n" + "\n".join(lines)


@mcp.tool()
async def add_preset_widget(
    preset_name: str,
    position_x: float,
    position_y: float,
    width: float = 0,
    height: float = 0,
    data_overrides_json: str = "{}",
    refresh_interval: int = 0,
) -> str:
    """Add a widget from a preset template. Use list_widget_presets to see available presets. Programmatic placement keeps a default 2% gap between normal widgets. Set width/height to 0 to use defaults. Set refresh_interval in seconds to override the preset default (0 = use preset default)."""
    size = [width, height] if width > 0 and height > 0 else None
    data_overrides = json.loads(data_overrides_json) if data_overrides_json != "{}" else None

    widget = instantiate_preset(preset_name, [position_x, position_y], size, data_overrides, refresh_interval=refresh_interval or None)
    if widget is None:
        return f"Preset '{preset_name}' not found. Use list_widget_presets to see available presets."

    checkpoint_for_undo()
    board = load_board()
    add_widget(
        board,
        description=widget["description"],
        position=widget["position"],
        size=widget["size"],
        data=widget["data"],
        html_template=widget["html_template"],
        css=widget["css"],
        widget_id=widget["id"],
        data_provider=widget.get("data_provider"),
        z_index=widget.get("z_index", 0),
        refresh_interval=widget.get("refresh_interval"),
    )
    await render_and_set_wallpaper(board)
    return f"Added preset widget '{preset_name}' as '{widget['id']}' at ({position_x}%, {position_y}%)"


@mcp.tool()
def set_finnhub_api_key(api_key: str) -> str:
    """Set the Finnhub API key for stock data. Get a free key at finnhub.io."""
    config = load_config()
    config["finnhub_api_key"] = api_key
    save_config(config)
    return "Finnhub API key saved."


@mcp.tool()
def set_coingecko_api_key(api_key: str) -> str:
    """Set the CoinGecko API key for crypto data."""
    config = load_config()
    config["coingecko_api_key"] = api_key
    save_config(config)
    return "CoinGecko API key saved."


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
