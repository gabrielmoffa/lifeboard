"""
Lifeboard — macOS menu bar app.

Sits in the top bar with an icon. Click to open a text input.
Type what you want, the AI updates your wallpaper.
"""

import asyncio
import glob
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
import rumps

from lifeboard.auto_refresh import NetworkChangeMonitor, RefreshTimer

LOG_PATH = os.path.expanduser("~/.lifeboard/lifeboard.log")
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

from config import load_config, save_config, get_api_key
import config as config_module
from lifeboard.ai_interpreter import process_request
from lifeboard.board_engine import (
    load_board, checkpoint_for_undo, auto_layout, list_available_themes, set_theme,
)
from lifeboard.desktop_backdrop import DesktopBackdrop
from lifeboard.hotkey import HotkeyListener
from lifeboard.iphone_server import IPhoneServer
from lifeboard.layout_editor import LayoutEditor
from lifeboard.renderer import render_and_set_wallpaper, reapply_current_wallpaper
from lifeboard.telegram_worker import TelegramWorker


WAKE_CHECK_INTERVAL = 15
WAKE_GAP_SECONDS = 90
WAKE_REAPPLY_DELAYS = (0, 15, 60)
STARTUP_REAPPLY_DELAYS = (5, 30, 120)
DISPLAY_CHECK_INTERVAL = 10
BACKDROP_REFRESH_INTERVAL = 5


