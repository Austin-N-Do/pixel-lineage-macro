from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from win_focus import detach_window, pin_topmost_realised

HANDLE = 10
MIN_W = 40
MIN_H = 40
BORDER = 2


@dataclass
class PixelRect:
    x: int
    y: int
    w: int
    h: int

    def clamp_within(self, bounds: "PixelRect") -> PixelRect:
        w = max(MIN_W, min(self.w, bounds.w))
        h = max(MIN_H, min(self.h, bounds.h))
        x = max(bounds.x, min(self.x, bounds.x + bounds.w - w))
        y = max(bounds.y, min(self.y, bounds.y + bounds.h - h))
        return PixelRect(x, y, w, h)


@dataclass
class FracRect:
    x: float
    y: float
    w: float
    h: float


DEFAULT_SCAN_AREA = FracRect(
    x=0.731640625,
    y=0.2923611111111111,
    w=0.03828125,
    h=0.3763888888888889,
)


class AreaSelector(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        initial: PixelRect,
        bounds: PixelRect,
        on_saved: Callable[[PixelRect], None],
        on_cancelled: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_saved = on_saved
        self.on_cancelled = on_cancelled
        self._done = False
        self._bounds = bounds
        self.rect = initial.clamp_within(bounds)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.45)
        except tk.TclError:
            pass
        self.configure(bg="#c47a3a")
        self._drag_mode: str | None = None
        self._origin_mouse = (0, 0)
        self._origin_rect = self.rect

        self._body = tk.Frame(self, bg="#352e26", cursor="fleur")
        self._body.pack(fill="both", expand=True, padx=BORDER, pady=BORDER)

        for widget in (self, self._body):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)

        self.bind("<Return>", lambda _e: self.save())
        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self._apply_geometry()
        detach_window(self)
        pin_topmost_realised(self)
        self.focus_force()
        self.grab_set()

    def _apply_geometry(self) -> None:
        self.rect = self.rect.clamp_within(self._bounds)
        r = self.rect
        self.geometry(f"{r.w}x{r.h}+{r.x}+{r.y}")

    def _hit_zone(self, x: int, y: int) -> str:
        w, h = self.rect.w, self.rect.h
        left = x < HANDLE
        right = x >= w - HANDLE
        top = y < HANDLE
        bottom = y >= h - HANDLE
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return "move"

    def _on_press(self, event: tk.Event) -> None:
        x = self.winfo_pointerx() - self.winfo_rootx()
        y = self.winfo_pointery() - self.winfo_rooty()
        self._drag_mode = self._hit_zone(x, y)
        self._origin_mouse = (self.winfo_pointerx(), self.winfo_pointery())
        self._origin_rect = PixelRect(self.rect.x, self.rect.y, self.rect.w, self.rect.h)
        cursors = {
            "move": "fleur",
            "n": "sb_v_double_arrow",
            "s": "sb_v_double_arrow",
            "e": "sb_h_double_arrow",
            "w": "sb_h_double_arrow",
            "ne": "top_right_corner",
            "nw": "top_left_corner",
            "se": "bottom_right_corner",
            "sw": "bottom_left_corner",
        }
        self.configure(cursor=cursors.get(self._drag_mode, "arrow"))

    def _on_drag(self, event: tk.Event) -> None:
        if not self._drag_mode:
            return
        mx, my = self.winfo_pointerx(), self.winfo_pointery()
        dx = mx - self._origin_mouse[0]
        dy = my - self._origin_mouse[1]
        o = self._origin_rect
        x, y, w, h = (o.x, o.y, o.w, o.h)
        mode = self._drag_mode

        if mode == "move":
            x, y = o.x + dx, o.y + dy
        else:
            if "e" in mode:
                w = o.w + dx
            if "s" in mode:
                h = o.h + dy
            if "w" in mode:
                x = o.x + dx
                w = o.w - dx
            if "n" in mode:
                y = o.y + dy
                h = o.h - dy

        self.rect = PixelRect(x, y, w, h).clamp_within(self._bounds)
        if self.rect.w < MIN_W:
            if "w" in mode:
                self.rect = PixelRect(o.x + o.w - MIN_W, self.rect.y, MIN_W, self.rect.h)
            else:
                self.rect = PixelRect(self.rect.x, self.rect.y, MIN_W, self.rect.h)
        if self.rect.h < MIN_H:
            if "n" in mode:
                self.rect = PixelRect(self.rect.x, o.y + o.h - MIN_H, self.rect.w, MIN_H)
            else:
                self.rect = PixelRect(self.rect.x, self.rect.y, self.rect.w, MIN_H)
        self.rect = self.rect.clamp_within(self._bounds)
        self._apply_geometry()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self.configure(cursor="arrow")

    def _finish(self, saved: bool) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        rect = self.rect.clamp_within(self._bounds)
        self.destroy()
        if saved:
            self.on_saved(rect)
        else:
            self.on_cancelled()

    def save(self) -> None:
        self._finish(True)

    def cancel(self) -> None:
        self._finish(False)
