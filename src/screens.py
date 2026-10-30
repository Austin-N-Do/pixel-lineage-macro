from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import cv2
import numpy as np

from ocr import Line

REF_W = 1920.0
REF_H = 1008.0

DEFAULT_AREAS = {
    "mg_area": {"x": 0.18, "y": 0.05, "w": 0.64, "h": 0.42},
    "en_area": {"x": 0.01, "y": 0.703, "w": 0.163, "h": 0.044},
    "skills_area": {"x": 0.18, "y": 0.385, "w": 0.276, "h": 0.28},
    "path_area": {"x": 0.31, "y": 0.34, "w": 0.52, "h": 0.52},
    "event_area": {"x": 0.33, "y": 0.10, "w": 0.48, "h": 0.65},
}

BANNER_BAND = (0.30, 0.08, 0.45, 0.18)
VICTORY_BAND = (0.12, 0.06, 0.76, 0.26)
CHEST_BAND = {"x": 0.28, "y": 0.12, "w": 0.50, "h": 0.45}
SKIP_BAND = {"x": 0.80, "y": 0.62, "w": 0.20, "h": 0.30}
TURN_BAND = (0.150, 0.71, 0.055, 0.25)
BOX_BAND = (0.002, 0.71, 0.030, 0.25)
MENU_BAND = {"x": 0.20, "y": 0.08, "w": 0.65, "h": 0.84}
BACK_BAND = (0.10, 0.70, 0.07, 0.045)
ROW_TOP = 0.7698
ROW_STEP = 0.0362
SCROLL_ROW = 2
GUARD_ROW = 3
ROW_X = (0.015, 0.17)
USUAL_CARDS = ({"x": 0.573, "y": 0.434}, {"x": 0.573, "y": 0.597}, {"x": 0.573, "y": 0.762})
PATH_CONFIRM = ({"x": 0.5, "y": 0.62}, {"x": 0.5, "y": 0.69}, {"x": 0.5, "y": 0.55})
# "ACT 10/10  THE HEART OF BLIGHT" top left, the RETURN HOME button under CHARACTER / GEAR.
ACT_BAND = {"x": 0.0, "y": 0.06, "w": 0.30, "h": 0.10}
HOME_BAND = {"x": 0.0, "y": 0.85, "w": 0.20, "h": 0.15}
HOME_WORDS = ("RETURN HOME", "TURN BACK")

_EN = re.compile(r"E\s*N\W{0,2}([0-9OoIl|]{1,3})\s*/\s*([0-9OoIl|]{1,3})")
_ACT = re.compile(r"ACT\s*([0-9OoIl|]{1,2})\s*/\s*([0-9OoIl|]{1,2})")
_DIGIT_FIX = str.maketrans({"O": "0", "I": "1", "L": "1", "|": "1"})
_COST = re.compile(r"\s\d+\s*EN\b.*$", re.IGNORECASE)


@dataclass
class Box:
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


@dataclass
class Button:
    box: Box
    active: bool


def ui_ref(w: int, h: int) -> float:
    return max(320.0, min(float(w), h * (REF_W / REF_H)))


# The fight menu, BACK, EN and the skill list shrink toward the bottom-left corner when the window
# is narrower than the 1920x1008 the spots were measured on (half a screen: about 0.55x, a bit
# lower). find_layout reads the menu words once per window size to get that. SCROLL and GUARD are
# often greyed out and don't read, MEDITATE and SATCHEL always do.
FIGHT_WORDS = ("ATTACK", "SKILLS", "SCROLL", "GUARD", "MEDITATE", "SATCHEL")
FIGHT_SCAN = {"x": 0.0, "y": 0.45, "w": 0.5, "h": 0.55}


@dataclass(frozen=True)
class Layout:
    w: int
    h: int
    scale: float
    dy: float


_window = (0, 0)
_layouts: dict[tuple[int, int], Layout | None] = {}


def set_window(w: int, h: int) -> None:
    global _window
    _window = (int(w), int(h))


def window() -> tuple[int, int]:
    return _window


def remember_layout(w: int, h: int, layout: Layout | None) -> None:
    _layouts[(int(w), int(h))] = layout


def forget_layouts() -> None:
    _layouts.clear()


def layout_known(w: int, h: int) -> bool:
    return (int(w), int(h)) in _layouts