def ask_input(title: str, message: str) -> str | None:
    """Show the standalone input dialog and return submitted text."""
    dialog_path = os.path.join(LIFEBOARD_DIR, "input_dialog.py")
    try:
        result = subprocess.run(
            [sys.executable, dialog_path, title, message],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None


def show_notification(title: str, message: str):
    """Show a macOS notification via osascript for reliability."""
    # Escape quotes for AppleScript
    safe_title = title.replace('\\', '\\\\').replace('"', '\\"')
    safe_msg = message.replace('\\', '\\\\').replace('"', '\\"')
    subprocess.run([
        "osascript", "-e",
        f'display notification "{safe_msg}" with title "{safe_title}"'
    ], capture_output=True)


LIFEBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(LIFEBOARD_DIR)


class LifeboardApp(rumps.App):
    def __init__(self):
        super().__init__("Lifeboard", title="◉")
        self.config = load_config()
        self._start_time = time.time()
        self._last_wake_check = time.time()
        self._wake_reapply_running = False
        self._reapply_pending = False
        self._last_display_topology = None
        self._busy = False
        self._process_lock = threading.Lock()
        self._desktop_backdrop = DesktopBackdrop(os.path.join(config_module.OUTPUT_DIR, "wallpaper.png"))
        self._layout_editor = LayoutEditor()
        self._telegram_worker = TelegramWorker(
            self.config,
            notify=show_notification,
            process_prompt=self._process_telegram_prompt_sync,
        )
        self._refresh_timer = RefreshTimer(self._do_refresh, board_loader=load_board)
        self._network_monitor = NetworkChangeMonitor(self._do_refresh)
        self._auto_refresh_item = rumps.MenuItem(
            "Auto-Refresh", callback=self.toggle_auto_refresh
        )
        self._auto_refresh_item.state = True
        self._theme_items = {}
        self._theme_menu = self._build_theme_menu()
        self.menu = [
            rumps.MenuItem("Update Board...", callback=self.open_input),
            rumps.MenuItem("Re-render Wallpaper", callback=self.rerender),
            self._theme_menu,
            rumps.MenuItem("Reset Layout", callback=self.auto_organize_layout),
            rumps.MenuItem("Open Layout Editor...", callback=self.open_layout_editor),
            None,
            self._auto_refresh_item,
            None,
            rumps.MenuItem("Set OpenRouter Key...", callback=self.set_api_key_menu),
            rumps.MenuItem("Set Finnhub Key...", callback=self.set_finnhub_key_menu),
            None,
            rumps.MenuItem("Restart Lifeboard", callback=self.restart_self),
        ]
        self._wake_timer = rumps.Timer(self._tick_wake, WAKE_CHECK_INTERVAL)
        self._display_timer = rumps.Timer(self._tick_display_watchdog, DISPLAY_CHECK_INTERVAL)
        self._backdrop_timer = rumps.Timer(self._tick_backdrop, BACKDROP_REFRESH_INTERVAL)
        self._staleness_timer = rumps.Timer(self._tick_staleness, 30)
        self._wake_timer.start()
        self._display_timer.start()
        self._backdrop_timer.start()
        self._staleness_timer.start()
        self._refresh_timer.start()
        self._network_monitor.start()
        self._telegram_worker.start()
        self._iphone_server = IPhoneServer()
        try:
            host, port = self._iphone_server.start()
            logging.info(f"iPhone server listening on {host}:{port}/wallpaper.png")
        except OSError as e:
            logging.warning(f"iPhone server failed to start: {e}")

        combo = self.config.get("hotkey", "cmd+shift+l")
        self._hotkey = HotkeyListener()
        if not self._hotkey.start(combo, self._on_hotkey):
            show_notification(
                "Lifeboard",
                f"Hotkey '{combo}' unavailable — edit ~/.lifeboard/config.json",
            )
        self._reapply_wallpaper_sequence("Startup", STARTUP_REAPPLY_DELAYS)
        self._tick_backdrop(None)

    def _get_api_key(self) -> str | None:
        key = get_api_key(self.config)
        if not key:
            show_notification("Lifeboard", "Set AI_API_KEY env var or use Set AI API Key in the menu.")
            return None
        return key

    @rumps.clicked("Update Board...")
    def open_input(self, _):
        self._run_update_flow()

    def _on_hotkey(self):
        self._run_update_flow()

    def _run_update_flow(self):
        if self._busy:
            return
        api_key = self._get_api_key()
        if not api_key:
            return

        self._busy = True

        def _thread():
            try:
                text = ask_input("Lifeboard", "What do you want to change?")
                if not text:
                    return

                self.title = "◎ Thinking..."
                show_notification("Lifeboard", "Processing your request...")

                msg = self._process_prompt_sync(text)

                self.title = "◉"
                self._sync_theme_menu_state()
                show_notification("Lifeboard", msg or "Wallpaper updated!")

            except Exception as e:
                logging.error(traceback.format_exc())
                self.title = "◉"
                show_notification("Lifeboard Error", str(e)[:200])
            finally:
                self._busy = False

        threading.Thread(target=_thread, daemon=True).start()

    def _build_theme_menu(self):
        theme_menu = rumps.MenuItem("Themes")
        for theme in list_available_themes():
            item = rumps.MenuItem(theme, callback=self._select_theme)
            theme_menu.add(item)
            self._theme_items[theme] = item
        self._sync_theme_menu_state()
        return theme_menu

    def _sync_theme_menu_state(self):
        current_theme = load_board().get("theme")
        for theme, item in self._theme_items.items():
            item.state = theme == current_theme

    def _select_theme(self, sender):
        theme = sender.title
        if self._busy:
            return
        self._busy = True
        self.title = "◎ Rendering..."

        def _thread():
            try:
                checkpoint_for_undo()
                board = load_board()
                set_theme(board, theme)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(render_and_set_wallpaper(board))
                loop.close()

                self.title = "◉"
                self._sync_theme_menu_state()
                show_notification("Lifeboard", f"Theme changed to {theme}.")
            except Exception as e:
                logging.error(traceback.format_exc())
                self.title = "◉"
                show_notification("Lifeboard Error", str(e)[:200])
            finally:
                self._busy = False

        threading.Thread(target=_thread, daemon=True).start()

    def _process_prompt_sync(self, text: str) -> str | None:
        api_key = self._get_api_key()
        if not api_key:
            return "Lifeboard has no AI API key configured."
        with self._process_lock:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(process_request(text, api_key))
            finally:
                loop.close()

    def _process_telegram_prompt_sync(self, text: str) -> str | None:
        before = self._board_mtime()
        result = self._process_prompt_sync(text)
        after = self._board_mtime()
        if result:
            return result
        if before == after:
            return "I tried to process that, but the board did not change."
        return None

    def _board_mtime(self) -> float | None:
        try:
            return os.path.getmtime(config_module.BOARD_FILE)
        except FileNotFoundError:
            return None

    @rumps.clicked("Re-render Wallpaper")
    def rerender(self, _):
        self.title = "◎ Rendering..."

        def _thread():
            try:
                board = load_board()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(render_and_set_wallpaper(board))
                loop.close()
                self.title = "◉"
                show_notification("Lifeboard", "Wallpaper updated!")
            except Exception as e:
                self.title = "◉"
                show_notification("Lifeboard Error", str(e)[:200])

        threading.Thread(target=_thread, daemon=True).start()

    @rumps.clicked("Reset Layout")
    def auto_organize_layout(self, _):
        self.title = "◎ Resetting..."

        def _thread():
            try:
                board = load_board()
                checkpoint_for_undo()
                # Use defaults; if we want, we could make these configurable later
                auto_layout(board)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                from lifeboard.renderer import render_and_set_wallpaper
                loop.run_until_complete(render_and_set_wallpaper(board))
                loop.close()
                self.title = "◉"
                show_notification("Lifeboard", "Layout reset.")
            except Exception as e:
                self.title = "◉"
                show_notification("Lifeboard Error", str(e)[:200])

        threading.Thread(target=_thread, daemon=True).start()

    @rumps.clicked("Open Layout Editor...")
    def open_layout_editor(self, _):
        try:
            url = self._layout_editor.start()
            webbrowser.open(url)
            show_notification("Lifeboard", "Layout editor opened.")
        except Exception as e:
            logging.error(traceback.format_exc())
            show_notification("Lifeboard Error", str(e)[:200])

    def _do_refresh(self):
        def _thread():
            try:
                board = load_board()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(render_and_set_wallpaper(board))
                loop.close()
            except Exception as e:
                logging.error(traceback.format_exc())

        threading.Thread(target=_thread, daemon=True).start()

    def _reapply_wallpaper_after_wake(self):
        self._reapply_wallpaper_sequence("Wake refresh", WAKE_REAPPLY_DELAYS)

    def _reapply_wallpaper_sequence(self, label: str, delays: tuple[int, ...]):
        if self._wake_reapply_running:
            self._reapply_pending = True
            logging.info(f"{label}: reapply already running, queued follow-up")
            return
        self._wake_reapply_running = True

        def _thread():
            try:
                current_label = label
                current_delays = delays
                while True:
                    self._reapply_pending = False
                    for delay in current_delays:
                        if delay:
                            time.sleep(delay)
                        try:
                            path = reapply_current_wallpaper()
                            if path:
                                logging.info(f"{current_label}: reapplied wallpaper from {path}")
                            else:
                                logging.info(f"{current_label}: no rendered wallpaper found, rendering board")
                                board = load_board()
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                try:
                                    loop.run_until_complete(render_and_set_wallpaper(board))
                                finally:
                                    loop.close()
                        except Exception:
                            logging.error(traceback.format_exc())

                    if not self._reapply_pending:
                        break
                    current_label = "Queued wallpaper repair"
                    current_delays = (0, 10, 30)
                    logging.info("Queued wallpaper repair: running follow-up sequence")
            except Exception:
                logging.error(traceback.format_exc())
            finally:
                self._wake_reapply_running = False

        threading.Thread(target=_thread, daemon=True).start()

    def _display_signature(self):
        try:
            from AppKit import NSScreen, NSWorkspace
        except Exception:
            return None

        workspace = NSWorkspace.sharedWorkspace()
        signature = []
        for screen in NSScreen.screens():
            frame = screen.frame()
            url = workspace.desktopImageURLForScreen_(screen)
            path = url.path() if url else ""
            signature.append((
                screen.localizedName(),
                int(frame.origin.x),
                int(frame.origin.y),
                int(frame.size.width),
                int(frame.size.height),
                path,
            ))
        return tuple(sorted(signature))

    def _wallpaper_urls_need_reapply(self, signature) -> bool:
        if not signature:
            return False
        output_dir = os.path.abspath(config_module.OUTPUT_DIR)
        for *_, path in signature:
            if not path:
                return True
            if not os.path.abspath(path).startswith(output_dir):
                return True
            if "/wallpaper_macos_" not in path:
                return True
            if not os.path.exists(path):
                return True
        return False

    def _system_wallpaper_url_need_reapply(self) -> bool:
        result = subprocess.run(
            ["defaults", "read", "com.apple.wallpaper", "SystemWallpaperURL"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return True

        url = result.stdout.strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "file":
            return True

        path = urllib.parse.unquote(parsed.path)
        output_dir = os.path.abspath(config_module.OUTPUT_DIR)
        if not os.path.abspath(path).startswith(output_dir):
            return True
        if "/wallpaper_macos_" not in path:
            return True
        if not os.path.exists(path):
            return True
        return False

    def _display_topology(self, signature):
        if not signature:
            return None
        return tuple(entry[:-1] for entry in signature)

    def toggle_auto_refresh(self, sender):
        if self._refresh_timer.running:
            self._refresh_timer.stop()
            sender.state = False
        else:
            self._refresh_timer.start()
            sender.state = True

    @rumps.clicked("Set OpenRouter Key...")
    def set_api_key_menu(self, _):
        key = ask_input("Lifeboard", "Enter your AI API key:")
        if key:
            self.config["ai_api_key"] = key
            save_config(self.config)
            show_notification("Lifeboard", "API key saved!")

    @rumps.clicked("Set Finnhub Key...")
    def set_finnhub_key_menu(self, _):
        key = ask_input("Lifeboard", "Enter your Finnhub API key (free at finnhub.io):")
        if key:
            self.config["finnhub_api_key"] = key
            save_config(self.config)
            show_notification("Lifeboard", "Finnhub API key saved!")

    def _is_stale(self) -> bool:
        try:
            files = glob.glob(os.path.join(LIFEBOARD_DIR, "*.py"))
            files.append(os.path.join(REPO_DIR, "run.py"))
            files.append(os.path.join(REPO_DIR, "config.py"))
            latest = max(os.path.getmtime(f) for f in files if os.path.exists(f))
            return latest > self._start_time
        except Exception:
            return False

    def _tick_staleness(self, _):
        if self._busy:
            return
        self.title = "◉⚠" if self._is_stale() else "◉"

    def _tick_wake(self, _):
        now = time.time()
        elapsed = now - self._last_wake_check
        self._last_wake_check = now
        if elapsed >= WAKE_GAP_SECONDS:
            logging.info(f"Wake refresh: detected timer gap of {elapsed:.1f}s")
            self._reapply_wallpaper_after_wake()

    def _tick_backdrop(self, _):
        try:
            self._desktop_backdrop.refresh()
        except Exception:
            logging.error(traceback.format_exc())

    def _tick_display_watchdog(self, _):
        signature = self._display_signature()
        if signature is None:
            return

        topology = self._display_topology(signature)
        changed = self._last_display_topology is not None and topology != self._last_display_topology
        invalid_urls = self._wallpaper_urls_need_reapply(signature)
        invalid_system_url = self._system_wallpaper_url_need_reapply()
        self._last_display_topology = topology

        if changed or invalid_urls or invalid_system_url:
            logging.info(
                "Display watchdog: "
                f"changed={changed} invalid_urls={invalid_urls} "
                f"invalid_system_url={invalid_system_url} signature={signature}"
            )
            self._reapply_wallpaper_sequence("Display watchdog", (0, 10, 30))

    def restart_self(self, _):
        script = os.path.join(REPO_DIR, "restart.sh")
        if not os.path.exists(script):
            show_notification("Lifeboard Error", "restart.sh not found.")
            return
        show_notification("Lifeboard", "Restarting...")
        subprocess.Popen(["/bin/bash", script], cwd=REPO_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    @rumps.clicked("Set CoinGecko Key...")
    def set_coingecko_key_menu(self, _):
        key = ask_input("Lifeboard", "Enter your CoinGecko API key:")
        if key:
            self.config["coingecko_api_key"] = key
            save_config(self.config)
            show_notification("Lifeboard", "CoinGecko API key saved!")


def main():
    LifeboardApp().run()


if __name__ == "__main__":
    main()
