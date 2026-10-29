from __future__ import annotations

import random
import sys
import time

IS_WINDOWS = sys.platform == "win32"

_nudge_mid_sec = 0.01
_nudge_settle_sec = 0.04
_click_hold_sec = 0.04


def apply_mouse_timings(nudge_mid_sec: float, nudge_settle_sec: float, click_hold_sec: float) -> None:
    global _nudge_mid_sec, _nudge_settle_sec, _click_hold_sec
    _nudge_mid_sec = max(0.0, float(nudge_mid_sec))
    _nudge_settle_sec = max(0.0, float(nudge_settle_sec))
    _click_hold_sec = max(0.0, float(click_hold_sec))


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    INPUT_MOUSE = 0
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        )

    class _INPUTUNION(ctypes.Union):
        _fields_ = (("mi", MOUSEINPUT),)

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = (
            ("type", wintypes.DWORD),
            ("u", _INPUTUNION),
        )

    def _send_mouse(flags: int, dx: int = 0, dy: int = 0) -> None:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(int(dx), int(dy), 0, int(flags), 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _set_pos(x: int, y: int) -> None:
        user32.SetCursorPos(int(x), int(y))

    def move_cursor(x: int, y: int) -> None:
        _set_pos(int(x) + 1, int(y) + 1)
        time.sleep(_nudge_mid_sec)
        _set_pos(int(x), int(y))
        time.sleep(_nudge_settle_sec)

    def _left_down() -> None:
        _send_mouse(MOUSEEVENTF_LEFTDOWN)

    def _left_up() -> None:
        _send_mouse(MOUSEEVENTF_LEFTUP)

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    MOUSEEVENTF_ABSOLUTE = 0x8000

    def _wheel(notches: int) -> None:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, (int(notches) * 120) & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    GUI_HOVER_SEC = 0.06
    GUI_PRESS_SEC = 0.05

    def _abs_coords(x: int, y: int) -> tuple[int, int]:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        w = max(2, user32.GetSystemMetrics(78))
        h = max(2, user32.GetSystemMetrics(79))
        return int(round((x - left) * 65535 / (w - 1))), int(round((y - top) * 65535 / (h - 1)))

    def _send_batch(*events: tuple[int, int, int]) -> None:
        arr = (INPUT * len(events))()
        for i, (flags, dx, dy) in enumerate(events):
            arr[i].type = INPUT_MOUSE
            arr[i].mi = MOUSEINPUT(int(dx), int(dy), 0, int(flags), 0, None)
        user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))

    def _win_gui_click(x: int, y: int) -> None:
        x, y = int(x), int(y)
        try:
            user32.ClipCursor(None)
        except Exception:
            pass
        move_cursor(x, y)
        time.sleep(GUI_HOVER_SEC)
        ax, ay = _abs_coords(x, y)
        move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        _send_batch((move, ax, ay), (MOUSEEVENTF_LEFTDOWN, 0, 0))
        time.sleep(max(_click_hold_sec, GUI_PRESS_SEC))
        _send_batch((move, ax, ay), (MOUSEEVENTF_LEFTUP, 0, 0))

