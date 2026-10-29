from __future__ import annotations

import time
from typing import Callable

from mouse_control import LeftClickController, click_at, gui_click_at, move_cursor
from platform_keys import key_press, key_release
from point_selector import FracPoint
from roblox_geo import point_to_screen, resolve_origin

AbortFn = Callable[[], bool]

_click = LeftClickController()

DEFAULT_KEY_HOLD_SEC = 0.1
STALE_KEY_GAP_SEC = 0.012

_held_keys: set[str] = set()


def release_inputs() -> None:
    _click.release()
    for name in list(_held_keys):
        try:
            key_release(name)
        except Exception:
            pass
        _held_keys.discard(name)


def sleep_interruptible(seconds: float, should_abort: AbortFn | None = None) -> bool:
    end = time.perf_counter() + max(0.0, float(seconds))
    while time.perf_counter() < end:
        if should_abort is not None and should_abort():
            return True
        time.sleep(min(0.02, max(0.0, end - time.perf_counter())))
    return False


def move_to_point(pt: FracPoint) -> tuple[int, int]:
    origin = resolve_origin()
    x, y = point_to_screen(pt.x, pt.y, origin)
    move_cursor(x, y)
    return x, y


def click_point(pt: FracPoint, settle_s: float = 0.05, should_abort: AbortFn | None = None) -> bool:
    if should_abort is not None and should_abort():
        return True
    origin = resolve_origin()
    x, y = point_to_screen(pt.x, pt.y, origin)
    click_at(x, y)
    return sleep_interruptible(settle_s, should_abort)


def gui_click_point(pt: FracPoint, settle_s: float = 0.05, should_abort: AbortFn | None = None) -> bool:
    if should_abort is not None and should_abort():
        return True
    origin = resolve_origin()
    x, y = point_to_screen(pt.x, pt.y, origin)
    gui_click_at(x, y)
    return sleep_interruptible(settle_s, should_abort)


def hold_click_point(pt: FracPoint, hold_s: float = 0.5, should_abort: AbortFn | None = None) -> bool:
    if should_abort is not None and should_abort():
        return True
    move_to_point(pt)
    _click.set(True)
    aborted = sleep_interruptible(hold_s, should_abort)
    _click.release()
    return aborted


def hold_keys(durations: dict[str, float], should_abort: AbortFn | None = None) -> bool:
    keys = {str(k): float(s) for k, s in durations.items() if float(s) > 0}
    if not keys:
        return False
    if should_abort is not None and should_abort():
        return True
    for name in keys:
        try:
            key_release(name)
        except Exception:
            pass
    time.sleep(STALE_KEY_GAP_SEC)
    down: list[str] = []
    aborted = False
    try:
        for name in keys:
            _held_keys.add(name)
            key_press(name)
            down.append(name)
        start = time.perf_counter()
        while down:
            if should_abort is not None and should_abort():
                aborted = True
                break
            now = time.perf_counter() - start
            for name in [n for n in down if now >= keys[n]]:
                try:
                    key_release(name)
                except Exception:
                    pass
                _held_keys.discard(name)
                down.remove(name)
            time.sleep(0.005)
    finally:
        for name in down:
            try:
                key_release(name)
            except Exception:
                pass
            _held_keys.discard(name)
    return aborted


def key_down(key: str) -> None:
    name = str(key)
    try:
        key_release(name)
    except Exception:
        pass
    time.sleep(STALE_KEY_GAP_SEC)
    _held_keys.add(name)
    key_press(name)


def key_up(key: str) -> None:
    name = str(key)
    try:
        key_release(name)
    except Exception:
        pass
    _held_keys.discard(name)


def press_point(pt: FracPoint) -> None:
    move_to_point(pt)
    _click.set(True)


def release_point() -> None:
    _click.release()


def tap_key(key: str, hold_s: float = DEFAULT_KEY_HOLD_SEC, should_abort: AbortFn | None = None) -> bool:
    if should_abort is not None and should_abort():
        return True
    name = str(key)
    try:
        key_release(name)
    except Exception:
        pass
    time.sleep(STALE_KEY_GAP_SEC)
    _held_keys.add(name)
    try:
        key_press(name)
        aborted = sleep_interruptible(hold_s, should_abort)
    finally:
        try:
            key_release(name)
        except Exception:
            pass
        _held_keys.discard(name)
    return aborted
