from __future__ import annotations

import copy
import json
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Callable

import cv2
import numpy as np

USER_AGENT = "DiscordBot (https://www.youtube.com/@1-vtt, 1.0)"
FOOTER = "1vtt's Pixel Lineage Macro"
TIMEOUT_SEC = 15.0
JPEG_QUALITY = 85
RATE_TRIES = 4
RATE_WAIT_MAX = 6.0

try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl.create_default_context()


def embed(title: str, color: int, fields: list[tuple[str, str]], description: str | None = None) -> dict:
    lines = []
    if fields:
        lines.append("  \u2022  ".join(f"{n} {v}" for n, v in fields))
    if description:
        lines.append(description)
    out = {
        "title": title,
        "color": color,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if lines:
        out["description"] = "\n".join(lines)[:4096]
    return out


def _part(boundary: str, headers: str, data: bytes) -> bytes:
    return f"--{boundary}\r\n{headers}\r\n\r\n".encode() + data + b"\r\n"


def _body(payload: dict, frame: np.ndarray | None) -> tuple[str, bytes]:
    payload = copy.deepcopy(payload)
    jpg = None
    if frame is not None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            jpg = buf.tobytes()
            if payload.get("embeds"):
                payload["embeds"][0]["image"] = {"url": "attachment://roblox.jpg"}
    boundary = uuid.uuid4().hex
    parts = [_part(
        boundary,
        'Content-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json',
        json.dumps(payload).encode(),
    )]
    if jpg is not None:
        parts.append(_part(
            boundary,
            'Content-Disposition: form-data; name="files[0]"; filename="roblox.jpg"\r\nContent-Type: image/jpeg',
            jpg,
        ))
    parts.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(parts)


def post(url: str, payload: dict, frame: np.ndarray | None = None) -> str:
    if not url.lower().startswith("https://"):
        return "the URL must start with https://"
    boundary, body = _body(payload, frame)
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": USER_AGENT,
    })

    def send() -> str:
        # A loot alert lands right next to the Run Log update, so Discord's rate limit can turn it
        # away: wait as long as it asks and try again instead of dropping it.
        for attempt in range(RATE_TRIES):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_SEC, context=_SSL):
                    return "sent"
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == RATE_TRIES - 1:
                    raise
                try:
                    wait = float(exc.headers.get("Retry-After") or 1.0)
                except ValueError:
                    wait = 1.0
                time.sleep(min(RATE_WAIT_MAX, max(0.5, wait)))
        return "rate limited, skipped"

    return _guard(send)


def _guard(call: Callable[[], str]) -> str:
    try:
        return call()
    except urllib.error.HTTPError as exc:
        return _http_error(exc)
    except (urllib.error.URLError, OSError, ValueError):
        return "failed, no connection"


def _http_error(exc: urllib.error.HTTPError) -> str:
    if exc.code == 429:
        return "rate limited, skipped"
    if exc.code in (401, 403, 404):
        return "the URL is wrong or the webhook was deleted"
    return f"failed (HTTP {exc.code})"


def _json_call(url: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method=method, headers={
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC, context=_SSL) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def _url_with(url: str, path_tail: str = "", **query: str) -> str:
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parts.query) + list(query.items())
    return urllib.parse.urlunsplit(parts._replace(path=parts.path.rstrip("/") + path_tail, query=urllib.parse.urlencode(q)))


class Webhook:
    def __init__(self) -> None:
        self._busy = threading.Lock()

    def send(self, url: str, payload: dict, frame: np.ndarray | None, report: Callable[[str], None], wait: bool = False) -> bool:
        # wait (loot alerts): queue behind a send in progress instead of dropping the drop.
        if not (self._busy.acquire(timeout=TIMEOUT_SEC * 2) if wait else self._busy.acquire(blocking=False)):
            return False

        def run() -> None:
            try:
                report(post(url, payload, frame))
            finally:
                self._busy.release()

        threading.Thread(target=run, daemon=True).start()
        return True


class LiveMessage:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = None
        self._running = False
        self._id: str | None = None
        self._url: str | None = None
        self._gen = 0

    def reset(self) -> None:
        with self._lock:
            self._gen += 1
            self._id = None
            self._url = None
            self._pending = None

    def update(self, url: str, payload: dict, report: Callable[[str], None]) -> None:
        with self._lock:
            self._pending = (url, payload, report, self._gen)
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            with self._lock:
                job, self._pending = self._pending, None
                if job is None:
                    self._running = False
                    return
                url, payload, report, gen = job
                msg_id = self._id if self._url == url and gen == self._gen else None
            report(self._push(url, payload, msg_id, gen))

    def _push(self, url: str, payload: dict, msg_id: str | None, gen: int) -> str:
        if not url.lower().startswith("https://"):
            return "the URL must start with https://"

        def send() -> str:
            if msg_id:
                try:
                    _json_call(_url_with(url, "/messages/" + msg_id), "PATCH", payload)
                    return "updated"
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
            data = _json_call(_url_with(url, wait="true"), "POST", payload)
            with self._lock:
                if gen == self._gen:
                    self._id = str(data.get("id") or "") or None
                    self._url = url
            return "sent"

        return _guard(send)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    import mss

    import win_focus as _wf

    _user32 = ctypes.WinDLL("user32")
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.IsIconic.argtypes = [wintypes.HWND]

    def _roblox_game_hwnd() -> int | None:
        found: list[int] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not _wf._is_visible(hwnd):
                return True
            if _wf._window_class(hwnd).lower() == _wf._ROBLOX_CLASS or (
                "roblox" in _wf._window_title(hwnd).lower()
                and _wf._exe_name(_wf._window_pid(hwnd)) in _wf._ROBLOX_EXES
            ):
                found.append(hwnd)
                return False
            return True

        _wf.user32.EnumWindows(_wf.ENUM_WINDOWS_PROC(callback), 0)
        return found[0] if found else None

    def capture_roblox() -> np.ndarray | None:
        hwnd = _roblox_game_hwnd()
        if hwnd is None or _user32.IsIconic(hwnd):
            return None
        rect = wintypes.RECT()
        if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        w, h = int(rect.right), int(rect.bottom)
        if w < 32 or h < 32:
            return None
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
            shot = sct.grab({"left": int(pt.x), "top": int(pt.y), "width": w, "height": h})
        return np.ascontiguousarray(np.asarray(shot, dtype=np.uint8)[:, :, :3])

else:
    def capture_roblox() -> np.ndarray | None:
        return None
