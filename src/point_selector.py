from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from win_focus import detach_window, pin_topmost_realised


@dataclass
class FracPoint:
    x: float
    y: float


class ClickCapture(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        prompt: str,
        on_saved: Callable[[FracPoint, str], None],
        on_cancelled: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_saved = on_saved
        self.on_cancelled = on_cancelled
        self._done = False

        from roblox_geo import resolve_origin, virtual_screen_rect

        self._origin = resolve_origin()
        vs = virtual_screen_rect()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{vs.w}x{vs.h}+{vs.x}+{vs.y}")
        self.configure(bg="#000000")
        try:
            self.attributes("-alpha", 0.15)
        except tk.TclError:
            pass

        src = "Roblox window" if self._origin.source == "roblox" else "screen (open Roblox for best results)"
        banner = tk.Label(
            self,
            text=prompt + f"\nLeft click to set, Esc to cancel\nCoords relative to: {src}",
            bg="#211c17",
            fg="#f3ece4",
            font=("Segoe UI", 14, "bold"),
            padx=16,
            pady=12,
            justify="center",
        )
        banner.place(relx=0.5, rely=0.08, anchor="n")

        self.bind("<Button-1>", self._on_click)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        detach_window(self)
        pin_topmost_realised(self)
        self.focus_force()
        self.grab_set()
        self.config(cursor="crosshair")

    def _on_click(self, event: tk.Event) -> None:
        from roblox_geo import clamp_point, point_from_screen

        x, y = int(event.x_root), int(event.y_root)
        fx, fy = clamp_point(*point_from_screen(x, y, self._origin))
        self._finish(True, FracPoint(fx, fy))

    def _finish(self, saved: bool, pt: FracPoint | None = None) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        source = self._origin.source
        self.destroy()
        if saved and pt is not None:
            self.on_saved(pt, source)
        else:
            self.on_cancelled()

    def cancel(self) -> None:
        self._finish(False)
