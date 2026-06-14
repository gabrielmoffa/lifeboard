"""
Renderer — turns board.json + theme into a PNG wallpaper.

Pipeline: board state → HTML document → Playwright screenshot → set wallpaper
"""

import os
import re
import shutil
import subprocess
import sys
import time
import asyncio
from contextlib import contextmanager
import fcntl

from config import OUTPUT_DIR, ensure_dirs, get_default_resolution
from config import DEFAULT_THEME
from lifeboard.data_providers import inject_data_into_board

THEMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "themes")
MACOS_WALLPAPER_PREFIX = "wallpaper_macos_"
MACOS_WALLPAPER_KEEP = 200
WALLPAPER_LOCK_FILE = "wallpaper.lock"


_VIEWPORT_UNIT_RE = re.compile(r'(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(vw|vh)(?![A-Za-z])')
# Typical Mac widgets occupy ~25% of the viewport, so 1vw on a default Mac widget
# equals ~4cqi. This multiplier preserves Mac visuals when translating, while
# letting bigger widgets (e.g. full-width on phone) scale up proportionally.
_VW_TO_CQI_MULTIPLIER = 4


def _viewport_to_container_units(css: str) -> str:
    """Translate vw/vh to cqi/cqb so widget CSS sizes relative to its widget container.

    Combined with container-type: size on the widget wrapper, this makes widget
    typography and spacing scale with the widget itself rather than the screen,
    which matters when the same widget appears on Mac (landscape) and phone
    (portrait, narrower viewport but larger widget %).
    """
    if not css:
        return css

    def replace(match: "re.Match[str]") -> str:
        n = float(match.group(1))
        unit = match.group(2)
        new_unit = "cqi" if unit == "vw" else "cqb"
        scaled = n * _VW_TO_CQI_MULTIPLIER
        return f"{scaled:g}{new_unit}"

    return _VIEWPORT_UNIT_RE.sub(replace, css)


