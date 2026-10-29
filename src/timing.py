from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

ATTACK = "attack"
DODGE = "dodge"

REF_W = 1920.0
REF_H = 1008.0


def ui_ref(client_w: int, client_h: int) -> float:
    return max(320.0, min(float(client_w), client_h * (REF_W / REF_H)))


@dataclass
class Bar:
    top: int
    bottom: int
    above: int
    mid: int
    width: int
    kind: str
    ref: float


@dataclass
class Marker:
    x: float
    start: int
    end: int
    kind: str


def _split(img: np.ndarray):
    px = img.astype(np.int16)
    return px[..., 0], px[..., 1], px[..., 2]


def _band(img: np.ndarray, lo: tuple, hi: tuple) -> np.ndarray:
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.strides[-2] != 3:
        img = np.ascontiguousarray(img)
    return cv2.inRange(img, np.array(lo, np.uint8), np.array(hi, np.uint8)).astype(bool)


def _zone_masks(img: np.ndarray):
    white = _band(img, (210, 210, 210), (255, 255, 255))
    gold = _band(img, (80, 166, 201), (160, 226, 255))
    blue = _band(img, (245, 180, 120), (255, 240, 180))
    return white, gold, blue


def _dark(img: np.ndarray) -> np.ndarray:
    return _band(img, (0, 0, 0), (60, 60, 60))


def runs(mask_1d: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], mask_1d.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def marker_at(row: np.ndarray, max_w: int) -> Marker | None:
    b, g, r = _split(row)
    white = np.minimum(np.minimum(b, g), r) >= 185
    red = (r >= 150) & (r * 2 >= g * 3) & (r * 2 >= b * 3)
    found = [(s, e) for s, e in runs(white | red) if 2 <= e - s <= max_w]
    if not found:
        return None
    s, e = max(found, key=lambda se: se[1] - se[0])
    kind = DODGE if red[s:e].mean() > 0.5 else ATTACK
    return Marker((s + e - 1) / 2.0, s, e, kind)


def _max_w(ref: float) -> int:
    return max(5, int(ref * 0.0177))


def find_bar(img: np.ndarray | None, ref: float | None = None) -> Bar | None:
    if img is None or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    if h < 12 or w < 60:
        return None
    ref = float(w) if ref is None else max(120.0, float(ref))
    white, gold, blue = _zone_masks(img)
    zone = white | gold | blue
    dark = _dark(img)
    min_run = max(4, int(ref * 0.004))
    good = np.zeros(h, dtype=bool)
    dark_rows = dark.mean(axis=1) >= 0.35
    for y in np.flatnonzero((zone.sum(axis=1) >= min_run) & dark_rows):
        found = runs(zone[y])
        if found and max(e - s for s, e in found) >= min_run:
            good[y] = True
    tall = max(3, int(round(ref * 0.0026)))
    blocks = [(s, e) for s, e in runs(good) if e - s >= tall]
    if not blocks:
        return None
    top, end = max(blocks, key=lambda se: se[1] - se[0])
    bottom = end - 1
    mid = (top + bottom) // 2
    if _longest(zone[mid], min_run) is None:
        return None
    off = max(3, int(round((bottom - top + 1) * 0.2)))
    above = top - off
    if above < 0 or dark[above].mean() < 0.5:
        return None
    mk = marker_at(img[above], _max_w(ref))
    if mk is None:
        return None
    below = bottom + off
    if below < h:
        low = marker_at(img[below], _max_w(ref))
        if low is None or abs(low.x - mk.x) > _max_w(ref):
            return None
    return Bar(top, bottom, above, mid, w, mk.kind, ref)


def has_block(img: np.ndarray, bar: Bar) -> bool:
    _white, _gold, blue = _zone_masks(img[bar.mid:bar.mid + 1])
    return _longest(blue[0], max(3, int((bar.ref or bar.width) * 0.003))) is not None


def bar_score(row: np.ndarray, kind: str) -> int:
    white, gold, blue = _zone_masks(row)
    if kind == DODGE:
        return int(blue.sum())
    zone = int((white | gold | blue).sum())
    return 0 if zone > row.shape[1] * 0.6 else zone


def _longest(mask_1d: np.ndarray, min_len: int) -> tuple[int, int] | None:
    found = [(s, e) for s, e in runs(mask_1d) if e - s >= min_len]
    if not found:
        return None
    s, e = max(found, key=lambda se: se[1] - se[0])
    return s, e - 1


