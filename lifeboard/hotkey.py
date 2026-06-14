"""
Global hotkey registration via Carbon RegisterEventHotKey.

Loaded at app start. No accessibility permission required.
"""

import ctypes
import logging
from ctypes import (
    CFUNCTYPE, POINTER, Structure, byref,
    c_int32, c_uint32, c_void_p,
)
from typing import Callable

_CMD = 1 << 8
_SHIFT = 1 << 9
_OPTION = 1 << 11
_CONTROL = 1 << 12

_MODIFIERS = {
    "cmd": _CMD, "command": _CMD,
    "shift": _SHIFT,
    "alt": _OPTION, "opt": _OPTION, "option": _OPTION,
    "ctrl": _CONTROL, "control": _CONTROL,
}

_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "return": 36, "tab": 48, "space": 49, "escape": 53, "esc": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "left": 123, "right": 124, "down": 125, "up": 126,
}


def parse_hotkey(combo: str) -> tuple[int, int]:
    """Parse 'cmd+shift+l' into (modifier_mask, virtual_keycode).

    Raises ValueError on empty input, unknown tokens, missing key,
    or multiple non-modifier keys.
    """
    if not combo or not combo.strip():
        raise ValueError("empty hotkey string")

    tokens = [t.strip().lower() for t in combo.split("+") if t.strip()]
    if not tokens:
        raise ValueError(f"empty hotkey: {combo!r}")

    mods = 0
    keycode: int | None = None
    for tok in tokens:
        if tok in _MODIFIERS:
            mods |= _MODIFIERS[tok]
        elif tok in _KEYCODES:
            if keycode is not None:
                raise ValueError(f"multiple non-modifier keys in {combo!r}")
            keycode = _KEYCODES[tok]
        else:
            raise ValueError(f"unknown token {tok!r} in {combo!r}")

    if keycode is None:
        raise ValueError(f"no key in {combo!r} (modifiers only)")

    return mods, keycode


class _EventHotKeyID(Structure):
    _fields_ = [("signature", c_uint32), ("id", c_uint32)]


class _EventTypeSpec(Structure):
    _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]


_EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
_EVENT_HOTKEY_PRESSED = 5  # kEventHotKeyPressed
_HOTKEY_SIGNATURE = 0x4C424B59  # 'LBKY'

_HANDLER_PROTO = CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)


class HotkeyListener:
    """Registers a global hotkey via Carbon.

    Callback fires on the application main run loop (the same loop
    rumps drives), so the callback should not block — spawn a thread
    if it does heavy work.
    """

    def __init__(self):
        self._carbon = None
        self._hotkey_ref = c_void_p()
        self._handler_ref = c_void_p()
        self._handler_callback = None
        self._user_callback: Callable[[], None] | None = None
        self._registered = False

    def _load_carbon(self):
        if self._carbon is not None:
            return self._carbon
        try:
            carbon = ctypes.CDLL(
                "/System/Library/Frameworks/Carbon.framework/Carbon"
            )
        except OSError as e:
            logging.error(f"Failed to load Carbon framework: {e}")
            return None
        carbon.GetApplicationEventTarget.restype = c_void_p
        carbon.RegisterEventHotKey.argtypes = [
            c_uint32, c_uint32, _EventHotKeyID, c_void_p, c_uint32,
            POINTER(c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = c_int32
        carbon.InstallEventHandler.argtypes = [
            c_void_p, _HANDLER_PROTO, c_uint32,
            POINTER(_EventTypeSpec), c_void_p, POINTER(c_void_p),
        ]
        carbon.InstallEventHandler.restype = c_int32
        carbon.UnregisterEventHotKey.argtypes = [c_void_p]
        carbon.UnregisterEventHotKey.restype = c_int32
        carbon.RemoveEventHandler.argtypes = [c_void_p]
        carbon.RemoveEventHandler.restype = c_int32
        self._carbon = carbon
        return carbon

    def start(self, combo: str, callback: Callable[[], None]) -> bool:
        """Register the hotkey. Returns True on success, False otherwise."""
        if self._registered:
            self.stop()

        try:
            mods, keycode = parse_hotkey(combo)
        except ValueError as e:
            logging.error(f"Invalid hotkey {combo!r}: {e}")
            return False

        carbon = self._load_carbon()
        if carbon is None:
            return False

        self._user_callback = callback

        def _c_handler(call_ref, event_ref, user_data):
            try:
                if self._user_callback:
                    self._user_callback()
            except Exception:
                logging.exception("Hotkey callback raised")
            return 0  # noErr

        self._handler_callback = _HANDLER_PROTO(_c_handler)

        event_type = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED)
        target = carbon.GetApplicationEventTarget()
        handler_ref = c_void_p()
        status = carbon.InstallEventHandler(
            target, self._handler_callback, 1, byref(event_type),
            None, byref(handler_ref),
        )
        if status != 0:
            logging.error(f"InstallEventHandler failed: OSStatus={status}")
            self._handler_callback = None
            return False
        self._handler_ref = handler_ref

        hotkey_id = _EventHotKeyID(_HOTKEY_SIGNATURE, 1)
        hotkey_ref = c_void_p()
        status = carbon.RegisterEventHotKey(
            keycode, mods, hotkey_id, target, 0, byref(hotkey_ref),
        )
        if status != 0:
            logging.error(
                f"RegisterEventHotKey failed: OSStatus={status} for {combo!r}"
            )
            carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = c_void_p()
            self._handler_callback = None
            return False
        self._hotkey_ref = hotkey_ref

        self._registered = True
        return True

    def stop(self):
        if not self._registered or self._carbon is None:
            return
        if self._hotkey_ref:
            self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            self._hotkey_ref = c_void_p()
        if self._handler_ref:
            self._carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = c_void_p()
        self._handler_callback = None
        self._user_callback = None
        self._registered = False
