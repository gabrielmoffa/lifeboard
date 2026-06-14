"""
Auto-refresh — periodically re-renders the wallpaper based on per-widget refresh intervals.

Each widget can declare a refresh_interval (in seconds). The timer runs at the
shortest interval found across all widgets. If no widget needs refreshing, the
timer stops. The board is re-read each cycle so new widgets are picked up.
"""
import logging
import subprocess
import threading

logger = logging.getLogger(__name__)


def get_min_refresh_interval(board: dict) -> int | None:
    """Return the shortest refresh_interval (seconds) across all widgets, or None if none set."""
    intervals = [
        w["refresh_interval"]
        for w in board.get("widgets", [])
        if w.get("refresh_interval")
    ]
    return min(intervals) if intervals else None


def is_network_available() -> bool:
    """Return whether macOS reports an active network path."""
    try:
        result = subprocess.run(
            ["scutil", "--nwi"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Network check failed: {e}")
        return False
    return result.returncode == 0 and "Network interfaces: 0" not in result.stdout


class NetworkChangeMonitor:
    def __init__(self, callback, check_interval: int = 15, network_check=is_network_available):
        self.callback = callback
        self.check_interval = check_interval
        self.network_check = network_check
        self.running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._was_available: bool | None = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._was_available = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Network monitor started")

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Network monitor stopped")

    def _loop(self):
        while not self._stop_event.is_set():
            available = self.network_check()
            if self._was_available is False and available:
                try:
                    logger.info("Network restored: triggering re-render")
                    self.callback()
                except Exception:
                    logger.exception("Network restore refresh failed")
            self._was_available = available
            self._stop_event.wait(self.check_interval)


class RefreshTimer:
    def __init__(self, callback, board_loader):
        """
        callback: called each tick to re-render the wallpaper.
        board_loader: callable that returns the current board dict.
        """
        self.callback = callback
        self.board_loader = board_loader
        self.running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Auto-refresh started (per-widget intervals)")

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Auto-refresh stopped")

    def _loop(self):
        while not self._stop_event.is_set():
            board = self.board_loader()
            interval = get_min_refresh_interval(board)

            if interval is None:
                # No widgets need refreshing — sleep a bit and check again
                self._stop_event.wait(60)
                continue

            logger.info(f"Auto-refresh: sleeping {interval}s (shortest widget interval)")
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break

            try:
                logger.info("Auto-refresh: triggering re-render")
                self.callback()
            except Exception:
                logger.exception("Auto-refresh: render failed")
