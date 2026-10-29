from __future__ import annotations

import sys
from dataclasses import dataclass

from area_selector import PixelRect
from win_focus import roblox_window_rect

IS_WINDOWS = sys.platform == "win32"

_dpi_ready = False


@dataclass(frozen=True)
class CoordOrigin:
    x: int
    y: int
    w: int
    h: int
    source: str

    @property
    def as_pixel_rect(self) -> PixelRect:
        return PixelRect(self.x, self.y, self.w, self.h)


def ensure_dpi_awareness() -> None:
    global _dpi_ready
    if _dpi_ready or not IS_WINDOWS:
        _dpi_ready = True
        return
    import ctypes

    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _dpi_ready = True
            return
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            _dpi_ready = True
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    _dpi_ready = True


def virtual_screen_rect() -> PixelRect:
    import mss

    try:
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
            m = sct.monitors[0]
            return PixelRect(
                int(m["left"]), int(m["top"]),
                max(1, int(m["width"])), max(1, int(m["height"])),
            )
    except Exception:
        return primary_monitor_rect()


def primary_monitor_rect() -> PixelRect:
    import mss

    try:
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
            m = sct.monitors[1]
            return PixelRect(
                int(m["left"]), int(m["top"]),
                max(1, int(m["width"])), max(1, int(m["height"])),
            )
    except Exception:
        if IS_WINDOWS:
            import ctypes

            user32 = ctypes.windll.user32
            return PixelRect(0, 0, max(1, int(user32.GetSystemMetrics(0))), max(1, int(user32.GetSystemMetrics(1))))
        return PixelRect(0, 0, 1920, 1080)


def roblox_client_rect() -> PixelRect | None:
    r = roblox_window_rect()
    if r is None:
        return None
    return PixelRect(r.x, r.y, r.w, r.h)


def resolve_origin() -> CoordOrigin:
    client = roblox_client_rect()
    if client is not None:
        return CoordOrigin(client.x, client.y, client.w, client.h, "roblox")
    prim = primary_monitor_rect()
    return CoordOrigin(prim.x, prim.y, prim.w, prim.h, "primary")


def point_to_screen(fx: float, fy: float, origin: CoordOrigin | None = None) -> tuple[int, int]:
    o = origin or resolve_origin()
    return (
        int(round(o.x + float(fx) * o.w)),
        int(round(o.y + float(fy) * o.h)),
    )


def point_from_screen(sx: int, sy: int, origin: CoordOrigin | None = None) -> tuple[float, float]:
    o = origin or resolve_origin()
    return ((sx - o.x) / max(o.w, 1), (sy - o.y) / max(o.h, 1))


def clamp_point(fx: float, fy: float) -> tuple[float, float]:
    return (max(0.0, min(1.0, float(fx))), max(0.0, min(1.0, float(fy))))


def rect_to_screen(fx: float, fy: float, fw: float, fh: float, origin: CoordOrigin | None = None) -> PixelRect:
    o = origin or resolve_origin()
    return PixelRect(
        x=int(round(o.x + float(fx) * o.w)),
        y=int(round(o.y + float(fy) * o.h)),
        w=max(1, int(round(float(fw) * o.w))),
        h=max(1, int(round(float(fh) * o.h))),
    )


def rect_from_screen(rect: PixelRect, origin: CoordOrigin | None = None) -> tuple[float, float, float, float]:
    o = origin or resolve_origin()
    return (
        (rect.x - o.x) / max(o.w, 1),
        (rect.y - o.y) / max(o.h, 1),
        rect.w / max(o.w, 1),
        rect.h / max(o.h, 1),
    )


def clamp_rect(fx: float, fy: float, fw: float, fh: float) -> tuple[float, float, float, float]:
    x = max(0.0, min(1.0, float(fx)))
    y = max(0.0, min(1.0, float(fy)))
    w = max(0.01, min(1.0 - x, float(fw)))
    h = max(0.01, min(1.0 - y, float(fh)))
    return (x, y, w, h)
