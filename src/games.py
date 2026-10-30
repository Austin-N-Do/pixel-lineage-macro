from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from timing import _longest, _velocity, _zone_masks, runs

REF_W = 1920.0
REF_H = 1008.0
REF_BOX = 756.0

BAR = "bar"
LOCK = "lock"
LANE = "lane"
METER = "meter"

CLASS_GAMES = {
    "Warrior": BAR,
    "Mage": LOCK,
    "Thief": LOCK,
    "Bard": LANE,
    "Fist": METER,
    "Archer": METER,
}
CLASSES = tuple(CLASS_GAMES)

GAME_NAMES = {
    BAR: "Blade Focus",
    LOCK: "gold lock",
    LANE: "Encore notes",
    METER: "Power Punch",
}
SHOT_NAME = "Power Shot"

LINE_GAMES = (
    ((178, 137, 255), LOCK, "Mage"),
    ((119, 217, 139), LOCK, "Thief"),
    ((252, 118, 196), LANE, "Bard"),
    ((254, 148, 69), METER, "Fist"),
    ((112, 208, 224), BAR, "Warrior"),
)

LINE_FAR = 0.18

FLASH = "flash"
DODGE = "dodge"
UNKNOWN = "unknown"

def colour_game(rgb: tuple[int, int, int]) -> tuple[str, str] | None:
    game, _who = line_game(rgb)
    if game == DODGE:
        return DODGE, "INCOMING!"
    if game in (BAR, LOCK, LANE, METER):
        return game, GAME_NAMES[game]
    return None


@dataclass
class Panel:
    top: int
    left: int
    right: int
    color: tuple[int, int, int]
    game: str
    who: str
    scale: float


def ui_scale(client_w: int, client_h: int) -> float:
    return max(0.2, min(float(client_w), client_h * (REF_W / REF_H)) / REF_W)


def box_scale(width: float) -> float:
    return max(0.2, min(5.0, float(width) / REF_BOX))


def _hi(px: np.ndarray) -> np.ndarray:
    return np.maximum(np.maximum(px[..., 0], px[..., 1]), px[..., 2])


def _lo(px: np.ndarray) -> np.ndarray:
    return np.minimum(np.minimum(px[..., 0], px[..., 1]), px[..., 2])


def _bgr(img: np.ndarray):
    px = img.astype(np.int16)
    return px[..., 0], px[..., 1], px[..., 2]


def _gold(img: np.ndarray) -> np.ndarray:
    b, g, r = _bgr(img)
    return (np.abs(r - 231) <= 30) & (np.abs(g - 196) <= 30) & (np.abs(b - 120) <= 40)


