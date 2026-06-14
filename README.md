# Lifeboard

Lifeboard is a macOS menu bar app that turns your desktop wallpaper into a live, AI-editable dashboard. You can update it from the menu bar, a global hotkey, Telegram, or an MCP client such as Claude Code or Codex.

Lifeboard is currently macOS-only. It stores runtime state, rendered wallpapers, and secrets under `~/.lifeboard`; those files are not meant to be committed.

## Setup

Run the setup script from the project root:

```sh
./setup.sh
```

The script creates `.venv`, installs Python dependencies, installs Playwright Chromium, compiles the wallpaper helper, creates `~/.lifeboard`, registers the MCP server with Claude Code when available, and installs a LaunchAgent so Lifeboard starts on login.

To run the app manually:

```sh
.venv/bin/python run.py
```

Runtime files live in `~/.lifeboard`:

- `config.json`: app settings that are okay to share or back up
- `secrets.json`: private API keys
- `board.json`: current wallpaper layout and widgets
- `output/wallpaper.png`: rendered wallpaper
- `lifeboard.log`, `stdout.log`, `stderr.log`: logs

Repository defaults live in `config.py`; your personal API keys are stored in `~/.lifeboard/secrets.json`, which is outside the repository. Older installs with keys in `~/.lifeboard/config.json` still work, and Lifeboard moves keys to `secrets.json` the next time it saves config.

## AI Provider

Lifeboard uses an OpenAI-compatible chat API by default through OpenRouter.

Set the key from the menu bar with `Set OpenRouter Key...`, or edit `~/.lifeboard/secrets.json`:

```json
{
  "ai_api_key": "your-key"
}
```

Provider settings stay in `~/.lifeboard/config.json`:

```json
{
  "ai_base_url": "https://openrouter.ai/api/v1",
  "ai_model": "anthropic/claude-sonnet-4.6"
}
```

You can also set `AI_API_KEY` in your shell environment. To use another OpenAI-compatible provider, change `ai_base_url` and `ai_model`.

## Everyday Use

Use the menu bar icon, then choose:

- `Update Board...`: type a request and let the AI update the wallpaper.
- `Re-render Wallpaper`: refresh live data and redraw the current board.
- `Themes`: choose a theme and immediately re-render the wallpaper.
- `Reset Layout`: clean up widget positions into the default tidy grid.
- `Open Layout Editor...`: manually drag, resize, and delete widgets.
- `Auto-Refresh`: toggle periodic refreshes for widgets with refresh intervals.

New boards use the `slate` theme by default.

On macOS Tahoe, Lifeboard writes the rendered PNG to both the Desktop and Idle wallpaper layers, updates the `com.apple.wallpaper` `SystemWallpaperURL` fallback, then applies a cache-busted copy through the compiled `set_wallpaper` NSWorkspace helper. Wallpaper writes are serialized and recent cache-busted files are retained because macOS may keep using an older image URL after wake, login, or display changes. Lifeboard also keeps a desktop-level backing window above WallpaperAgent but below desktop icons and normal apps, so the Lifeboard image stays visible when macOS reports the right wallpaper URL but still draws the default wallpaper layer. Lifeboard reapplies the last rendered wallpaper after startup, after wake, when the active display topology changes, when visible wallpaper URLs point away from Lifeboard, or when the system fallback points back to Apple's default wallpaper; repair requests that arrive during an active repair are queued for a follow-up pass. The setter reasserts the Desktop and Idle plist entries multiple times because macOS can rewrite them asynchronously.

The default global hotkey is `cmd+shift+l`. Change it in `~/.lifeboard/config.json`:

```json
{
  "hotkey": "cmd+shift+l"
}
```

Useful prompts:

- `Add a todo list for groceries and make it visible on the left.`
- `Add a photo gallery using my ~/Pictures/Vacation folder.`
- `Make the current todo list softer and more minimal.`
- `Clean up the layout.`
- `Add a weather widget for Tallinn.`
- `Use the minimal theme.`

## Telegram Collaboration

Telegram lets other people contribute to the same wallpaper by sending messages to a group. For example, you can create a group with the Lifeboard bot and your partner, then either of you can say things like `add buy milk to Gabriel's todo list`.

1. In Telegram, message `@BotFather`.
2. Create a bot with `/newbot` and copy the bot token.
3. In BotFather, open `/mybots`, select the bot, go to `Bot Settings` -> `Group Privacy`, and turn privacy off. This lets the bot read normal group messages instead of only commands.
4. Create a Telegram group and add the bot. Add anyone else who should be able to update the wallpaper.
5. Send a test message in the group.
6. Find the group chat id by calling Telegram's `getUpdates` endpoint with your token and reading `message.chat.id`. Group ids are usually negative numbers.
7. Store the bot token in the environment variable named by `telegram_bot_token_env`, which defaults to `MY_LIFEBOARD_BOT`.
8. Put the group id in `~/.lifeboard/config.json`.

Example config:

```json
{
  "telegram_enabled": true,
  "telegram_bot_token_env": "MY_LIFEBOARD_BOT",
  "telegram_group_id": "-1234567890"
}
```

Example shell setup:

```sh
export MY_LIFEBOARD_BOT="123456:telegram-bot-token"
```

Only messages from the configured group id are processed. Lifeboard replies in the group when it finishes or when something fails.

## Widgets

Lifeboard ships with preset widgets in `widget_presets/`. Ask the AI to add one by name or describe what you want.

Current presets:

- `clock`: digital clock with date
- `crypto_ticker`: live crypto price from CoinGecko, tolerant of formatted price strings
- `habit_tracker`: monthly habit grid
- `image`: single local image, useful as a card or background
- `news`: topic-based headlines from Google News RSS
- `photo_library`: cycling gallery from a local folder or an internet topic
- `quote`: daily quote
- `stock_ticker`: live stock price, requires a Finnhub API key
- `todo`: to-do list; height auto-sizes from task count
- `weather`: current weather