def fight_layout(w: int, h: int) -> Layout | None:
    return _layouts.get((int(w), int(h)))


def _fit_x(fx: float, lay: Layout) -> float:
    return fx * REF_W * lay.scale / lay.w


def _fit_y(fy: float, lay: Layout) -> float:
    return (lay.h - (1.0 - fy) * REF_H * lay.scale + lay.dy) / lay.h


def fit_point(pt: dict, w: int, h: int) -> dict:
    lay = fight_layout(w, h)
    if lay is None:
        return pt
    return {"x": _fit_x(pt["x"], lay), "y": _fit_y(pt["y"], lay)}


def fit_area(area: dict, w: int, h: int) -> dict:
    lay = fight_layout(w, h)
    if lay is None:
        return area
    return {
        "x": _fit_x(area["x"], lay),
        "y": _fit_y(area["y"], lay),
        "w": area["w"] * REF_W * lay.scale / lay.w,
        "h": area["h"] * REF_H * lay.scale / lay.h,
    }


def _fit_band(band: tuple[float, float, float, float], w: int, h: int) -> tuple[float, float, float, float]:
    a = fit_area({"x": band[0], "y": band[1], "w": band[2], "h": band[3]}, w, h)
    return a["x"], a["y"], a["w"], a["h"]


def narrow(w: int, h: int) -> float:
    # How much narrower than 1920x1008 the window is (half a screen: about 1.9).
    return max(1.0, (REF_W / REF_H) / (w / float(h))) if w and h else 1.0


def widen(area: dict, w: int, h: int, power: float = 0.25) -> dict:
    # Boxes in the middle (minigames, loot, events, paths) shrink less than the window does,
    # so on a narrow window they spill out of areas measured on a wide one. Half a screen: the
    # loot cards went to 84% of the width (power 1.0). Minigame boxes grow less, and any wider
    # than needed (power 0.25) took in the hero's health bar, chests and the ultra banners.
    k = narrow(w, h) ** power
    if k <= 1.05:
        return area
    nw = min(1.0, area["w"] * k)
    x = max(0.0, min(1.0 - nw, area["x"] + area["w"] / 2.0 - nw / 2.0))
    return {**area, "x": x, "w": nw}


def skip_band(w: int, h: int) -> dict:
    return {"x": 0.6, "y": 0.6, "w": 0.4, "h": 0.4} if narrow(w, h) > 1.05 else SKIP_BAND


def find_layout(lines: list[Line], w: int, h: int) -> tuple[float, float] | None:
    # Lines in window pixels. Returns (row step, ATTACK row centre) from a column of menu words.
    rows = []
    for ln in lines:
        words = norm(ln.text).split()
        if not words:
            continue
        for k, word in enumerate(FIGHT_WORDS):
            if difflib.SequenceMatcher(None, word, words[0]).ratio() >= 0.8:
                rows.append((k, ln))
                break
    best: dict[int, Line] | None = None
    for k0, a in rows:
        col = {k0: a}
        for k, ln in rows:
            if k not in col and abs(ln.x - a.x) <= max(4, a.h):
                col[k] = ln
        if len(col) < 3:
            continue
        ks = sorted(col)
        steps = [(col[kb].cy - col[ka].cy) / float(kb - ka) for ka, kb in zip(ks, ks[1:])]
        if min(steps) <= 0 or max(steps) > 1.25 * min(steps):
            continue
        if best is None or len(col) > len(best):
            best = col
    if best is None:
        return None
    ks = sorted(best)
    step = (best[ks[-1]].cy - best[ks[0]].cy) / float(ks[-1] - ks[0])
    return step, best[ks[0]].cy - ks[0] * step


def layout_from(step: float, row0: float, w: int, h: int) -> Layout | None:
    # None: the spots as measured already fit this window.
    old = ROW_STEP * h
    if abs(step - old) <= 0.12 * old and abs(row0 - ROW_TOP * h) <= 0.4 * old:
        return None
    scale = step / (ROW_STEP * REF_H)
    return Layout(int(w), int(h), scale, row0 - (h - (1.0 - ROW_TOP) * REF_H * scale))


def area_px(area: dict, w: int, h: int) -> tuple[int, int, int, int]:
    x0 = max(0, min(w - 1, int(round(area["x"] * w))))
    y0 = max(0, min(h - 1, int(round(area["y"] * h))))
    x1 = max(x0 + 1, min(w, int(round((area["x"] + area["w"]) * w))))
    y1 = max(y0 + 1, min(h, int(round((area["y"] + area["h"]) * h))))
    return x0, y0, x1, y1