class Player:
    def __init__(self) -> None:
        self.lead = 0.035
        self.dodge_lead = 0.035
        self.bias = 0.0
        self.min_speed = 0.12
        self.lost = 0.6
        self.max_sec = 8.0
        self.dodge_max = 3.0
        self.timed_out = False
        self.press_hold = 0.03

    def configure(self, adv: dict) -> None:
        self.lead = float(adv.get("press_lead_s", self.lead))
        self.dodge_lead = float(adv.get("dodge_lead_s", self.dodge_lead))
        self.bias = float(adv.get("aim_bias", self.bias))
        self.min_speed = float(adv.get("min_speed", self.min_speed))
        self.lost = max(0.1, float(adv.get("minigame_lost_s", self.lost)))
        self.max_sec = max(2.0, float(adv.get("minigame_max_s", self.max_sec)))
        self.dodge_max = max(1.0, float(adv.get("dodge_max_s", self.dodge_max)))
        self.press_hold = max(0.0, float(adv.get("press_hold_s", self.press_hold)))

    def play(
        self,
        grab: Callable[[], tuple[np.ndarray | None, float]],
        bar: Bar,
        press: Callable[[float], None],
        aborted: Callable[[], bool],
        want: dict[str, bool],
        early: bool = False,
    ) -> dict:
        width = bar.ref or bar.width
        max_w = _max_w(width)
        zone_min = max(3, int(width * 0.003))
        samples: deque = deque(maxlen=10)
        zone: tuple[int, int] | None = None
        band: tuple[int, int] | None = None
        armed = True
        settled = False
        prev_x: float | None = None
        kind = bar.kind
        limit = min(self.max_sec, self.dodge_max) if bar.kind == DODGE else self.max_sec
        widest = 0
        mode: str | None = None
        presses = 0
        last_press = 0.0
        self.timed_out = False
        start = last_seen = last_bar = time.perf_counter()
        while not aborted():
            img, t = grab()
            if t - (start if bar.kind == DODGE else max(start, last_press)) > limit:
                self.timed_out = True
                break
            if img is None:
                if t - last_seen > self.lost:
                    break
                time.sleep(0.005)
                continue
            if mode is None:
                mode = DODGE if bar.kind == DODGE and bar_score(img[-1:], DODGE) >= zone_min else ATTACK
            score = bar_score(img[-1:], mode)
            if score >= max(zone_min, int(widest * 0.3)):
                last_bar = t
                widest = max(widest, score)
            elif t - last_bar > self.lost:
                break
            mk = marker_at(img[0], max_w)
            if mk is None:
                if t - last_seen > self.lost:
                    break
                time.sleep(0.002)
                continue
            last_seen = t
            white, gold, blue = _zone_masks(img[-1:])
            white_run = _longest(white[0], zone_min)
            outer_run = _longest((white | gold | blue)[0], zone_min)
            kind = mk.kind
            run = white_run or outer_run
            if run is not None and (mk.end + 3 < run[0] or mk.start - 3 > run[1]):
                if zone is not None and abs((run[0] + run[1]) - (zone[0] + zone[1])) / 2.0 > max(6.0, (zone[1] - zone[0]) * 0.5):
                    armed = True
                    samples.clear()
                zone = run
                band = outer_run or run
            x = mk.x
            if prev_x is not None and abs(x - prev_x) > width * 0.25:
                armed = True
                samples.clear()
            prev_x = x
            if not samples or abs(samples[-1][1] - x) >= 1.0:
                samples.append((t, x))
            v = _velocity(samples)
            moving = v is not None and abs(v) >= self.min_speed * width
            if not armed:
                if v is not None and not moving:
                    settled = True
                elif moving and settled:
                    armed = True
                    samples.clear()
                    samples.append((t, x))
                time.sleep(0.001)
                continue
            if early and kind == ATTACK and moving and want.get(kind, True):
                press(self.press_hold)
                presses += 1
                last_press = time.perf_counter()
                armed = False
                settled = False
                continue
            if zone is None or not want.get(kind, True) or not moving:
                time.sleep(0.001)
                continue
            zl, zr = zone
            span = max(1.0, zr - zl)
            target = (zl + zr) / 2.0 + self.bias * span * (1 if v > 0 else -1)
            now = time.perf_counter()
            x_now = x + v * (now - t)
            gap = target - x_now
            if gap * v < 0:
                bl, br = band or zone
                if not (min(zl, bl) <= x_now <= max(zr, br)):
                    time.sleep(0.001)
                    continue
                wait = 0.0
            else:
                wait = gap / v - (self.dodge_lead if kind == DODGE else self.lead)
                if wait > 0.012:
                    time.sleep(0.001)
                    continue
            if wait > 0:
                end = time.perf_counter() + wait
                while time.perf_counter() < end:
                    pass
            press(self.press_hold)
            presses += 1
            last_press = time.perf_counter()
            armed = False
            settled = False
        return {"kind": kind, "presses": presses}


def _velocity(samples: deque) -> float | None:
    if len(samples) < 3:
        return None
    newest = samples[-1][0]
    pts = [(t, x) for t, x in samples if newest - t <= 0.09]
    if len(pts) < 3:
        return None
    ts = np.array([p[0] for p in pts])
    xs = np.array([p[1] for p in pts])
    if ts[-1] - ts[0] < 0.012:
        return None
    tm = ts.mean()
    den = float(((ts - tm) ** 2).sum())
    if den <= 0:
        return None
    return float(((ts - tm) * (xs - xs.mean())).sum() / den)
