from __future__ import annotations

import sys
import threading
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

_SPECIAL_TO_CHAR = {
    "Space": "space",
    "Plus": "+",
    "Minus": "-",
    "Equal": "=",
    "Comma": ",",
    "Period": ".",
    "Slash": "/",
    "Backslash": "\\",
    "LeftBracket": "[",
    "RightBracket": "]",
    "Semicolon": ";",
    "Quote": "'",
    "Grave": "`",
    "PageUp": "page up",
    "PageDown": "page down",
}


def to_keyboard_name(key: str) -> str:
    if key in _SPECIAL_TO_CHAR:
        return _SPECIAL_TO_CHAR[key]
    return key.lower()


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    import keyboard as _kb

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = wintypes.BOOL
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    WM_QUIT = 0x0012
    WM_HOTKEY = 0x0312
    WM_APP = 0x8000
    MOD_NOREPEAT = 0x4000
    _OS_KEYS = {
        "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23,
        "PageUp": 0x21, "PageDown": 0x22,
    }

    def _os_vk(name: str) -> int | None:
        if name in _OS_KEYS:
            return _OS_KEYS[name]
        low = str(name).lower()
        if low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            return 0x6F + int(low[1:])
        return None

    class _OsHotkeys:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._jobs: list = []
            self._callbacks: dict[int, Callable[[], None]] = {}
            self._next_id = 1
            self._tid = 0
            self._thread: threading.Thread | None = None
            self._ready = threading.Event()

        def _ensure(self) -> bool:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
            self._thread.start()
            return self._ready.wait(2.0)

        def _run(self) -> None:
            msg = wintypes.MSG()
            _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            self._tid = _kernel32.GetCurrentThreadId()
            self._ready.set()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    cb = self._callbacks.get(int(msg.wParam))
                    if cb is not None:
                        try:
                            cb()
                        except Exception:
                            pass
                elif msg.message == WM_APP:
                    with self._lock:
                        jobs, self._jobs = self._jobs, []
                    for fn, box, done in jobs:
                        try:
                            box["result"] = fn()
                        except Exception:
                            box["result"] = None
                        done.set()

        def _call(self, fn):
            if not self._ensure():
                return None
            done = threading.Event()
            box: dict = {}
            with self._lock:
                self._jobs.append((fn, box, done))
            if not _user32.PostThreadMessageW(self._tid, WM_APP, 0, 0):
                return None
            done.wait(2.0)
            return box.get("result")

        def add(self, vk: int, callback: Callable[[], None]) -> int | None:
            with self._lock:
                hid = self._next_id
                self._next_id += 1
            if not self._call(lambda: bool(_user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk))):
                return None
            self._callbacks[hid] = callback
            return hid

        def remove(self, hid: int) -> None:
            if self._callbacks.pop(hid, None) is not None:
                self._call(lambda: _user32.UnregisterHotKey(None, hid))

        def stop(self) -> None:
            for hid in list(self._callbacks):
                self.remove(hid)
            if self._thread is not None and self._thread.is_alive():
                _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    _OS = _OsHotkeys()

    def key_press(name: str) -> None:
        _kb.press(name)

    def key_release(name: str) -> None:
        _kb.release(name)

    def add_hotkey(name: str, callback: Callable[[], None]):
        vk = _os_vk(name)
        if vk is not None:
            hid = _OS.add(vk, callback)
            if hid is not None:
                return ("os", hid)
        return ("kb", _kb.add_hotkey(to_keyboard_name(name), callback, suppress=False))

    def remove_hotkey(handle) -> None:
        kind, h = handle
        if kind == "os":
            _OS.remove(h)
        else:
            _kb.remove_hotkey(h)

    def unhook_all() -> None:
        _OS.stop()
        try:
            _kb.unhook_all_hotkeys()
        except Exception:
            pass