def crop(frame: np.ndarray | None, area: dict) -> tuple[np.ndarray | None, int, int]:
    if frame is None:
        return None, 0, 0
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = area_px(area, w, h)
    return frame[y0:y1, x0:x1], x0, y0


def _channels(img: np.ndarray):
    px = img.astype(np.int16)
    return px[..., 0], px[..., 1], px[..., 2]


def find_button(img: np.ndarray | None, client_w: int, client_h: int) -> Button | None:
    if img is None or img.size == 0:
        return None
    b, g, r = _channels(img)
    gold = (np.abs(r - 231) <= 22) & (np.abs(g - 196) <= 22) & (np.abs(b - 120) <= 28)
    grey = (np.abs(r - 127) <= 12) & (np.abs(g - 108) <= 12) & (np.abs(b - 66) <= 12)
    return _solid_button(((gold, True), (grey, False)), client_w, client_h)


def find_dim_button(img: np.ndarray | None, client_w: int, client_h: int) -> Button | None:
    # FOLLOW THE LIGHT on THE LIGHT IS FADING is a darker gold (190, 150, 60) than the usual buttons.
    if img is None or img.size == 0:
        return None
    b, g, r = _channels(img)
    dim = (np.abs(r - 190) <= 22) & (np.abs(g - 150) <= 22) & (np.abs(b - 60) <= 28)
    return _solid_button(((dim, True),), client_w, client_h)


def _solid_button(masks, client_w: int, client_h: int) -> Button | None:
    min_w = max(40, int(client_w * 0.05))
    min_h = max(12, int(client_h * 0.02))
    best: Button | None = None
    for mask, active in masks:
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if w < min_w or h < min_h or w < 2.5 * h or area < 0.7 * w * h:
                continue
            if best is None or w * h > best.box.w * best.box.h:
                best = Button(Box(x, y, w, h), active)
    return best


def path_banner(frame: np.ndarray | None) -> bool:
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x, y, bw, bh = BANNER_BAND
    band = frame[int(y * h):int((y + bh) * h), int(x * w):int((x + bw) * w)]
    if band.size == 0:
        return False
    b, g, r = _channels(band)
    brown = (r >= 105) & (r <= 165) & (g >= 70) & (g <= 120) & (b >= 35) & (b <= 85) & (r - b >= 50)
    return float(brown.mean()) >= 0.06


def _gold_run(row: np.ndarray, lo: int, hi: int) -> tuple[int, int] | None:
    idx = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    best = None
    for s, e in zip(idx[::2].tolist(), idx[1::2].tolist()):
        if lo <= e - s <= hi and (best is None or e - s > best[1] - best[0]):
            best = (s, e)
    return best


def victory_banner(frame: np.ndarray | None) -> bool:
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x, y, bw, bh = VICTORY_BAND
    x0, y0 = int(x * w), int(y * h)
    band = frame[y0:int((y + bh) * h), x0:int((x + bw) * w)]
    if band.size == 0:
        return False
    b, g, r = _channels(band)
    gold = (np.abs(r - 231) <= 45) & (np.abs(g - 196) <= 45) & (np.abs(b - 120) <= 60)
    ref = ui_ref(w, h)
    ref_h = ref / (REF_W / REF_H)
    lo, hi = int(ref * 0.27), int(ref * 0.50)
    lines = []
    for i in np.flatnonzero(gold.sum(axis=1) >= lo).tolist():
        run = _gold_run(gold[i], lo, hi)
        if run is not None and abs(x0 + (run[0] + run[1]) / 2.0 - w / 2.0) <= w * 0.05:
            lines.append((i, run[0], run[1]))
    for k, (ya, sa, ea) in enumerate(lines):
        for yb, sb, eb in lines[k + 1:]:
            if 0.055 * ref_h <= yb - ya <= 0.10 * ref_h and abs(sa - sb) <= ref * 0.012 and abs(ea - eb) <= ref * 0.012:
                return True
    return False