def _z_index(widget: dict) -> int:
    try:
        return int(widget.get("z_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _load_theme_css(theme_name: str) -> str:
    theme_path = os.path.join(THEMES_DIR, theme_name, "global.css")
    if os.path.exists(theme_path):
        with open(theme_path) as f:
            return f.read()
    return ""


def _render_widget_html(widget: dict, z_index: int = 0) -> str:
    """Render a single widget into its positioned HTML container."""
    pos = widget["position"]
    size = widget["size"]
    widget_id = widget["id"]

    # The html_template may contain {{key}} placeholders or be fully baked HTML.
    # We replace simple placeholders with data values, and also inject data as
    # a JSON script block so inline JS can access it.
    import json as _json
    html = widget.get("html_template", "")
    data = widget.get("data", {})

    # Simple placeholder replacement for flat values
    for key, value in data.items():
        if not isinstance(value, (dict, list)):
            html = html.replace("{{" + key + "}}", str(value))

    # Inject data as a scoped JS variable. We set it on the widget's DOM element
    # and also as a local WIDGET_DATA for inline scripts within this widget.
    data_json_str = _json.dumps(data)
    data_script = (
        f'<script>(function() {{'
        f' var el = document.getElementById("widget-{widget_id}");'
        f' var WIDGET_DATA = {data_json_str};'
        f' el._WIDGET_DATA = WIDGET_DATA;'
        f' window._WIDGET_DATA_{widget_id.replace("-", "_")} = WIDGET_DATA;'
        f'}})()</script>'
    )
    # Replace references to WIDGET_DATA in the template's inline scripts
    # with the widget-specific global so they resolve correctly
    safe_var = f'window._WIDGET_DATA_{widget_id.replace("-", "_")}'
    html = html.replace("WIDGET_DATA", safe_var)
    html = data_script + html

    css = widget.get("css", "")
    css = _viewport_to_container_units(css)
    scoped_css = _scope_css(css, widget_id)

    return f"""
    <div class="widget" id="widget-{widget_id}" style="
        position: absolute;
        left: {pos[0]}%;
        top: {pos[1]}%;
        width: {size[0]}%;
        height: {size[1]}%;
        z-index: {z_index};
        overflow: hidden;
        container-type: size;
    ">
        <style>{scoped_css}</style>
        {html}
    </div>
    """


def _scope_css(css: str, widget_id: str) -> str:
    """Prefix CSS selectors with #widget-{id} to prevent cross-widget bleeding.
    Skips at-rules (@keyframes, @media, @font-face, etc.)."""
    if not css.strip():
        return css
    prefix = f"#widget-{widget_id}"

    def replace_rule(match):
        selectors = match.group(1)
        # Skip at-rules — they aren't selectors
        if selectors.strip().startswith("@"):
            return match.group(0)
        # Skip selectors that are already inside an at-rule block (e.g. keyframe stops like "0%", "from", "to")
        stripped = selectors.strip()
        if stripped in ("from", "to") or re.match(r'^\d+%$', stripped):
            return match.group(0)
        scoped = ", ".join(
            f"{prefix} {s.strip()}" for s in selectors.split(",")
        )
        return scoped + " {"
    return re.sub(r'([^{}]+)\{', replace_rule, css)


def board_to_html(board: dict) -> str:
    """Compose the full HTML document from board state."""
    resolution = board.get("resolution", get_default_resolution())
    theme = board.get("theme", DEFAULT_THEME)
    theme_css = _load_theme_css(theme)

    sorted_widgets = sorted(board.get("widgets", []), key=_z_index)
    widgets_html = "\n".join(
        _render_widget_html(w, z_index=_z_index(w)) for w in sorted_widgets
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        width: {resolution[0]}px;
        height: {resolution[1]}px;
        position: relative;
        overflow: hidden;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    {theme_css}
</style>
</head>
<body>
    {widgets_html}
</body>
</html>"""


async def render_to_png(board: dict, output_filename: str = "wallpaper.png") -> str:
    """Render board to PNG, return the file path."""
    from playwright.async_api import async_playwright

    ensure_dirs()
    inject_data_into_board(board)
    html = board_to_html(board)
    resolution = board.get("resolution", get_default_resolution())
    scale = int(board.get("device_scale_factor", 1) or 1)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": resolution[0], "height": resolution[1]},
            device_scale_factor=scale,
        )
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=output_path, full_page=False)
        await browser.close()

    return output_path


@contextmanager
def _wallpaper_lock():
    ensure_dirs()
    lock_path = os.path.join(OUTPUT_DIR, WALLPAPER_LOCK_FILE)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _macos_wallpaper_path(rendered_path: str) -> str:
    """Return a cache-busted copy for macOS while keeping wallpaper.png stable."""
    output_dir = os.path.dirname(rendered_path)
    stamp = time.time_ns()
    macos_path = os.path.join(output_dir, f"{MACOS_WALLPAPER_PREFIX}{stamp}.png")
    shutil.copy2(rendered_path, macos_path)
    return macos_path


def _cleanup_old_macos_wallpapers(protected_path: str | None = None):
    output_dir = OUTPUT_DIR
    old_paths = sorted(
        (
            os.path.join(output_dir, name)
            for name in os.listdir(output_dir)
            if name.startswith(MACOS_WALLPAPER_PREFIX) and name.endswith(".png")
        ),
        key=lambda path: os.path.getmtime(path),
        reverse=True,
    )
    protected_abs = os.path.abspath(protected_path) if protected_path else None
    for old_path in old_paths[MACOS_WALLPAPER_KEEP:]:
        if protected_abs and os.path.abspath(old_path) == protected_abs:
            continue
        try:
            os.remove(old_path)
        except OSError:
            pass


def _apply_rendered_wallpaper(rendered_path: str) -> str:
    with _wallpaper_lock():
        macos_path = _macos_wallpaper_path(rendered_path)
        set_wallpaper(macos_path)
        _cleanup_old_macos_wallpapers(protected_path=macos_path)
        return macos_path


def reapply_current_wallpaper() -> str | None:
    """Reapply the last rendered wallpaper without re-rendering providers/widgets."""
    png_path = os.path.join(OUTPUT_DIR, "wallpaper.png")
    if not os.path.exists(png_path):
        return None
    _apply_rendered_wallpaper(png_path)
    return png_path


async def render_phone_to_png(mac_board: dict) -> str | None:
    """Render the phone projection to PNG. Returns path, or None if projection is empty."""
    from lifeboard.phone_board import resolve_phone_board

    phone_board = resolve_phone_board(mac_board)
    if not phone_board["widgets"]:
        return None
    return await render_to_png(phone_board, output_filename="wallpaper_phone.png")


def set_wallpaper(image_path: str):
    """Set the macOS desktop wallpaper via plist manipulation (Sequoia-compatible)."""
    abs_path = os.path.abspath(image_path)
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "set_wallpaper.py")
    subprocess.run([sys.executable, script, abs_path], check=True)


async def render_and_set_wallpaper(board: dict) -> str:
    """Full pipeline: render Mac board, set as wallpaper, also render phone PNG."""
    png_path = await render_to_png(board)
    _apply_rendered_wallpaper(png_path)
    try:
        await render_phone_to_png(board)
    except Exception:
        # Phone render failures must never break the Mac wallpaper flow.
        import logging
        logging.exception("phone render failed")
    return png_path
