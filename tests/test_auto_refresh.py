import time
import pytest
from unittest.mock import MagicMock, patch
from lifeboard.auto_refresh import (
    NetworkChangeMonitor,
    RefreshTimer,
    get_min_refresh_interval,
    is_network_available,
)


class TestRefreshTimer:
    def _make_board_loader(self, widgets=None):
        board = {"theme": "hacker", "resolution": [5120, 3200], "widgets": widgets or []}
        return lambda: board

    def test_create_timer(self):
        callback = MagicMock()
        timer = RefreshTimer(callback, board_loader=self._make_board_loader())
        assert timer.running is False

    def test_start_sets_running(self):
        callback = MagicMock()
        timer = RefreshTimer(callback, board_loader=self._make_board_loader())
        timer.start()
        assert timer.running is True
        timer.stop()

    def test_stop_clears_running(self):
        callback = MagicMock()
        timer = RefreshTimer(callback, board_loader=self._make_board_loader())
        timer.start()
        timer.stop()
        assert timer.running is False

    def test_stop_when_not_running_is_safe(self):
        callback = MagicMock()
        timer = RefreshTimer(callback, board_loader=self._make_board_loader())
        timer.stop()
        assert timer.running is False


class TestNetworkChangeMonitor:
    @patch("lifeboard.auto_refresh.subprocess.run")
    def test_network_check_returns_false_without_interfaces(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Network interfaces: 0")
        assert is_network_available() is False

    @patch("lifeboard.auto_refresh.subprocess.run")
    def test_network_check_returns_true_with_interfaces(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Network interfaces: en0")
        assert is_network_available() is True

    def test_triggers_callback_when_network_returns(self):
        callback = MagicMock()
        states = iter([False, True, True])
        monitor = NetworkChangeMonitor(
            callback,
            check_interval=0.01,
            network_check=lambda: next(states, True),
        )
        monitor.start()
        time.sleep(0.05)
        monitor.stop()
        callback.assert_called_once()


class TestGetMinRefreshInterval:
    def test_no_widgets(self):
        assert get_min_refresh_interval({"widgets": []}) is None

    def test_no_intervals_set(self):
        board = {"widgets": [{"id": "a"}, {"id": "b"}]}
        assert get_min_refresh_interval(board) is None

    def test_single_interval(self):
        board = {"widgets": [{"id": "a", "refresh_interval": 300}]}
        assert get_min_refresh_interval(board) == 300

    def test_picks_minimum(self):
        board = {"widgets": [
            {"id": "a", "refresh_interval": 3600},
            {"id": "b", "refresh_interval": 60},
            {"id": "c"},
        ]}
        assert get_min_refresh_interval(board) == 60