def _border_column(frame: np.ndarray | None, band: tuple[float, float, float, float]) -> bool:
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x, y, bw, bh = _fit_band(band, w, h)
    reg = frame[int(y * h):int((y + bh) * h), int(x * w):max(int(x * w) + 1, int((x + bw) * w))]
    if reg.size == 0:
        return False
    b, g, r = _channels(reg)
    edge = (np.abs(r - 80) <= 28) & (np.abs(g - 110) <= 28) & (np.abs(b - 143) <= 30)
    return float(edge.mean(axis=0).max()) >= 0.5


def your_turn(frame: np.ndarray | None) -> bool:
    return _border_column(frame, TURN_BAND)


def in_battle(frame: np.ndarray | None) -> bool:
    return _border_column(frame, BOX_BAND)


def is_retry(text: str) -> bool:
    t = norm(text)
    return "AGAIN" in t or "RETRY" in t or "PLAY AG" in t


def is_chest(text: str) -> bool:
    t = norm(text)
    return "CLICK TO" in t or "TO OPEN" in t


def rarity_list(text: str) -> list[str]:
    return [norm(p) for p in str(text or "").split(",") if norm(p)]


# Rarity tags OCR can't read (dark text on a bright fill came back as "mynâ€¢11C"), found by fill colour.
# BGR, as frames are.
TAG_FILLS = {"MYTHIC": (200, 110, 255)}


def find_tags(img: np.ndarray | None, client_h: int) -> list[tuple[str, Box]]:
    if img is None or img.size == 0:
        return []
    px = img.astype(np.int16)
    out = []
    min_h, max_h = max(6, int(client_h * 0.010)), max(12, int(client_h * 0.035))
    for rarity, (fb, fg, fr) in TAG_FILLS.items():
        mask = (np.abs(px[..., 0] - fb) <= 25) & (np.abs(px[..., 1] - fg) <= 25) & (np.abs(px[..., 2] - fr) <= 25)
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            # A filled tag, not the card's thin pink outline: wide, short and mostly solid around its text.
            if min_h <= h <= max_h and w >= 3 * h and area >= 0.55 * w * h:
                out.append((rarity, Box(x, y, w, h)))
    return out


