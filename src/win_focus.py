from __future__ import annotations

import sys
import threading
import time
import tkinter as tk

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_TITLE_HINTS = ("roblox",)


class WindowRect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    SW_MINIMIZE = 6
    SW_RESTORE = 9
    GWL_HWNDPARENT = -8
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040

    def _window_title(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def _is_visible(hwnd: int) -> bool:
        return bool(user32.IsWindowVisible(hwnd))

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ROBLOX_CLASS = "windowsclient"
    _ROBLOX_EXES = ("robloxplayerbeta.exe", "robloxplayer.exe", "windows10universal.exe")
    _OWN_PID = ctypes.windll.kernel32.GetCurrentProcessId()

    def _window_class(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _window_pid(hwnd: int) -> int:
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def _exe_name(pid: int) -> str:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)

    def find_roblox_hwnd() -> int | None:
        strong: list[int] = []
        weak: list[int] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not _is_visible(hwnd):
                return True
            title = _window_title(hwnd).strip().lower()
            if title == "roblox" or _window_class(hwnd).lower() == _ROBLOX_CLASS:
                if _window_pid(hwnd) != _OWN_PID:
                    strong.append(hwnd)
                    return False
            elif title and any(h in title for h in _TITLE_HINTS):
                if _window_pid(hwnd) != _OWN_PID:
                    weak.append(hwnd)
            return True

        user32.EnumWindows(ENUM_WINDOWS_PROC(callback), 0)
        if strong:
            return strong[0]
        for hwnd in weak:
            if _exe_name(_window_pid(hwnd)) in _ROBLOX_EXES:
                return hwnd
        return weak[0] if weak else None

    HWND_REUSE_SEC = 1.0
    _hwnd_cache = {"hwnd": None, "at": 0.0}

    def _cached_roblox_hwnd() -> int | None:
        now = time.perf_counter()
        hwnd = _hwnd_cache["hwnd"]
        if (hwnd and now - _hwnd_cache["at"] < HWND_REUSE_SEC
                and user32.IsWindow(hwnd) and _is_visible(hwnd)):
            return hwnd
        hwnd = find_roblox_hwnd()
        _hwnd_cache["hwnd"] = hwnd
        _hwnd_cache["at"] = now
        return hwnd

    def roblox_window_rect() -> WindowRect | None:
        hwnd = _cached_roblox_hwnd()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w < 32 or h < 32:
            return None
        pt = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        return WindowRect(int(pt.x), int(pt.y), w, h)

    def focus_roblox() -> bool:
        hwnd = find_roblox_hwnd()
        if not hwnd:
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        if user32.GetForegroundWindow() == hwnd:
            return True

        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        attached_fg = False
        attached_target = False
        try:
            if fg_tid and fg_tid != cur_tid:
                attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
            if target_tid and target_tid != cur_tid:
                attached_target = bool(user32.AttachThreadInput(cur_tid, target_tid, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            if attached_target:
                user32.AttachThreadInput(cur_tid, target_tid, False)
            if attached_fg:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        return user32.GetForegroundWindow() == hwnd

    def tk_hwnd(widget: tk.Misc) -> int:
        widget.update_idletasks()
        hwnd = int(widget.winfo_id())
        GA_ROOT = 2
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root:
            return int(root)
        parent = user32.GetParent(hwnd)
        return int(parent) if parent else hwnd

    def _set_long(hwnd: int, index: int, value: int) -> None:
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            user32.SetWindowLongPtrW(hwnd, index, value)
        else:
            user32.SetWindowLongW(hwnd, index, value)

    def _get_long(hwnd: int, index: int) -> int:
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            return int(user32.GetWindowLongPtrW(hwnd, index))
        return int(user32.GetWindowLongW(hwnd, index))

    def detach_window(widget: tk.Misc) -> None:
        try:
            hwnd = tk_hwnd(widget)
            _set_long(hwnd, GWL_HWNDPARENT, 0)
        except Exception:
            pass

    def style_overlay_window(widget: tk.Misc) -> None:
        try:
            hwnd = tk_hwnd(widget)
            style = _get_long(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
            _set_long(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass
        try:
            widget.attributes("-toolwindow", True)
        except tk.TclError:
            pass

    def keep_overlay_on_top(widget: tk.Misc) -> None:
        pass

    def pin_topmost_realised(widget: tk.Misc) -> None:
        pass

    def force_destroy_window(widget: tk.Misc | None) -> None:
        if widget is None:
            return
        hwnd = None
        try:
            hwnd = tk_hwnd(widget)
        except Exception:
            pass
        try:
            widget.destroy()
        except tk.TclError:
            pass
        if hwnd:
            try:
                if user32.IsWindow(hwnd):
                    user32.DestroyWindow(hwnd)
            except Exception:
                pass

    def minimize_tk(widget: tk.Misc) -> None:
        try:
            widget.iconify()
        except tk.TclError:
            user32.ShowWindow(tk_hwnd(widget), SW_MINIMIZE)

    def pin_topmost_no_activate(widget: tk.Misc, enabled: bool = True) -> None:
        try:
            hwnd = tk_hwnd(widget)
            insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
            user32.SetWindowPos(
                hwnd, insert_after, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            widget.attributes("-topmost", bool(enabled))
        except tk.TclError:
            pass

    def restore_tk(widget: tk.Misc, *, keep_topmost: bool = False, activate: bool = True) -> None:
        hwnd = tk_hwnd(widget)
        try:
            widget.deiconify()
            widget.state("normal")
        except tk.TclError:
            pass
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.ShowWindow(hwnd, 5)
        if keep_topmost:
            pin_topmost_no_activate(widget, True)
        else:
            try:
                widget.attributes("-topmost", False)
            except tk.TclError:
                pass
        if activate:
            user32.BringWindowToTop(hwnd)
            try:
                widget.lift()
                widget.focus_force()
            except tk.TclError:
                pass


elif IS_MAC:
    try:
        import Quartz
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
    except Exception:
        Quartz = None
        NSRunningApplication = None
        NSApplicationActivateIgnoringOtherApps = 0

    def _roblox_window_info() -> dict | None:
        if Quartz is None:
            return None
        opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        weak = None
        for info in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
            if int(info.get("kCGWindowLayer", 0)) != 0:
                continue
            b = info.get("kCGWindowBounds") or {}
            if float(b.get("Width", 0)) < 32 or float(b.get("Height", 0)) < 32:
                continue
            owner = str(info.get("kCGWindowOwnerName", "") or "").strip().lower()
            title = str(info.get("kCGWindowName", "") or "").strip().lower()
            if owner in ("roblox", "robloxplayer"):
                return dict(info)
            if weak is None and any(h in owner + " " + title for h in _TITLE_HINTS):
                weak = dict(info)
        return weak

    def find_roblox_hwnd() -> int | None:
        info = _roblox_window_info()
        return int(info["kCGWindowNumber"]) if info else None

    def roblox_window_rect() -> WindowRect | None:
        info = _roblox_window_info()
        if not info:
            return None
        b = info["kCGWindowBounds"]
        title_h = 28
        x, y = int(b["X"]), int(b["Y"]) + title_h
        w, h = int(b["Width"]), int(b["Height"]) - title_h
        if w < 32 or h < 32:
            return None
        return WindowRect(x, y, w, h)

    def focus_roblox() -> bool:
        info = _roblox_window_info()
        if not info or NSRunningApplication is None:
            return False
        pid = int(info.get("kCGWindowOwnerPID", 0))
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        return bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))

    def detach_window(widget: tk.Misc) -> None:
        pass

    def style_overlay_window(widget: tk.Misc) -> None:
        try:
            widget.update_idletasks()
            widget.attributes("-topmost", False)
            widget.attributes("-topmost", True)
        except tk.TclError:
            pass

    def keep_overlay_on_top(widget: tk.Misc) -> None:
        try:
            widget.attributes("-topmost", True)
        except tk.TclError:
            pass

    def pin_topmost_realised(widget: tk.Misc) -> None:
        style_overlay_window(widget)

    def force_destroy_window(widget: tk.Misc | None) -> None:
        if widget is None:
            return
        try:
            widget.destroy()
        except tk.TclError:
            pass

    def minimize_tk(widget: tk.Misc) -> None:
        try:
            widget.iconify()
        except tk.TclError:
            pass

    def pin_topmost_no_activate(widget: tk.Misc, enabled: bool = True) -> None:
        try:
            widget.attributes("-topmost", bool(enabled))
        except tk.TclError:
            pass

    def restore_tk(widget: tk.Misc, *, keep_topmost: bool = False, activate: bool = True) -> None:
        try:
            widget.deiconify()
            widget.state("normal")
            widget.attributes("-topmost", bool(keep_topmost))
            if activate:
                widget.lift()
                widget.focus_force()
        except tk.TclError:
            pass


else:
    import shutil
    import subprocess

    try:
        from Xlib import X, Xatom, display as _xdisplay
        from Xlib.protocol import event as _xevent
    except Exception:
        X = None
        Xatom = None
        _xdisplay = None
        _xevent = None

    _CLASS_HINTS = ("roblox", "sober", "vinegar")

    def _open_display():
        if _xdisplay is None:
            return None
        try:
            return _xdisplay.Display()
        except Exception:
            return None

    def _text_prop(d, win, name: str) -> str:
        try:
            atom = name if isinstance(name, int) else d.intern_atom(name)
            prop = win.get_full_property(atom, X.AnyPropertyType)
        except Exception:
            return ""
        if prop is None or prop.value is None:
            return ""
        val = prop.value
        if isinstance(val, bytes):
            return val.decode("utf-8", "replace")
        if isinstance(val, str):
            return val
        try:
            return bytes(val).decode("utf-8", "replace")
        except Exception:
            return ""

    def _window_name(d, win) -> str:
        name = _text_prop(d, win, "_NET_WM_NAME")
        if not name:
            name = _text_prop(d, win, Xatom.WM_NAME)
        return name

    def _window_class(win) -> str:
        try:
            cls = win.get_wm_class()
        except Exception:
            return ""
        if not cls:
            return ""
        return " ".join(str(c) for c in cls if c)

    def _is_roblox(d, win) -> bool:
        blob = (_window_name(d, win) + " " + _window_class(win)).lower()
        if not blob.strip():
            return False
        if any(h in blob for h in _CLASS_HINTS):
            cls = _window_class(win).lower()
            if "tk" in cls.split() or "python" in cls:
                return False
            return True
        return False

    def _is_viewable(win) -> bool:
        try:
            return win.get_attributes().map_state == X.IsViewable
        except Exception:
            return False

    def _client_list(d) -> list:
        try:
            prop = d.screen().root.get_full_property(d.intern_atom("_NET_CLIENT_LIST"), Xatom.WINDOW)
        except Exception:
            return []
        if prop is None or not prop.value:
            return []
        out = []
        for wid in prop.value:
            try:
                out.append(d.create_resource_object("window", int(wid)))
            except Exception:
                pass
        return out

    def _walk(d, win, out: list, depth: int = 0) -> None:
        if depth > 6:
            return
        try:
            kids = win.query_tree().children
        except Exception:
            return
        for kid in kids:
            if not _is_viewable(kid):
                continue
            if _is_roblox(d, kid):
                out.append(kid)
                return
            _walk(d, kid, out, depth + 1)

    def _window_area(win) -> int:
        try:
            g = win.get_geometry()
            return int(g.width) * int(g.height)
        except Exception:
            return 0

    def _find_roblox_window():
        d = _open_display()
        if d is None:
            return None, None
        found = [w for w in _client_list(d) if _is_roblox(d, w)]
        if not found:
            _walk(d, d.screen().root, found)
        if not found:
            return d, None
        viewable = [w for w in found if _is_viewable(w)] or found
        return d, max(viewable, key=_window_area)

    def find_roblox_hwnd() -> int | None:
        d, win = _find_roblox_window()
        try:
            return int(win.id) if win is not None else None
        finally:
            if d is not None:
                d.close()

    _RECT_TTL = 0.2
    _rect_lock = threading.Lock()
    _rect_cache: tuple[float, WindowRect | None] = (0.0, None)

    def _query_roblox_window_rect() -> WindowRect | None:
        d, win = _find_roblox_window()
        if win is None:
            if d is not None:
                d.close()
            return None
        try:
            geom = win.get_geometry()
            root = d.screen().root
            pos = win.translate_coords(root, 0, 0)
            w, h = int(geom.width), int(geom.height)
            if w < 32 or h < 32:
                return None
            return WindowRect(-int(pos.x), -int(pos.y), w, h)
        except Exception:
            return None
        finally:
            d.close()

    def roblox_window_rect() -> WindowRect | None:
        global _rect_cache
        now = time.monotonic()
        with _rect_lock:
            stamp, rect = _rect_cache
            if now - stamp < _RECT_TTL:
                return rect
        rect = _query_roblox_window_rect()
        with _rect_lock:
            _rect_cache = (now, rect)
        return rect

    def _active_window_id(d) -> int | None:
        try:
            prop = d.screen().root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW)
            if prop and prop.value:
                return int(prop.value[0])
        except Exception:
            pass
        return None

    def _activate_ewmh(d, win) -> None:
        root = d.screen().root
        ev = _xevent.ClientMessage(
            window=win,
            client_type=d.intern_atom("_NET_ACTIVE_WINDOW"),
            data=(32, [2, X.CurrentTime, 0, 0, 0]),
        )
        root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.flush()

    def focus_roblox() -> bool:
        d, win = _find_roblox_window()
        if win is None:
            if d is not None:
                d.close()
            return False
        try:
            if _active_window_id(d) == int(win.id):
                return True
            try:
                _activate_ewmh(d, win)
            except Exception:
                pass
            try:
                win.set_input_focus(X.RevertToParent, X.CurrentTime)
                win.configure(stack_mode=X.Above)
            except Exception:
                pass
            d.sync()
            for _ in range(10):
                if _active_window_id(d) == int(win.id):
                    return True
                time.sleep(0.03)
            if shutil.which("wmctrl"):
                subprocess.call(
                    ["wmctrl", "-ia", hex(int(win.id))],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                d.sync()
                time.sleep(0.05)
                if _active_window_id(d) == int(win.id):
                    return True
            return _active_window_id(d) is None
        except Exception:
            return False
        finally:
            d.close()

    def detach_window(widget: tk.Misc) -> None:
        pass

    def style_overlay_window(widget: tk.Misc) -> None:
        try:
            widget.attributes("-type", "utility")
        except tk.TclError:
            pass

    def keep_overlay_on_top(widget: tk.Misc) -> None:
        try:
            widget.lift()
        except tk.TclError:
            pass

    def pin_topmost_realised(widget: tk.Misc) -> None:
        keep_overlay_on_top(widget)

    def force_destroy_window(widget: tk.Misc | None) -> None:
        if widget is None:
            return
        try:
            widget.destroy()
        except tk.TclError:
            pass

    def minimize_tk(widget: tk.Misc) -> None:
        try:
            widget.iconify()
        except tk.TclError:
            pass

    def pin_topmost_no_activate(widget: tk.Misc, enabled: bool = True) -> None:
        try:
            widget.attributes("-topmost", bool(enabled))
        except tk.TclError:
            pass

    def restore_tk(widget: tk.Misc, *, keep_topmost: bool = False, activate: bool = True) -> None:
        try:
            widget.deiconify()
            widget.state("normal")
            widget.attributes("-topmost", bool(keep_topmost))
            if activate:
                widget.lift()
                widget.focus_force()
        except tk.TclError:
            pass