else:
    from pynput import keyboard as _pk

    _ctl = _pk.Controller()
    _lock = threading.Lock()
    _hotkeys: dict[int, tuple[str, Callable[[], None]]] = {}
    _listener: _pk.Listener | None = None
    _next_id = 1

    _CHAR_TO_SPECIAL = {
        " ": "Space",
        "+": "Plus",
        "-": "Minus",
        "=": "Equal",
        ",": "Comma",
        ".": "Period",
        "/": "Slash",
        "\\": "Backslash",
        "[": "LeftBracket",
        "]": "RightBracket",
        ";": "Semicolon",
        "'": "Quote",
        "`": "Grave",
    }
    _KEY_TO_SPECIAL = {}
    for _attr, _name in (("space", "Space"), ("page_up", "PageUp"), ("page_down", "PageDown"),
                         ("up", "Up"), ("down", "Down"), ("left", "Left"), ("right", "Right"),
                         ("insert", "Insert"), ("delete", "Delete"), ("home", "Home"), ("end", "End")):
        _k = getattr(_pk.Key, _attr, None)
        if _k is not None:
            _KEY_TO_SPECIAL[_k] = _name

    def _canonical(key) -> str | None:
        if isinstance(key, _pk.KeyCode):
            ch = key.char
            if not ch:
                return None
            if ch in _CHAR_TO_SPECIAL:
                return _CHAR_TO_SPECIAL[ch]
            if len(ch) == 1:
                return ch.upper()
            return None
        if key in _KEY_TO_SPECIAL:
            return _KEY_TO_SPECIAL[key]
        name = getattr(key, "name", "") or ""
        if name.startswith("f") and name[1:].isdigit():
            return name.upper()
        return None

    def _on_press(key) -> None:
        name = _canonical(key)
        if name is None:
            return
        with _lock:
            cbs = [cb for (n, cb) in _hotkeys.values() if n == name]
        for cb in cbs:
            try:
                cb()
            except Exception:
                pass

    def _ensure_listener() -> None:
        global _listener
        if _listener is None or not _listener.is_alive():
            _listener = _pk.Listener(on_press=_on_press)
            _listener.daemon = True
            _listener.start()

    def _to_pynput(name: str):
        name = str(name)
        if len(name) == 1:
            return name.lower()
        low = name.lower()
        if low.startswith("f") and low[1:].isdigit():
            return getattr(_pk.Key, low)
        if name in _SPECIAL_TO_CHAR:
            ch = _SPECIAL_TO_CHAR[name]
            if ch == "space":
                return _pk.Key.space
            if ch == "page up":
                return _pk.Key.page_up
            if ch == "page down":
                return _pk.Key.page_down
            return ch
        return getattr(_pk.Key, low, None)

    _MAC_KEYCODES = {
        "esc": 53, "escape": 53, "enter": 36, "return": 36, "tab": 48,
        "space": 49, "backspace": 51, "delete": 51, "end": 119, "home": 115,
        "ctrl": 59, "shift": 56, "alt": 58, "cmd": 55,
        "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23,
        "6": 22, "7": 26, "8": 28, "9": 25, "a": 0, "b": 11, "c": 8, "d": 2,
        "e": 14, "f": 3, "g": 5, "h": 4, "i": 34, "j": 38, "k": 40, "l": 37,
        "m": 46, "n": 45, "o": 31, "p": 35, "q": 12, "r": 15, "s": 1, "t": 17,
        "u": 32, "v": 9, "w": 13, "x": 7, "y": 16, "z": 6,
    }
    if sys.platform == "darwin":
        try:
            from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap as _TAP
        except Exception:
            CGEventCreateKeyboardEvent = None
    else:
        CGEventCreateKeyboardEvent = None

    def _mac_key(name: str, down: bool) -> bool:
        if CGEventCreateKeyboardEvent is None:
            return False
        code = _MAC_KEYCODES.get(str(name).lower())
        if code is None:
            return False
        CGEventPost(_TAP, CGEventCreateKeyboardEvent(None, code, down))
        return True

    def key_press(name: str) -> None:
        if _mac_key(name, True):
            return
        k = _to_pynput(name)
        if k is not None:
            _ctl.press(k)

    def key_release(name: str) -> None:
        if _mac_key(name, False):
            return
        k = _to_pynput(name)
        if k is not None:
            _ctl.release(k)

    def add_hotkey(name: str, callback: Callable[[], None]):
        global _next_id
        with _lock:
            handle = _next_id
            _next_id += 1
            _hotkeys[handle] = (str(name), callback)
        _ensure_listener()
        return handle

    def remove_hotkey(handle) -> None:
        with _lock:
            _hotkeys.pop(handle, None)

    def unhook_all() -> None:
        global _listener
        with _lock:
            _hotkeys.clear()
        if _listener is not None:
            try:
                _listener.stop()
            except Exception:
                pass
            _listener = None
