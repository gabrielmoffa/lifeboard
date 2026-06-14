"""
AI Interpreter — takes natural language + current board state,
returns structured commands to modify the board.

The AI sees the full board and decides:
  - Whether to add, update, remove, or rearrange widgets
  - What HTML/CSS to generate for new/modified widgets
  - How to update widget data without regenerating HTML

For data-only updates (e.g., "I went to the gym"), it patches data directly.
For structural changes (e.g., "add a sankey chart"), it generates HTML/CSS.
"""

import json
import logging
import os
import re
from openai import OpenAI

from lifeboard.board_engine import (
    load_board, save_board, get_board_summary,
    add_widget, update_widget, remove_widget,
    set_theme, replace_board, checkpoint_for_undo,
    auto_layout,
)
from lifeboard.widget_presets import instantiate_preset, list_presets
from lifeboard.data_providers import list_provider_specs
from config import get_default_resolution, load_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the AI engine behind Lifeboard, a dynamic wallpaper app. The user's desktop wallpaper is a customizable dashboard rendered from HTML/CSS widgets.

You receive the current board state and a user request. You respond with a JSON array of commands to execute.

## Rules
- Positions and sizes are in PERCENTAGE of screen (0-100). Use these to lay out widgets.
- CRITICAL: HTML templates must be FULLY SELF-CONTAINED with all data baked in. Do NOT use template syntax like {{#items}}, {{^done}}, mustache, or handlebars loops/conditionals. The renderer does simple {{key}} replacement for flat string/number values only. For lists and complex data, generate the full HTML with all items hardcoded.
- Example: for a todo list, generate `<li>[ ] Build thing</li><li>[x] Test it</li>` directly, NOT `{{#items}}<li>{{label}}</li>{{/items}}`.
- A JS variable `WIDGET_DATA` is injected containing the widget's data object. You can use inline `<script>` tags that read from `WIDGET_DATA` to dynamically build HTML — this DOES work.
- For complex visualizations (charts, graphs), generate inline SVG or use CSS-only techniques. No external libraries or CDN links.
- Keep CSS scoped — prefix selectors with the widget's id or use unique class names.
- The board has a global theme CSS applied. Your widget CSS should work with it (use CSS variables like var(--fg), var(--bg), var(--accent), var(--font) when available).
- When the user asks to resize, move, or rearrange widgets, update positions/sizes to avoid overlaps and keep at least 2% gap between normal widgets. Do not intentionally overlap or touch normal widgets; only use layering for explicit background requests.
- When the user asks to change widget content or settings only, do not include position or size updates.
- For todo widgets, prefer preset/data updates and omit size unless the user explicitly asks to resize. Lifeboard sizes todo height from task count, so empty or short todo lists should not be tall columns.
- For data-only updates (e.g., "mark X as done", "I went to the gym"), ALWAYS regenerate the html_template too with the updated data baked in. This ensures the widget renders correctly.
- When asked to change theme, just use the set_theme command.

## Available Commands

Each command is a JSON object with an "action" field:

### add_widget
Add a new widget to the board.
```json
{
  "action": "add_widget",
  "id": "short-unique-id",
  "description": "What this widget shows",
  "position": [x_percent, y_percent],
  "size": [width_percent, height_percent],
  "data": { ... },
  "html_template": "<div>...</div>",
  "css": ".my-class { ... }",
  "data_provider": "provider-name",
  "z_index": 0,
  "refresh_interval": 300
}
```

### update_widget
Update an existing widget. Include only the fields you want to change.
```json
{
  "action": "update_widget",
  "id": "existing-widget-id",
  "updates": {
    "data": { "key": "new_value" },
    "position": [new_x, new_y],
    "size": [new_w, new_h],
    "html_template": "...",
    "css": "..."
  }
}
```

### remove_widget
```json
{
  "action": "remove_widget",
  "id": "widget-to-remove"
}
```

### set_theme
```json
{
  "action": "set_theme",
  "theme": "theme-name"
}
```

### add_preset
Add a widget from a pre-built preset template. Preferred over add_widget for common types.
```json
{
  "action": "add_preset",
  "preset": "preset-name",
  "position": [x_percent, y_percent],
  "size": [width_percent, height_percent],
  "data_overrides": { "key": "value" }
}
```
size and data_overrides are optional — omit to use preset defaults. For todo presets, omit size unless the user explicitly asks for a specific size.

### replace_board
Full board replacement — use this when the user wants a complete overhaul.
```json
{
  "action": "replace_board",
  "board": { "theme": "...", "resolution": [...], "widgets": [...] }
}
```

### auto_layout
Re-organize existing widgets into a tidy grid. Useful when the user says "re-organize", "clean up layout", or "make it neat".
```json
{
  "action": "auto_layout",
  "columns": 4,
  "gutter": 2.0,
  "base_row_height": 18.0,
  "preserve_spans": true,
  "top_margin": 6.0
}
```
All fields are optional; omit to use sensible defaults. The default keeps stock/crypto compact, sizes todo widgets from task count, keeps a consistent gutter between stacked widgets, avoids treating empty image widgets as backgrounds, and leaves top margin for the macOS menu bar.

## Response Format
Respond with ONLY a JSON array of commands. No explanation, no markdown fences. Just the array.
Example: [{"action": "add_widget", ...}, {"action": "update_widget", ...}]

If the user's request is unclear or you need more info, respond with:
[{"action": "message", "text": "your question here"}]

## Refresh Intervals
Widgets can have a "refresh_interval" field (integer, seconds). The wallpaper auto-refreshes at the shortest interval across all widgets. Only set this on widgets with live data (clock, weather, market data, news, photo galleries). Omit for static widgets (todo, quote). Examples: clock=300, weather=3600.

## Z-Index / Layering
Widgets have a "z_index" field (integer, default 0). Lower values render behind higher values. Use z_index: -1 for background images, 0 for normal widgets, positive values to bring widgets to front.

## Data Providers
Widgets can have a "data_provider" field. When set, the renderer will fetch live data before rendering. Available providers:
{provider_list}

When adding a clock or weather widget, set data_provider to the appropriate value. When adding an image widget, set data_provider to "image" and include file_path in data. The HTML template can use WIDGET_DATA to read the injected values.

## Widget Presets
Pre-built widget templates are available. Use the add_preset action for these — it's simpler and more reliable than generating HTML from scratch.
{preset_list}
When the user asks for a common widget type, prefer add_preset over add_widget.
"""


def _build_system_prompt() -> str:
    """Inject the live preset list so newly added presets are discoverable without editing the prompt."""
    presets = list_presets()
    if presets:
        lines = "\n".join(f"- {p['name']}: {p['description']}" for p in presets)
        block = "Available presets:\n" + lines
    else:
        block = "Available presets: (none)"

    providers = list_provider_specs()
    if providers:
        provider_lines = "\n".join(
            f'- "{p["name"]}" — {p["description"]}. Widget data: {p["widget_data"]}.'
            for p in providers
        )
    else:
        provider_lines = "No data providers are currently registered."

    return (
        SYSTEM_PROMPT
        .replace("{preset_list}", block)
        .replace("{provider_list}", provider_lines)
    )


def parse_ai_response(raw: str) -> list[dict]:
    """Parse the AI's raw text response into a list of command dicts.

    Handles common issues:
    - Markdown code fences
    - Surrounding explanation text
    - Single object instead of array
    - Trailing commas
    - Total parse failure (returns a message command)
    """
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find a JSON array in the text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        candidate = match.group()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try fixing trailing commas
            fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # Try to find a single JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return [json.loads(match.group())]
        except json.JSONDecodeError:
            pass

    # Total failure — return the raw text as a message
    return [{"action": "message", "text": f"Couldn't understand the AI response: {raw[:300]}"}]


def call_ai(user_content: str, api_key: str) -> str:
    """Make the API call and return raw text. Separated for testability."""
    config = load_config()
    base_url = config.get("ai_base_url", "https://openrouter.ai/api/v1")
    model = config.get("ai_model", "anthropic/claude-sonnet-4.6")

    if "anthropic.com" in base_url:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=8192,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content.strip()


MAX_RETRIES = 2


def interpret(user_message: str, api_key: str, board: dict | None = None) -> list[dict]:
    """Send the user message + board state to the AI via OpenRouter, get back commands.

    Retries up to MAX_RETRIES times if the response can't be parsed as valid commands.
    """
    if board is None:
        board = load_board()

    board_context = get_board_summary(board)
    full_board_json = json.dumps(board, indent=2)

    user_content = f"""## Current Board State
{board_context}

## Full Board JSON (for reference)
{full_board_json}

## User Request
{user_message}"""

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = call_ai(user_content, api_key)
            commands = parse_ai_response(raw)

            # Check if we got a "couldn't understand" message — that means parsing failed
            if (len(commands) == 1
                    and commands[0].get("action") == "message"
                    and "couldn't understand" in commands[0].get("text", "").lower()):
                if attempt < MAX_RETRIES:
                    logger.warning(f"AI response not parseable (attempt {attempt + 1}), retrying")
                    user_content += "\n\n[SYSTEM: Your previous response was not valid JSON. Respond with ONLY a JSON array of commands, no explanation.]"
                    continue
                return commands

            return commands

        except Exception as e:
            last_error = e
            logger.error(f"AI call failed (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES:
                continue

    return [{"action": "message", "text": f"Failed to process request after {MAX_RETRIES + 1} attempts: {last_error}"}]


def execute_commands(commands: list[dict], board: dict | None = None) -> str | None:
    """Execute a list of commands against the board. Returns a message if the AI has one."""
    if board is None:
        board = load_board()

    # Take a single undo snapshot for this whole plan, not per save inside it.
    checkpoint_for_undo()

    message = None

    for cmd in commands:
        action = cmd.get("action")

        if action == "add_widget":
            add_widget(
                board,
                description=cmd["description"],
                position=cmd["position"],
                size=cmd["size"],
                data=cmd.get("data", {}),
                html_template=cmd.get("html_template", ""),
                css=cmd.get("css", ""),
                widget_id=cmd.get("id"),
                data_provider=cmd.get("data_provider"),
                z_index=cmd.get("z_index", 0),
                refresh_interval=cmd.get("refresh_interval"),
            )

        elif action == "add_preset":
            widget = instantiate_preset(
                cmd["preset"],
                cmd["position"],
                cmd.get("size"),
                cmd.get("data_overrides"),
                refresh_interval=cmd.get("refresh_interval"),
            )
            if widget:
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

        elif action == "update_widget":
            update_widget(board, cmd["id"], cmd.get("updates", {}))

        elif action == "remove_widget":
            remove_widget(board, cmd["id"])

        elif action == "set_theme":
            try:
                set_theme(board, cmd["theme"])
            except ValueError as e:
                message = str(e)
                logger.warning(f"set_theme rejected: {e}")

        elif action == "replace_board":
            new_board = cmd["board"]
            new_board.setdefault("resolution", board.get("resolution", get_default_resolution()))
            replace_board(board, new_board)

        elif action == "message":
            message = cmd.get("text", "")

        elif action == "auto_layout":
            auto_layout(
                board,
                columns=cmd.get("columns", 4),
                gutter=float(cmd.get("gutter", 2.0)),
                base_row_height=float(cmd.get("base_row_height", 18.0)),
                preserve_spans=bool(cmd.get("preserve_spans", True)),
                top_margin=float(cmd.get("top_margin", 6.0)),
            )

    return message


async def process_request(user_message: str, api_key: str) -> str | None:
    """Full pipeline: interpret user message → execute commands → re-render wallpaper."""
    from lifeboard.renderer import render_and_set_wallpaper

    board = load_board()
    commands = interpret(user_message, api_key, board)
    message = execute_commands(commands, board)

    if message:
        return message

    # Re-render after changes
    board = load_board()  # reload to get saved state
    await render_and_set_wallpaper(board)
    return None
