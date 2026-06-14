# Contributing

Thanks for taking a look at Lifeboard. Keep changes small, practical, and easy to verify.

## Local Setup

Lifeboard is macOS-only.

```sh
./setup.sh
```

For manual development:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/python run.py
```

Runtime state lives in `~/.lifeboard`, not in the repository.

## Tests

Run the full suite:

```sh
python3 -m pytest
```

Run a focused test file while iterating:

```sh
python3 -m pytest tests/test_board_engine.py
```

## Development Guidelines

- Keep changes scoped to the requested behavior.
- Update `README.md` when changing setup, configuration, widgets, Telegram behavior, layout workflows, themes, MCP tools, or common usage.
- When changing default widget behavior, update the matching file in `widget_presets/`.
- When adding, removing, or changing a data provider, update both `PROVIDER_REGISTRY` and `PROVIDER_METADATA` in `lifeboard/data_providers.py`.
- Do not commit runtime files from `~/.lifeboard`, API keys, bot tokens, rendered wallpapers, virtual environments, or local agent/editor state.

To pick up app changes locally, restart Lifeboard from the repo root:

```sh
./restart.sh
```