Live data providers include `datetime`, `weather`, `crypto`, `stock`, `news`, `image`, and `photo_library`.

Weather widgets use wttr.in with no API key. Set `location` to a city name such as `Tallinn`; set `units` to `metric` for Celsius and km/h or `imperial` for Fahrenheit and mph.

When internet-backed providers cannot fetch fresh data, market and news widgets keep using their last successful provider cache when one exists. The macOS app also watches for the network returning and re-renders shortly after reconnecting, so stock, crypto, news, and remote photo widgets do not have to wait for the next normal refresh interval.

## News

Use `news` for a compact headline widget based on a topic:

```text
Add a news widget about artificial intelligence.
```

The news provider uses Google News RSS search with `topic`, `country`, `language`, and `max_items` widget data. It does not require an API key, but Google News RSS is best-effort rather than a guaranteed public API.

## Photo Galleries

Use `photo_library` for a rotating gallery.

For a local folder:

```text
Add a photo gallery from ~/Pictures/Weekend and refresh it every hour.
```

For an internet topic, Lifeboard tries LoremFlickr first and falls back to Wikimedia Commons if the topic request is blocked or unavailable:

```text
Add a photo gallery with the topic "japanese garden" and show captions.
```

The gallery accepts common image formats such as JPG, PNG, WebP, GIF, and BMP. Its refresh cadence comes from the widget's `refresh_interval`; the preset default is one hour.

Use the `image` preset when you want one specific local file rather than a rotating gallery:

```text
Use /Users/me/Pictures/family.png as a subtle full-screen background image.
```

## Layout

Widget positions and sizes are percentages of the screen, stored in `~/.lifeboard/board.json`. New boards auto-detect the primary display resolution; use the MCP `set_board_resolution` tool only when you need to override that, such as for a non-primary display or unusual wallpaper target.

There are three practical layout workflows:

- Ask the AI: `move the todo list to the top right` or `make the photo bigger`.
- Use `Reset Layout` when the board gets messy.
- Use `Open Layout Editor...` for exact drag-and-drop positioning, resizing, and widget deletion.

Programmatic widget changes clamp positions and sizes to the board. Normal widgets are placed in free space with a default 2% gap when possible, so AI/Telegram/MCP moves should not overlap or touch adjacent widgets. Todo widgets are height-sized from their task count so empty or short lists do not become tall columns. Reset Layout uses the configured gutter between stacked widgets, including compact todos. Manual edits in the layout editor remain exact.

Background images use a low `z_index`, commonly `-1`. Normal widgets use `0`; higher values appear in front.

## Themes and Styling

Themes live in `themes/<name>/global.css`. The app currently includes `dark`, `forest`, `hacker`, `lavender`, `midnight`, `minimal`, `mono`, `neon`, `nord`, `ocean`, `paper`, `rose`, `slate`, `solarized`, `sunset`, `terminal-light`, and `warm`.

Ask the AI to change themes:

```text
Use the minimal theme.
```

To create a new theme, add a folder under `themes/` with a `global.css`. Use the shared CSS tokens documented in `themes/README.md`, including `--bg`, `--fg`, `--accent`, `--surface`, `--border`, and `--font`.

When changing default widget behavior or styling, update the matching file in `widget_presets/` so future widgets get the same behavior.

## Market Data Keys

Stock widgets require a Finnhub API key:

```json
{
  "finnhub_api_key": "your-finnhub-key"
}
```

Crypto widgets can use CoinGecko:

```json
{
  "coingecko_api_key": "your-coingecko-key"
}
```

Store market data keys in `~/.lifeboard/secrets.json`. CoinGecko prices are rendered from the crypto provider output, which may already include thousands separators.

You can set the Finnhub key from the menu bar with `Set Finnhub Key...`. The MCP server also exposes tools for setting Finnhub and CoinGecko keys.

If a stock widget is rendered without a Finnhub key, it displays a short setup message instead of silently showing stale or empty prices. Crypto widgets can run without a CoinGecko key, but setting one can help with rate limits.

If the Mac wakes up offline, stock and crypto widgets keep their last good prices when cached data is available. When Wi-Fi comes back, Lifeboard detects the network transition and triggers a fresh render automatically.

## MCP

Lifeboard exposes an MCP server so agents can inspect and update the board directly.

Run it with:

```sh
.venv/bin/python -m lifeboard.mcp_server
```

Claude Code registration:

```sh
claude mcp add -s user lifeboard -- "$(pwd)/.venv/bin/python" -m lifeboard.mcp_server
```

For other MCP clients, configure a stdio server with:

- Command: `/path/to/lifeboard/.venv/bin/python`
- Args: `-m lifeboard.mcp_server`
- Working directory: `/path/to/lifeboard`

Useful MCP tools include:

- `get_board`, `get_board_json`
- `add_preset_widget`, `add_widget_to_board`
- `update_widget_on_board`, `remove_widget_from_board`
- `change_theme`, `list_themes`
- `reorganize_layout`, `undo_last_change`
- `render_wallpaper`
- `log_habit`

## Maintenance Notes

Keep this README current whenever user-facing setup, configuration, widgets, Telegram behavior, layouts, themes, MCP tools, or common workflows change.

For implementation guidance, see `AGENTS.md`.

## Contributing

Issues and pull requests are welcome. See `CONTRIBUTING.md` for local setup, test commands, and contribution guidelines.

## Security

Do not open public issues with API keys, bot tokens, private board data, or screenshots that expose secrets. See `SECURITY.md` for reporting guidance.

## License

MIT. See `LICENSE`.
