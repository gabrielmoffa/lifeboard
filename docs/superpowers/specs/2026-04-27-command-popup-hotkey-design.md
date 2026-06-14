# Command Popup Hotkey — Design

**Date:** 2026-04-27
**Status:** Approved, pending implementation plan

## Goal

Press a configurable global hotkey from anywhere in macOS to open Lifeboard's existing input dialog, type a request, and have the AI update the wallpaper — without clicking the menu bar icon.

Default hotkey: `cmd+shift+l`. User overrides it by editing `~/.lifeboard/config.json`.

## Non-goals

- No new popup UI, autocomplete, recent-commands history, or quick-action shortcuts. The popup is the existing `input_dialog.py` NSPanel, unchanged.
- No menu item or in-app UI for changing the hotkey. Config-file edit only.
- No accessibility-permission-based approaches (`pynput`, `NSEvent` global monitor, `CGEventTap`). The hotkey must work without prompting for system permissions on first launch.

## Approach

Use Carbon's `RegisterEventHotKey` API via `ctypes`. This is the canonical macOS API for menu bar app hotkeys: no accessibility permission required, the keystroke is consumed (does not leak to the foreground app), and it works while Lifeboard is in the background. Carbon is technically deprecated but stable on current macOS releases.

## Components

### `lifeboard/hotkey.py` (new, ~150 lines)

Single-purpose module wrapping Carbon hotkey registration.

**`parse_hotkey(combo: str) -> (mods_mask: int, keycode: int)`**

Parses a string like `"cmd+shift+l"` into a Carbon modifier mask and virtual keycode.

- Modifier tokens: `cmd`, `shift`, `alt`, `opt` (alias for alt), `ctrl`. Case-insensitive. Order-insensitive.
- Key tokens: `a`–`z`, `0`–`9`, `f1`–`f12`, `space`, `return`, `escape`, `tab`, `left`, `right`, `up`, `down`.
- Exactly one non-modifier key required; zero or more modifiers.
- Raises `ValueError` with a clear message on unknown tokens, missing key, or multiple keys.

**`class HotkeyListener`**

Wraps `RegisterEventHotKey` + `InstallEventHandler` from `Carbon.framework` loaded via `ctypes.CDLL`.

- `start(combo: str, callback: Callable[[], None]) -> bool` — parses combo, registers hotkey, installs event handler. Returns `True` on success, `False` if registration fails (e.g., combo already taken by another app). On failure, logs the Carbon `OSStatus`.
- `stop() -> None` — calls `UnregisterEventHotKey` and removes the event handler. Idempotent.
- The Carbon event handler is installed against `GetApplicationEventTarget()`, so the callback fires on the application main run loop — the same loop rumps drives. The callback itself does no work beyond spawning the same daemon thread used today by `open_input`, so blocking on the main thread is not a concern.

### `lifeboard/app.py` (modified)

- Refactor `open_input` body into a private `_run_update_flow(self) -> None` method that does: get API key → show dialog → process → render → notify. Both the menu item and the hotkey call this method.
- Add `self._busy = False` flag. `_run_update_flow` checks-and-sets at the top, clears in a `finally`. Hotkey presses while busy are ignored (no second dialog, no second AI call).
- In `__init__`: read `config.get("hotkey", "cmd+shift+l")`, instantiate `HotkeyListener`, call `start(combo, self._on_hotkey)`. If `start` returns `False`, show a one-shot notification: `"Hotkey '<combo>' is in use — edit ~/.lifeboard/config.json"`. App continues to run normally.
- `_on_hotkey` simply spawns the same daemon thread that `open_input` does, calling `_run_update_flow`.
- On app quit (rumps `quit_application` hook or `atexit`): call `listener.stop()`.

### `config.py` (modified)

Add `"hotkey": "cmd+shift+l"` to the default-config dict returned by `load_config` when no config file exists. Existing configs without the field fall through to the same default at read time (`config.get("hotkey", "cmd+shift+l")`).

### `tests/test_hotkey.py` (new)

Unit tests for `parse_hotkey` only. Carbon registration cannot be unit-tested in isolation; that's manual smoke-test territory.

Cases:
- Valid: `"cmd+shift+l"`, `"L"`, `"cmd+space"`, `"ctrl+alt+f5"`, `"opt+return"` (opt aliases alt).
- Invalid: `""`, `"cmd"` (no key), `"cmd+a+b"` (two keys), `"meta+a"` (unknown modifier), `"cmd+foo"` (unknown key).
- Case-insensitivity: `"CMD+SHIFT+L"` parses identically to `"cmd+shift+l"`.
- Order-insensitivity: `"shift+cmd+l"` parses identically to `"cmd+shift+l"`.

## Failure modes

| Failure | Behavior |
|---|---|
| Hotkey combo already taken by another app | `RegisterEventHotKey` returns non-zero `OSStatus`. Log it, show a one-shot notification at startup, app keeps running without a hotkey. |
| Invalid combo string in config | `parse_hotkey` raises `ValueError`. App logs the error, falls back to the default `"cmd+shift+l"`, retries registration once. If that also fails, behave as the row above. |
| `Carbon.framework` fails to load (unlikely on macOS) | Wrap `ctypes.CDLL` call in try/except. Log, app keeps running without a hotkey. |
| Hotkey pressed while previous request still processing | `self._busy` is `True`. Ignore. No notification (would be noisy). |
| App quit without stop | OS reclaims the hotkey registration when the process dies. `stop()` on quit is best-effort cleanup, not required for correctness. |

## Files touched

- `lifeboard/hotkey.py` — new, ~150 lines.
- `lifeboard/app.py` — refactor `open_input` into `_run_update_flow`, add `_busy` flag, wire `HotkeyListener` in `__init__`, stop on quit. Net ~25 lines added.
- `config.py` — one new default key.
- `tests/test_hotkey.py` — new, parser tests only.

## Out of scope (explicitly)

- Recent-commands history, autocomplete, structured quick actions (`:tick X`). These would belong in a follow-up if the basic hotkey-to-dialog flow proves valuable.
- A "Set Hotkey..." menu item. Config-file edit is the chosen UX.
- Cross-platform support. macOS only.