def _tone(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    top = max(1.0, float(max(rgb)))
    return rgb[0] / top, rgb[1] / top, rgb[2] / top


LINE_TONES = tuple(
    (_tone(rgb), game, who) for rgb, game, who in
    (((255, 255, 255), FLASH, ""), ((229, 194, 118), FLASH, ""), ((235, 89, 79), DODGE, "")) + LINE_GAMES
)


def line_game(rgb: tuple[int, int, int]) -> tuple[str, str]:
    top = max(rgb)
    if top < 90:
        return UNKNOWN, ""
    tone = _tone(rgb)
    best, far = (UNKNOWN, ""), LINE_FAR ** 2
    for ref, game, who in LINE_TONES:
        gap = sum((a - b) ** 2 for a, b in zip(tone, ref))
        if gap < far:
            best, far = (game, who), gap
    if best[0] == FLASH and min(rgb) >= 0.76 * top and top < 170:
        return UNKNOWN, ""
    return best


def _line_mask(px: np.ndarray) -> np.ndarray:
    hi = _hi(px)
    lo = _lo(px)
    return ((hi - lo >= 60) & (hi >= 120)) | (lo >= 200)


def _line_colour(px: np.ndarray, y: int, s: int, e: int, thick: int) -> np.ndarray:
    lo = s + (e - s) // 5
    hi = max(lo + 1, e - (e - s) // 5)
    best, score = px[y, lo:hi], -1.0
    for yy in range(y, min(px.shape[0], y + max(1, thick // 2) + 1)):
        row = px[yy, lo:hi]
        bright = float(row.max(axis=-1).mean())
        if bright > score:
            best, score = row, bright
    return np.median(best, axis=0)


def find_panel(img: np.ndarray | None, client_w: int, client_h: int) -> Panel | None:
    if img is None or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    if h < 20 or w < 60:
        return None
    px = img.astype(np.int16)
    hi = _hi(px)
    line = _line_mask(px)
    k = ui_scale(client_w, client_h)
    min_run = max(120, int(REF_BOX * 0.30 * k))
    near = max(2, int(round(3 * k)))
    far = max(near + 3, int(round(11 * k)))
    best: Panel | None = None
    for y in np.flatnonzero(line.sum(axis=1) >= min_run):
        if y + far >= h:
            break
        for s, e in runs(line[y]):
            if e - s < min_run:
                continue
            mid = (s + e) // 2
            c = _line_colour(px, y, s, e, far)
            if y >= 2 and (np.abs(px[y - 2, s:e] - c).max(axis=-1) <= 40).mean() > 0.5:
                continue
            same = np.abs(px[y] - c).max(axis=-1) <= 45
            span = next(((a, b) for a, b in runs(same) if a <= mid < b), None)
            if span is None:
                continue
            left, right = span
            if right - left < min_run or left <= 0 or right >= w:
                continue
            if best is not None and right - left <= best.right - best.left:
                continue
            body = hi[y + near:y + far + 1, left:right] <= 60
            if body.mean(axis=1).max() < 0.6:
                continue
            rgb = (int(round(c[2])), int(round(c[1])), int(round(c[0])))
            game, who = line_game(rgb)
            if game == UNKNOWN:
                continue
            best = Panel(int(y), int(left), int(right), rgb, game, who, box_scale(right - left))
            break
    return best


def panel_line(img: np.ndarray, rows: int, near: int, far: int) -> tuple[int, tuple[int, int, int]] | None:
    h, w = img.shape[:2]
    if h <= far + 1 or w < 8:
        return None
    px = img[:min(h, rows + far + 1)].astype(np.int16)
    line = _line_mask(px[:rows])
    hi = _hi(px)
    a, b = w // 4, 3 * w // 4
    for y in np.flatnonzero(line.mean(axis=1) >= 0.6):
        if (np.abs(px[y + 2, a:b] - px[y, a:b]).max(axis=-1) <= 40).mean() < 0.6:
            continue
        body = hi[y + near:y + far + 1] <= 60
        if body.mean(axis=1).max() < 0.6:
            continue
        c = np.median(px[y, a:b], axis=0)
        return int(y), (int(round(c[2])), int(round(c[1])), int(round(c[0])))
    return None


def lock_box(body: np.ndarray, scale: float) -> tuple[int, int, int, int] | None:
    gold = _gold(body)
    if gold.sum() < 40 * scale:
        return None
    n, _lab, st, _ = cv2.connectedComponentsWithStats(gold.astype(np.uint8), connectivity=8)
    bh, bw = body.shape[:2]
    keep = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if area < 6 or w > bw * 0.4 or h > bh * 0.8:
            continue
        if w * h >= 30 and area > 0.6 * w * h:
            continue
        keep.append((x, y, x + w, y + h, area))
    if not keep:
        return None
    best = None
    for k in keep:
        group = [o for o in keep if abs((o[0] + o[2]) - (k[0] + k[2])) < 200 * scale and abs((o[1] + o[3]) - (k[1] + k[3])) < 200 * scale]
        x0 = min(o[0] for o in group)
        y0 = min(o[1] for o in group)
        x1 = max(o[2] for o in group)
        y1 = max(o[3] for o in group)
        w, h = x1 - x0, y1 - y0
        side = max(w, h)
        if side < 30 * scale or side > 160 * scale or h < 1:
            continue
        if not (0.7 <= w / h <= 1.4):
            continue
        if sum(o[4] for o in group) < 1.5 * side:
            continue
        if best is None or side > best[2]:
            best = (x0, y0, w, h)
    return best


def find_ring(body: np.ndarray, scale: float) -> tuple[int, int, int, int] | None:
    b, g, r = _bgr(body)
    mask = _gold(body) | (np.minimum(np.minimum(b, g), r) >= 220)
    n, _lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if h < 70 * scale or h > 170 * scale:
            continue
        if w < 0.35 * h or w > 0.8 * h or area > 0.5 * w * h:
            continue
        if best is None or x < best[0]:
            best = (x, y, w, h)
    return best


def note_xs(band: np.ndarray, scale: float) -> list[float]:
    b, g, r = _bgr(band)
    pink = (r >= 200) & (g >= 80) & (g <= 175) & (b >= 140) & (b <= 235)
    cols = pink.sum(axis=0) >= 2
    found = runs(cols)
    if not found:
        return []
    merged = [list(found[0])]
    gap = max(3, int(round(12 * scale)))
    for s, e in found[1:]:
        if s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    lo = 25 * scale
    hi = 75 * scale
    return [(s + e) / 2.0 for s, e in merged if lo <= e - s <= hi]


def _meter_masks(img: np.ndarray):
    b, g, r = _bgr(img)
    dim = (np.abs(r - 127) <= 22) & (np.abs(g - 115) <= 22) & (np.abs(b - 71) <= 22)
    lit = (r >= 200) & (g >= 170) & (g <= 230) & (b >= 60) & (b <= 160)
    orange = (r >= 220) & (g >= 110) & (g <= 185) & (b <= 120)
    green = (g >= 170) & (g - r >= 40) & (g - b >= 30)
    return dim, lit, orange | green


def find_meter(body: np.ndarray, scale: float) -> int | None:
    dim, lit, _fill = _meter_masks(body)
    need = max(10, int(14 * scale))
    cols = (dim | lit).sum(axis=0) >= need
    found = [(s, e) for s, e in runs(cols) if e - s >= 20 * scale and e - s <= 120 * scale]
    if not found:
        return None
    s, e = min(found, key=lambda se: se[0])
    return (s + e) // 2


def green_game(body: np.ndarray, scale: float, cls: str) -> tuple[str, str]:
    if cls == "Archer":
        return METER, "Archer"
    if cls == "Thief":
        return LOCK, "Thief"
    if body.size and find_meter(body, scale) is not None:
        return METER, "Archer"
    return LOCK, "Thief"


def panel_game(panel: Panel, area: np.ndarray, cls: str) -> tuple[str, str, str] | None:
    found = colour_game(panel.color)
    if found is None:
        return None
    game, name = found
    who = panel.who
    if game == LOCK and who == "Thief":
        top = panel.top + max(12, int(round(60 * panel.scale)))
        body = area[top:panel.top + int(round(363 * panel.scale)), panel.left:panel.right]
        game, who = green_game(body, panel.scale, cls)
        name = SHOT_NAME if game == METER else GAME_NAMES[game]
    if cls in CLASS_GAMES and game in GAME_NAMES and (game != CLASS_GAMES[cls] or who != cls):
        # Another class's minigame: the ultra banners (LEGION GATE...) have a Blade Focus blue
        # top line, and the hero's green health bar is a Thief line that reads as gold lock.
        # Playing them pressed Space in the middle of the turn.
        return None
    return game, name, who


class LockGame:
    def __init__(self, scale: float, delay: float) -> None:
        self.scale = scale
        self.delay = max(0.0, delay)
        self.armed = True
        self.off = 0

    def step(self, body: np.ndarray, t: float) -> float | None:
        if lock_box(body, self.scale) is None:
            self.off += 1
            if self.off >= 2:
                self.armed = True
            return None
        self.off = 0
        if not self.armed:
            return None
        return self.delay

    def pressed(self) -> None:
        self.armed = False
        self.off = 0


def _purple(img: np.ndarray) -> np.ndarray:
    b, g, r = _bgr(img)
    return (r >= 130) & (r <= 225) & (g >= 90) & (g <= 185) & (b >= 200) & (r - g >= 25)


def find_rune(body: np.ndarray, scale: float) -> tuple[int, int, int, int] | None:
    mask = _purple(body).astype(np.uint8)
    if int(mask.sum()) < 20 * scale * scale:
        return None
    k = max(3, int(round(5 * scale)) | 1)
    grown = cv2.dilate(mask, np.ones((k, k), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    lo, hi = 20 * scale + k, 62 * scale + k
    best = None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if not (lo <= w <= hi and lo <= h <= hi) or not (0.7 <= w / h <= 1.4):
            continue
        if best is None or area > best[4]:
            best = (x, y, w, h, area)
    if best is None:
        return None
    x, y, w, h, _a = best
    ys, xs = np.nonzero(mask[y:y + h, x:x + w])
    if len(xs) == 0:
        return None
    return x + int(xs.min()), y + int(ys.min()), x + int(xs.max()) + 1, y + int(ys.max()) + 1


def square_side(body: np.ndarray, rune: tuple[int, int, int, int]) -> tuple[int, bool] | None:
    x0, y0, x1, y1 = rune
    rw = x1 - x0
    cy = (y0 + y1) // 2
    reach = rw * 2
    sides = []
    gold_hit = False
    for y in (cy - 1, cy, cy + 1):
        if y < 0 or y >= body.shape[0]:
            continue
        row = body[y:y + 1]
        b, g, r = _bgr(row)
        white = np.minimum(np.minimum(b, g), r)[0] >= 190
        gold = _gold(row)[0]
        edge = white | gold
        left = np.flatnonzero(edge[max(0, x0 - reach):x0])
        right = np.flatnonzero(edge[x1:x1 + reach])
        if len(left) == 0 or len(right) == 0:
            continue
        lx = max(0, x0 - reach) + int(left[-1])
        rx = x1 + int(right[0])
        sides.append(rx - lx + 1)
        gold_hit = gold_hit or bool(gold[lx]) or bool(gold[rx])
    if not sides:
        return None
    return int(np.median(sides)), gold_hit


def _shrink(samples: deque) -> float | None:
    if len(samples) < 3:
        return None
    newest = samples[-1][0]
    pts = [(t, s) for t, s in samples if newest - t <= 0.4]
    if len(pts) < 3:
        return None
    ts = np.array([p[0] for p in pts])
    ss = np.array([p[1] for p in pts])
    if ts[-1] - ts[0] < 0.06:
        return None
    tm = ts.mean()
    den = float(((ts - tm) ** 2).sum())
    if den <= 0:
        return None
    return float(((ts - tm) * (ss - ss.mean())).sum() / den)


class MageGame:
    def __init__(self, scale: float, lead: float, close: float) -> None:
        self.scale = scale
        self.lead = lead
        self.close = max(1.0, close)
        self.samples: deque = deque(maxlen=16)
        self.centre: tuple[float, float] | None = None
        self.last_side: int | None = None
        self.armed = True
        self.fallback = LockGame(scale, 0.0)

    def _reset(self, cx: float, cy: float) -> None:
        self.centre = (cx, cy)
        self.samples.clear()
        self.last_side = None
        self.armed = True

    def step(self, body: np.ndarray, t: float) -> float | None:
        rune = find_rune(body, self.scale)
        if rune is None:
            if self.centre is None:
                return self.fallback.step(body, t)
            return None
        x0, y0, x1, y1 = rune
        rw = x1 - x0
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if self.centre is None or abs(cx - self.centre[0]) > rw * 0.5 or abs(cy - self.centre[1]) > rw * 0.5:
            self._reset(cx, cy)
        found = square_side(body, rune)
        if found is None:
            return None
        side, gold = found
        if self.last_side is not None and side > self.last_side + 6 * self.scale:
            self._reset(cx, cy)
        if self.last_side is None or side != self.last_side:
            self.samples.append((t, float(side)))
        self.last_side = side
        if not self.armed:
            return None
        target = rw * self.close
        v = _shrink(self.samples)
        if v is None or v > -15.0 * self.scale:
            return 0.0 if gold and side <= target else None
        s_now = side + v * (time.perf_counter() - t)
        if s_now <= target:
            return 0.0
        wait = (s_now - target) / -v - self.lead
        if wait > 0.012:
            return None
        return max(0.0, wait)

    def pressed(self) -> None:
        self.armed = False
        self.fallback.pressed()


class LaneGame:
    def __init__(self, scale: float, lead: float, bias: float) -> None:
        self.scale = scale
        self.lead = lead
        self.bias = bias
        self.min_speed = 300.0 * scale
        self.ring: tuple[int, int, int, int] | None = None
        self.samples: deque = deque(maxlen=12)
        self.prev_x: float | None = None
        self.armed = True
        self.gone = 0

    def step(self, body: np.ndarray, t: float) -> float | None:
        ring = find_ring(body, self.scale)
        if ring is not None and (self.ring is None or abs(ring[0] - self.ring[0]) < ring[2]):
            self.ring = ring
        if self.ring is None:
            return None
        rx, ry, rw, rh = self.ring
        y0 = max(0, int(ry - rh * 0.25))
        y1 = min(body.shape[0], int(ry + rh * 1.25))
        x0 = max(0, int(rx - rw * 0.25))
        xs = [x0 + x for x in note_xs(body[y0:y1, x0:], self.scale)]
        centre = rx + rw / 2.0
        xs = [x for x in xs if x > centre - rw * 0.75]
        if not xs:
            self.gone += 1
            if self.gone >= 2:
                self.armed = True
                self.samples.clear()
                self.prev_x = None
            return None
        self.gone = 0
        x = min(xs)
        if self.prev_x is not None and x - self.prev_x > rw:
            self.armed = True
            self.samples.clear()
        self.prev_x = x
        self.samples.append((t, x))
        if not self.armed:
            return None
        v = _velocity(self.samples)
        if v is None or v > -self.min_speed:
            return None
        target = centre - self.bias * rw
        x_now = x + v * (time.perf_counter() - t)
        gap = x_now - target
        if gap <= 0:
            return 0.0 if x_now >= rx - rw * 0.2 else None
        wait = gap / -v - self.lead
        if wait > 0.012:
            return None
        return max(0.0, wait)

    def pressed(self) -> None:
        self.armed = False


class MeterGame:
    def __init__(self, scale: float, lead: float, bias: float) -> None:
        self.scale = scale
        self.lead = lead
        self.bias = bias
        self.min_speed = 60.0 * scale
        self.cx: int | None = None
        self.band: tuple[int, int] | None = None
        self.samples: deque = deque(maxlen=12)
        self.prev_top: int | None = None
        self.armed = True

    def step(self, body: np.ndarray, t: float) -> float | None:
        if self.cx is None:
            self.cx = find_meter(body, self.scale)
            if self.cx is None:
                return None
        half = max(2, int(round(3 * self.scale)))
        strip = body[:, max(0, self.cx - half):self.cx + half + 1]
        dim, lit, fill = _meter_masks(strip)
        dim_rows = np.flatnonzero(dim.mean(axis=1) >= 0.6)
        fill_rows = np.flatnonzero(fill.mean(axis=1) >= 0.6)
        if len(fill_rows) < 2:
            if len(dim_rows) >= 10 * self.scale:
                self.band = (int(dim_rows[0]), int(dim_rows[-1]))
            self.armed = True
            self.samples.clear()
            self.prev_top = None
            return None
        top = int(fill_rows[0])
        if self.prev_top is not None and top - self.prev_top > 12 * self.scale:
            self.armed = True
            self.samples.clear()
        self.prev_top = top
        if len(dim_rows) >= 10 * self.scale and top > dim_rows[-1]:
            self.band = (int(dim_rows[0]), int(dim_rows[-1]))
        if self.band is None:
            return None
        self.samples.append((t, float(top)))
        if not self.armed:
            return None
        v = _velocity(self.samples)
        if v is None or v > -self.min_speed:
            return None
        bt, bb = self.band
        target = (bt + bb) / 2.0 - self.bias * (bb - bt)
        y_now = top + v * (time.perf_counter() - t)
        gap = y_now - target
        if gap <= 0:
            return 0.0 if y_now >= bt else None
        wait = gap / -v - self.lead
        if wait > 0.012:
            return None
        return max(0.0, wait)

    def pressed(self) -> None:
        self.armed = False


def dodge_bar(img: np.ndarray, scale: float) -> bool:
    _white, _gold, blue = _zone_masks(img)
    need = max(6, int(round(12 * scale)))
    rows = np.flatnonzero(blue.sum(axis=1) >= need)
    return any(_longest(blue[y], need) is not None for y in rows[:6])


class PanelPlayer:
    def __init__(self) -> None:
        self.lead = 0.035
        self.meter_lead = 0.035
        self.bard_lead = 0.035
        self.mage_lead = 0.035
        self.mage_close = 1.3
        self.thief_delay = 0.045
        self.bias = 0.0
        self.lost = 0.6
        self.max_sec = 7.0
        self.timed_out = False
        self.press_hold = 0.03
        self.early_gap = 0.35

    def configure(self, adv: dict) -> None:
        self.lead = float(adv.get("press_lead_s", self.lead))
        self.meter_lead = float(adv.get("meter_lead_s", self.meter_lead))
        self.bard_lead = float(adv.get("bard_lead_s", self.bard_lead))
        self.mage_lead = float(adv.get("mage_lead_s", self.mage_lead))
        self.mage_close = max(1.0, float(adv.get("mage_close", self.mage_close)))
        self.thief_delay = max(0.0, float(adv.get("thief_delay_s", self.thief_delay)))
        self.bias = float(adv.get("aim_bias", self.bias))
        self.lost = max(0.1, float(adv.get("minigame_lost_s", self.lost)))
        self.max_sec = max(2.0, float(adv.get("minigame_max_s", self.max_sec)))
        self.press_hold = max(0.0, float(adv.get("press_hold_s", self.press_hold)))
        self.early_gap = max(0.05, float(adv.get("early_gap_sec", self.early_gap)))

    def make(self, game: str, scale: float, who: str = ""):
        if game == LOCK and who == "Mage":
            return MageGame(scale, self.mage_lead, self.mage_close)
        if game == LOCK:
            return LockGame(scale, self.thief_delay)
        if game == LANE:
            return LaneGame(scale, self.bard_lead, self.bias)
        if game == METER:
            return MeterGame(scale, self.meter_lead, self.bias)
        return None

    def play(
        self,
        game,
        grab: Callable[[], tuple[np.ndarray | None, float]],
        scale: float,
        press: Callable[[float], None],
        aborted: Callable[[], bool],
        rows: int,
    ) -> int:
        near = max(2, int(round(3 * scale)))
        far = max(near + 3, int(round(11 * scale)))
        skip = max(12, int(round(60 * scale)))
        presses = 0
        next_early = 0.0
        self.timed_out = False
        start = last_seen = last_press = time.perf_counter()
        while not aborted():
            img, t = grab()
            if t - last_press > self.max_sec:
                self.timed_out = True
                break
            seen = panel_line(img, rows, near, far) if img is not None else None
            if seen is None:
                if t - last_seen > self.lost:
                    break
                time.sleep(0.003)
                continue
            last_seen = t
            y, rgb = seen
            kind, _who = line_game(rgb)
            if kind == DODGE and (presses == 0 and t - start > 0.3 or dodge_bar(img, scale)):
                break
            if game is None:
                if kind not in (FLASH, DODGE) and t >= next_early:
                    press(self.press_hold)
                    presses += 1
                    last_press = next_early = time.perf_counter()
                    next_early += self.early_gap
                time.sleep(0.005)
                continue
            if kind in (FLASH, DODGE):
                time.sleep(0.002)
                continue
            body = img[y + skip:]
            if body.size == 0:
                continue
            wait = game.step(body, t)
            if wait is None:
                time.sleep(0.001)
                continue
            if wait > 0:
                time.sleep(wait)
            press(self.press_hold)
            presses += 1
            last_press = time.perf_counter()
            game.pressed()
        return presses
