from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from area_selector import PixelRect
from win_focus import detach_window, force_destroy_window, keep_overlay_on_top, style_overlay_window

OUTLINE_THICKNESS = 3
OUTLINE_COLOR = "#FF00FF"
PLAYING_COLOR = "#00FFFF"
WDA_EXCLUDEFROMCAPTURE = 0x11
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
LWA_ALPHA = 0x2


def hide_from_capture(widget: tk.Misc) -> None:
    if sys.platform != "win32":
        return
    try:
        widget.update_idletasks()
        user32 = ctypes.windll.user32
        inner = int(widget.winfo_id())
        hwnd = user32.GetAncestor(inner, 2) or inner
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    except Exception:
        pass


class ScanOutline:
    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._edges: list[tk.Toplevel] = []
        self._visible = False
        self._last_key: tuple[int, int, int, int] | None = None
        self._color = OUTLINE_COLOR

    def set_color(self, color: str) -> None:
        if color == self._color:
            return
        self._color = color
        for edge in self._edges:
            try:
                if edge.winfo_exists():
                    edge.configure(bg=color)
            except tk.TclError:
                pass

    def _specs(self, rect: PixelRect) -> tuple[tuple[int, int, int, int], ...]:
        t = OUTLINE_THICKNESS
        x, y, w, h = (rect.x, rect.y, rect.w, rect.h)
        return (
            (x - t, y - t, w + 2 * t, t),
            (x - t, y + h, w + 2 * t, t),
            (x - t, y, t, h),
            (x + w, y, t, h),
        )

    def show(self, rect: PixelRect) -> None:
        if self._visible and len(self._edges) == 4:
            self.update(rect)
            return
        self.hide()
        for sx, sy, sw, sh in self._specs(rect):
            if sw <= 0 or sh <= 0:
                continue
            edge = tk.Toplevel(self.master)
            edge.overrideredirect(True)
            edge.attributes("-topmost", True)
            try:
                edge.attributes("-alpha", 1.0)
            except tk.TclError:
                pass
            edge.configure(bg=self._color, highlightthickness=0, bd=0)
            edge.geometry(f"{int(sw)}x{int(sh)}+{int(sx)}+{int(sy)}")
            edge.lift()
            try:
                edge.attributes("-disabled", True)
            except tk.TclError:
                pass
            detach_window(edge)
            style_overlay_window(edge)
            hide_from_capture(edge)
            self._edges.append(edge)
        self._visible = True
        self._last_key = (rect.x, rect.y, rect.w, rect.h)

    def hide(self) -> None:
        for edge in self._edges:
            force_destroy_window(edge)
        self._edges.clear()
        self._visible = False
        self._last_key = None

    def update(self, rect: PixelRect) -> None:
        key = (rect.x, rect.y, rect.w, rect.h)
        if not self._visible or len(self._edges) != 4:
            self.show(rect)
            return
        if key == self._last_key:
            return
        try:
            for edge, (sx, sy, sw, sh) in zip(self._edges, self._specs(rect)):
                if edge.winfo_exists():
                    edge.geometry(f"{int(sw)}x{int(sh)}+{int(sx)}+{int(sy)}")
                    keep_overlay_on_top(edge)
                else:
                    self.show(rect)
                    return
        except tk.TclError:
            self.show(rect)
            return
        self._last_key = key