elif sys.platform == "darwin":
    from Quartz import (
        CGEventCreate,
        CGEventCreateMouseEvent,
        CGEventCreateScrollWheelEvent,
        CGEventGetLocation,
        CGEventPost,
        CGEventSetIntegerValueField,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseDragged,
        kCGEventLeftMouseUp,
        kCGEventMouseMoved,
        kCGHIDEventTap,
        kCGMouseButtonLeft,
        kCGMouseEventClickState,
        kCGScrollEventUnitLine,
    )

    _down = False

    def _wheel(notches: int) -> None:
        CGEventPost(kCGHIDEventTap, CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, int(notches)))

    def _cursor_pos() -> tuple[float, float]:
        loc = CGEventGetLocation(CGEventCreate(None))
        return float(loc.x), float(loc.y)

    def _post(kind, x: float, y: float) -> None:
        ev = CGEventCreateMouseEvent(None, kind, (float(x), float(y)), kCGMouseButtonLeft)
        if kind in (kCGEventLeftMouseDown, kCGEventLeftMouseUp):
            CGEventSetIntegerValueField(ev, kCGMouseEventClickState, 1)
        CGEventPost(kCGHIDEventTap, ev)

    def _move(x: float, y: float) -> None:
        _post(kCGEventLeftMouseDragged if _down else kCGEventMouseMoved, x, y)

    def move_cursor(x: int, y: int) -> None:
        _move(x + 1, y + 1)
        time.sleep(_nudge_mid_sec)
        _move(x, y)
        time.sleep(_nudge_settle_sec)

    def _left_down() -> None:
        global _down
        x, y = _cursor_pos()
        _post(kCGEventLeftMouseDown, x, y)
        _down = True

    def _left_up() -> None:
        global _down
        x, y = _cursor_pos()
        _post(kCGEventLeftMouseUp, x, y)
        _down = False

    _MAC_WIGGLE_PX = (6, 12)
    _MAC_WIGGLE_SEC = 0.04
    _MAC_SETTLE_SEC = 0.09
    _MAC_PRESS_SEC = 0.06

    def _mac_click(x: int, y: int) -> None:
        x, y = int(x), int(y)
        _move(x + random.randint(*_MAC_WIGGLE_PX), y + random.randint(*_MAC_WIGGLE_PX))
        time.sleep(_MAC_WIGGLE_SEC)
        _move(x - random.randint(*_MAC_WIGGLE_PX), y - random.randint(*_MAC_WIGGLE_PX))
        time.sleep(_MAC_WIGGLE_SEC)
        _move(x, y)
        time.sleep(max(_MAC_SETTLE_SEC, _nudge_settle_sec))
        _left_down()
        time.sleep(max(_MAC_PRESS_SEC, _click_hold_sec))
        _left_up()

else:
    from pynput.mouse import Button, Controller

    _mouse = Controller()

    def _set_pos(x: int, y: int) -> None:
        _mouse.position = (int(x), int(y))

    def move_cursor(x: int, y: int) -> None:
        _set_pos(int(x) + 1, int(y) + 1)
        time.sleep(_nudge_mid_sec)
        _set_pos(int(x), int(y))
        time.sleep(_nudge_settle_sec)

    def _left_down() -> None:
        _mouse.press(Button.left)

    def _left_up() -> None:
        _mouse.release(Button.left)

    def _wheel(notches: int) -> None:
        _mouse.scroll(0, int(notches))


def wheel_at(x: int, y: int, notches: int) -> None:
    hover_at(x, y)
    _wheel(notches)


def hover_at(x: int, y: int) -> None:
    move_cursor(x, y)
    if IS_WINDOWS:
        ax, ay = _abs_coords(int(x), int(y))
        _send_batch((MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay))


def _step(x: int, y: int) -> None:
    if IS_WINDOWS:
        _set_pos(x, y)
        ax, ay = _abs_coords(x, y)
        _send_batch((MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay))
    elif sys.platform == "darwin":
        _move(x, y)
    else:
        _set_pos(x, y)


def jitter_at(x: int, y: int, px: int = 4, times: int = 3, gap: float = 0.012) -> None:
    x, y = int(x), int(y)
    for _ in range(max(1, times)):
        _step(x + px, y + px // 2)
        time.sleep(gap)
        _step(x - px, y - px // 2)
        time.sleep(gap)
    _step(x, y)
    time.sleep(_nudge_settle_sec)


def gui_click_at(x: int, y: int) -> None:
    if IS_WINDOWS:
        _win_gui_click(x, y)
        return
    click_at(x, y)


def click_at(x: int, y: int) -> None:
    if sys.platform == "darwin":
        _mac_click(x, y)
        return
    move_cursor(x, y)
    _left_down()
    time.sleep(_click_hold_sec)
    _left_up()


class LeftClickController:
    def __init__(self) -> None:
        self._held = False

    def set(self, want_hold: bool) -> None:
        if want_hold and not self._held:
            _left_down()
            self._held = True
        elif not want_hold and self._held:
            _left_up()
            self._held = False

    def release(self) -> None:
        self.set(False)