def tag_crop(img: np.ndarray, box: Box) -> np.ndarray:
    # Dark letters to black on white, scaled up, so the text reader gets plain text.
    part = img[box.y:box.y + box.h, box.x:box.x + box.w]
    ink = part.max(axis=2) < 110
    out = np.where(ink, 0, 255).astype(np.uint8)
    out = cv2.copyMakeBorder(out, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(cv2.resize(out, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)


def with_tags(lines: list[Line], tags: list[tuple[str, Box, str]]) -> list[Line]:
    # Swap whatever OCR made of each coloured tag for its rarity word.
    out = [ln for ln in lines if not any(b.x - 2 <= ln.cx <= b.x + b.w + 2 and b.y - 2 <= ln.cy <= b.y + b.h + 2 for _r, b, _t in tags)]
    for rarity, b, read in tags:
        word = next((w for w in norm(read).split() if w in TAG_WORDS), rarity)
        out.append(Line(word, b.x, b.y, b.w, b.h))
    return out


TAG_WORDS = {"COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "HEIRLOOM"}


def _rarity_in(text: str, rarities: list[str]) -> str | None:
    # A tag on its own ("MYTHIC") or a word in a type line ("MYTHIC ULTRA SIGIL", "BLOODLINE HEIRLOOM").
    words = norm(text).split()
    for r in rarities:
        if any(w == r or (len(r) >= 5 and difflib.SequenceMatcher(None, w, r).ratio() >= 0.8) for w in words):
            return r
    return None


def find_loot(lines: list[Line], rarities: list[str], client_h: int) -> list[tuple[str, str]]:
    # The item name sits right above the rarity line, either centred (spoils cards) or
    # left-aligned (lists). Returns (rarity, item name) for every watched rarity found.
    def aligned(a: Line, b: Line) -> bool:
        return abs(a.cx - b.cx) <= max(a.w, b.w, client_h * 0.06) * 0.5 or abs(a.x - b.x) <= max(4, client_h * 0.01)

    def next_up(cur: Line, gap: float) -> Line | None:
        up = [o for o in lines if o.y < cur.y and cur.y - o.y <= gap and aligned(o, cur)]
        return max(up, key=lambda o: o.y) if up else None

    lines = join_rows(lines) if lines else lines
    # OCR boxes only cover capital height, so gaps are measured against the window instead.
    name_gap = client_h * 0.055
    found = {id(ln): _rarity_in(ln.text, rarities) for ln in lines}
    hits, used = [], set()
    for ln in lines:
        rarity = found[id(ln)]
        if rarity is None:
            continue
        # "Dragonborn Heirloom" right above "BLOODLINE HEIRLOOM": the upper one is the name, not a second drop.
        if any(found[id(o)] and o.y > ln.y and o.y - ln.y <= client_h * 0.03 and aligned(o, ln) for o in lines):
            continue
        names = []
        cur = next_up(ln, name_gap)
        while cur is not None:
            names.insert(0, cur.text)
            used.add(id(cur))
            cur = next_up(cur, max(cur.h * 2, client_h * 0.016))
        hits.append((ln, rarity, " ".join(names) or "unknown item"))
    return [(rarity, name) for ln, rarity, name in hits if id(ln) not in used]


def is_skip(text: str) -> bool:
    return norm(text).startswith("SKIP")


def is_home(text: str) -> bool:
    # RETURN HOME path card ("TURN BACK") and the sidebar button ("PRESS AGAIN TO GO HOME").
    t = norm(text)
    return any(w in t for w in HOME_WORDS) or "GO HOME" in t


def parse_act(text: str) -> int | None:
    m = _ACT.search(str(text or "").upper())
    if not m:
        return None
    try:
        act, total = int(m.group(1).translate(_DIGIT_FIX)), int(m.group(2).translate(_DIGIT_FIX))
    except ValueError:
        return None
    return act if 1 <= act <= total <= 20 else None


def is_castle(text: str) -> bool:
    t = norm(text)
    return "CASTLE" in t or t.startswith("RETURN")


def button_kind(text: str) -> str | None:
    t = norm(text)
    if not t:
        return None
    if "BUY" in t:
        return "buy"
    if any(w.startswith("PART") for w in t.split()):
        # The PARTY tab is gold mid-fight; Space on it hit whatever the battle menu cursor was on.
        # On a narrow window it reads "PART".
        return "ignore"
    # Small text on a narrow window: FOLLOW THE LIGHT reads as "FOLLOK LIGHT" / "FOLLO'K THE LIGHT".
    if "FOLLO" in t or "THE LIGHT" in t or is_castle(t):
        return "light"
    if is_retry(t):
        return "retry"
    if "CONTIN" in t.replace(" ", ""):
        return "continue"
    if "BATTLE" in t or "DONE" in t:
        return "battle"
    return None


def back_header(frame: np.ndarray | None) -> bool:
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x, y, bw, bh = _fit_band(BACK_BAND, w, h)
    reg = frame[int(y * h):int((y + bh) * h), int(x * w):int((x + bw) * w)]
    if reg.size == 0:
        return False
    b, g, r = _channels(reg)
    gold = (np.abs(r - 231) <= 35) & (np.abs(g - 196) <= 35) & (np.abs(b - 120) <= 45)
    return float(gold.mean()) >= 0.02


def row_point(k: int) -> dict:
    return {"x": 0.09, "y": ROW_TOP + k * ROW_STEP}


def row_band(frame: np.ndarray, pt: dict) -> np.ndarray | None:
    if frame is None:
        return None
    h, w = frame.shape[:2]
    lay = fight_layout(w, h)
    step = ROW_STEP * REF_H * lay.scale / h if lay else ROW_STEP
    x0, x1 = (_fit_x(ROW_X[0], lay), _fit_x(ROW_X[1], lay)) if lay else ROW_X
    half = max(4, int(round(h * step * 0.45)))
    cy = int(round(pt["y"] * h))
    return frame[max(0, cy - half):min(h, cy + half), int(x0 * w):int(x1 * w)]


def guard_alert(frame: np.ndarray | None, pt: dict) -> bool:
    band = row_band(frame, pt)
    if band is None or band.size == 0:
        return False
    b, g, r = _channels(band)
    yellow = (r >= 170) & (g >= 120) & (b <= 140) & (r - b >= 70)
    if float(yellow.mean()) < 0.008:
        return False
    cols = np.flatnonzero(yellow.any(axis=0))
    return len(cols) > 0 and cols[-1] - cols[0] >= band.shape[1] * 0.12


def row_lit(frame: np.ndarray | None, pt: dict) -> bool:
    band = row_band(frame, pt)
    if band is None or band.size == 0:
        return False
    b, g, r = _channels(band)
    white = np.minimum(np.minimum(b, g), r) >= 200
    if float(white.mean()) < 0.01:
        return False
    cols = np.flatnonzero(white.any(axis=0))
    return cols[-1] - cols[0] >= band.shape[1] * 0.12


def text_lit(img: np.ndarray, box) -> bool:
    part = img[max(0, box.y):box.y + box.h, max(0, box.x):box.x + box.w]
    if part.size == 0:
        return True
    b, g, r = _channels(part)
    # Brightest channel, not darkest: ULTRA skills are drawn in colour (gold etc.),
    # which never has all three channels >= 200 and read as "greyed out".
    return float((np.maximum(np.maximum(b, g), r) >= 200).mean()) >= 0.03


def skill_list_open(frame: np.ndarray | None, area: dict) -> bool:
    if frame is None:
        return False
    h, w = frame.shape[:2]
    lay = fight_layout(w, h)
    pad = _fit_x(0.03, lay) if lay else 0.03
    x0 = int(max(0.0, area["x"] - pad) * w)
    x1 = int(min(1.0, area["x"] + pad) * w)
    y0 = int((area["y"] + area["h"] * 0.1) * h)
    y1 = int(min(area["y"] + area["h"] * 0.9, _fit_y(0.675, lay) if lay else 0.675) * h)
    if x1 - x0 < 2 or y1 - y0 < 8:
        return False
    b, g, r = _channels(frame[y0:y1, x0:x1])
    edge = (np.abs(r - 82) <= 28) & (np.abs(g - 111) <= 28) & (np.abs(b - 140) <= 30)
    return float(edge.mean(axis=0).max()) >= 0.6


def _panel(img: np.ndarray) -> np.ndarray:
    b, g, r = _channels(img)
    return (b >= r + 18) & (b >= g + 10) & (r <= 80) & (b <= 120) & (b >= 25)


def find_cards(img: np.ndarray | None, client_h: int) -> list[Box]:
    if img is None or img.size == 0:
        return []
    mask = _panel(img)
    rows = mask.mean(axis=1) >= 0.30
    cards = []
    min_h = max(30, int(client_h * 0.06))
    d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
    for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if e - s < min_h:
            continue
        cols = np.flatnonzero(mask[s:e].mean(axis=0) >= 0.3)
        if len(cols) == 0:
            continue
        x0, x1 = int(cols[0]), int(cols[-1])
        if x0 <= 2 and x1 >= img.shape[1] - 3:
            body = img[s:e, x0:x1 + 1][mask[s:e, x0:x1 + 1]]
            if len(body) == 0 or float(np.median(body.max(axis=1))) > 100:
                continue
        cards.append(Box(x0, int(s), x1 - x0 + 1, int(e - s)))
    return merge_cards(cards, client_h)


def merge_cards(cards: list[Box], client_h: int) -> list[Box]:
    gap = max(3, int(client_h * 0.014))
    out: list[Box] = []
    for c in sorted(cards, key=lambda b: b.y):
        if out and c.y - (out[-1].y + out[-1].h) <= gap and abs(c.cx - out[-1].cx) <= max(c.w, out[-1].w) * 0.1:
            p = out[-1]
            x0, y0 = min(p.x, c.x), p.y
            x1, y1 = max(p.x + p.w, c.x + c.w), c.y + c.h
            out[-1] = Box(x0, y0, x1 - x0, y1 - y0)
        else:
            out.append(c)
    return out


def find_options(img: np.ndarray | None, client_h: int) -> list[Box]:
    if img is None or img.size == 0:
        return []
    h, w = img.shape[:2]
    px = img.astype(np.int16)
    hi = np.maximum(np.maximum(px[..., 0], px[..., 1]), px[..., 2])
    lo = np.minimum(np.minimum(px[..., 0], px[..., 1]), px[..., 2])
    sat = (hi - lo >= 70) & (hi >= 140)
    dark = hi <= 60
    limit = max(16, int(w * 0.15))
    near = max(3, int(round(w * 0.0087)))
    far = max(near + 2, int(round(w * 0.013)))
    if w < limit + far + 2:
        return []
    hit = sat[:, :limit] & (dark[:, near:limit + near] | dark[:, far:limit + far])
    rows = hit.any(axis=1)
    min_h = max(14, int(client_h * 0.028))
    out = []
    d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
    for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if e - s < min_h:
            continue
        cols = np.flatnonzero(hit[s:e].sum(axis=0) >= (e - s) * 0.6)
        x = int(cols[0]) if len(cols) else 0
        out.append(Box(x, int(s), w - x, int(e - s)))
    return out


def parse_header(text: str) -> tuple[str, int, int] | None:
    up = str(text or "").upper()
    m = _EN.search(up)
    if m:
        fix = str.maketrans({"O": "0", "I": "1", "L": "1", "|": "1"})
        try:
            return "menu", int(m.group(1).translate(fix)), int(m.group(2).translate(fix))
        except ValueError:
            pass
    if "CHOOSE" in up or "FOE" in up:
        return "foe", 0, 0
    if "BACK" in up:
        return "back", 0, 0
    return None


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper().replace("'", "")).split())


def matches(keyword: str, text: str) -> bool:
    k, t = norm(keyword), norm(text)
    if not k or not t:
        return False
    if k in t:
        return True
    words = t.split()
    for kw in k.split():
        if len(kw) < 3:
            if kw not in words:
                return False
            continue
        if not any(difflib.SequenceMatcher(None, kw, tw).ratio() >= 0.8 for tw in words):
            return False
    return True


def lines_in(lines: list[Line], box: Box) -> list[Line]:
    return [ln for ln in lines if box.y <= ln.cy <= box.y + box.h and ln.cx >= box.x - 4]


def rank(text: str, prefer: list[str], avoid: list[str]) -> tuple[int, int]:
    avoided = any(matches(a, text) for a in avoid)
    pos = next((i for i, p in enumerate(prefer) if matches(p, text)), len(prefer))
    return (1 if avoided else 0, pos)


def letters_matched(want: str, label: str) -> int:
    a, b = want.replace(" ", ""), label.replace(" ", "")
    blocks = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(m.size for m in blocks if m.size >= 2)


def words_match(want: str, label: str) -> bool:
    words = label.split()
    for kw in want.split():
        if len(kw) < 3:
            continue
        if not any(difflib.SequenceMatcher(None, kw, tw).ratio() >= 0.7 for tw in words):
            return False
    return True


def join_rows(lines: list[Line]) -> list[Line]:
    # Windows OCR splits two-colour rows ("ULTRA:" + "LEGION GATE") into separate lines,
    # listing every "ULTRA:" first. Put pieces on the same row back together, left to right.
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda l: l.cy):
        row = rows[-1] if rows else None
        if row is not None and abs(ln.cy - row[0].cy) <= max(4, min(ln.h, row[0].h) * 0.6):
            row.append(ln)
        else:
            rows.append([ln])
    out = []
    for row in rows:
        row.sort(key=lambda l: l.x)
        # Only join pieces that touch: spoils cards side by side stay separate.
        groups = [[row[0]]]
        for ln in row[1:]:
            prev = groups[-1][-1]
            if ln.x - (prev.x + prev.w) <= max(12, 3 * min(ln.h, prev.h)):
                groups[-1].append(ln)
            else:
                groups.append([ln])
        for g in groups:
            x0, y0 = min(l.x for l in g), min(l.y for l in g)
            x1, y1 = max(l.x + l.w for l in g), max(l.y + l.h for l in g)
            out.append(Line(" ".join(l.text for l in g), x0, y0, x1 - x0, y1 - y0))
    return out


def skill_line(lines: list[Line], name: str, letters: int = 0, strict: bool = False) -> Line | None:
    # strict (Turn 1/2 skills): every word has to show up, so "ULTRA: LEGION GATE"
    # can't grab "ULTRA: DRAGON GATE" just because 5+ letters overlap.
    want = norm(name)
    if not want:
        return None
    need = 0 if strict else (min(int(letters), len(want.replace(" ", ""))) if letters and letters > 0 else 0)
    best, score = None, (0, 0.0)
    for ln in join_rows(lines):
        label = norm(_COST.sub("", " " + ln.text))
        if not label or label.startswith("SKILLS"):
            continue
        s = 1.0 if want == label else difflib.SequenceMatcher(None, want, label).ratio()
        if want in label:
            s = max(s, 0.9)
        got = letters_matched(want, label)
        if strict:
            ok = want in label or words_match(want, label)
        else:
            ok = got >= need if need else s >= 0.72
        if ok and (got, s) > score:
            best, score = ln, (got, s)
    return best
