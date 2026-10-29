from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parent / "ocr.ps1"
READ_TIMEOUT_SEC = 8.0
MAX_SIDE = 2500
UPSCALE = 2.0


@dataclass
class Line:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


class Reader:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._next_id = 0
        self._dir = Path(tempfile.gettempdir())
        self._left: list[Path] = []
        self._lock = threading.Lock()
        self.why = ""

    def _start(self) -> None:
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._lines = queue.Queue()
        proc, lines = self._proc, self._lines

        def pump() -> None:
            for line in proc.stdout:
                lines.put(line.rstrip("\r\n"))

        threading.Thread(target=pump, daemon=True).start()

    def warm(self) -> None:
        with self._lock:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
            except OSError as exc:
                self.why = str(exc)

    def read(self, crop: np.ndarray | None) -> list[Line]:
        if crop is None or crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
            self.why = "nothing to read"
            return []
        with self._lock:
            try:
                return self._read(np.ascontiguousarray(crop))
            except Exception as exc:
                self.why = str(exc)
                return []

    def text(self, crop: np.ndarray | None) -> str:
        return " ".join(line.text for line in self.read(crop)).strip()

    def _read(self, crop: np.ndarray) -> list[Line]:
        self._clean()
        h, w = crop.shape[:2]
        scale = min(UPSCALE, MAX_SIDE / float(max(h, w)))
        img = crop if abs(scale - 1.0) < 0.01 else cv2.resize(
            crop, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
        )
        self._next_id += 1
        tag = str(self._next_id)
        image = self._dir / f"pl-ocr-{os.getpid()}-{tag}.png"
        if not cv2.imwrite(str(image), img):
            self.why = "couldn't write the temp picture"
            return []
        self._left.append(image)
        try:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            self._proc.stdin.write(f"{tag}|{image}\n")
            self._proc.stdin.flush()
            end = time.monotonic() + READ_TIMEOUT_SEC
            while True:
                got, _, rest = self._lines.get(timeout=max(0.01, end - time.monotonic())).partition("|")
                if got == tag:
                    break
        except (OSError, ValueError, queue.Empty):
            self._stop()
            self.why = "Windows text reader didn't answer"
            return []
        self._clean()
        self.why = ""
        out = []
        for item in rest.split("|") if rest else []:
            parts = item.split("~")
            if len(parts) != 5:
                continue
            try:
                x, y, bw, bh = (int(v) for v in parts[1:])
            except ValueError:
                continue
            text = " ".join(parts[0].split())
            if text:
                out.append(Line(text, int(x / scale), int(y / scale), max(1, int(bw / scale)), max(1, int(bh / scale))))
        return out

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
        self._clean()

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _clean(self) -> None:
        keep = []
        for image in self._left:
            try:
                image.unlink(missing_ok=True)
            except OSError:
                keep.append(image)
        self._left = keep
