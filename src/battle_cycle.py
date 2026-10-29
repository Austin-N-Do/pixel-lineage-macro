from __future__ import annotations

import difflib
import time
from typing import Callable

import cv2
import mss
import numpy as np

from advanced_settings import DEFAULT_ADVANCED
from app_paths import writable_dir
from games import BAR, DODGE, LANE, LOCK, PanelPlayer, find_meter, find_panel, find_ring, lock_box, panel_game, ui_scale
from input_actions import release_inputs, sleep_interruptible, tap_key
from mouse_control import gui_click_at, hover_at, jitter_at, wheel_at
from ocr import Line, Reader
from platform_keys import key_press, key_release
from roblox_geo import roblox_client_rect
from screens import (
    CHEST_BAND,
    DEFAULT_AREAS,
    GUARD_ROW,
    MENU_BAND,
    PATH_CONFIRM,
    SCROLL_ROW,
    SKIP_BAND,
    USUAL_CARDS,
    Box,
    area_px,
    back_header,
    button_kind,
    crop,
    find_button,
    find_cards,
    find_dim_button,
    find_loot,
    find_tags,
    tag_crop,
    with_tags,
    find_options,
    guard_alert,
    in_battle,
    is_castle,
    is_chest,
    is_skip,
    lines_in,
    norm,
    parse_header,
    path_banner,
    rank,
    rarity_list,
    row_lit,
    row_point,
    skill_line,
    skill_list_open,
    text_lit,
    victory_banner,
    your_turn,
)
from timing import ATTACK, DODGE as BAR_DODGE, Player, find_bar, has_block, ui_ref
from win_focus import focus_roblox

SPACE = "space"
DEFAULT_POINTS = {
    "attack_btn": row_point(0),
    "skills_btn": row_point(1),
    "scroll_btn": row_point(SCROLL_ROW),
    "back_btn": {"x": 0.1344, "y": 0.7242},
    "guard_btn": row_point(GUARD_ROW),
    "replay_btn": {"x": 0.554, "y": 0.6825},
}

PLAYED = "played"
SEEN = "seen"
CLEAR = ""

HIT = "hit"
OPEN = "open"
PICK = "pick"
CHECK = "check"
CAST = "cast"
BAR_WAIT_SEC = 0.5
BACK_GAP_SEC = 0.6
BACK_TRIES = 4
SCROLL_TRIES = 3
FIGHT_GAP_SEC = 6.0
COMBO_TRIES = 3
OUT_OF_FIGHT = ("victory", "path", "event", "end", "light")
TURN_GAP_SEC = 0.4
EN_TRIES = 3
SKILL_MISSES = 3
CASTLE_TRIES = 6
LOOT_SETTLE_SEC = 0.3
LOOT_WAIT_SEC = 3.0
CONTINUE_GAP_SEC = 0.6
LOOT_TITLES = {"SPOILS", "DEFEATED", "LOOT", "REWARDS"}
ANY_RARITY = {"COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "HEIRLOOM"}
LOOT_HOLD_SEC = 2.0
LOOT_DEDUP_SEC = 90.0
CHEST_LOOT_BAND = {"x": 0.20, "y": 0.08, "w": 0.60, "h": 0.84}
DEBUG_KEEP = 60
JITTER_KEYS = ("attack_btn", "skills_btn", "scroll_btn")

cv2.setNumThreads(1)


class Grabber:
    def __init__(self) -> None:
        self._sct = (getattr(mss, "MSS", None) or mss.mss)()

    def grab(self, x: int, y: int, w: int, h: int) -> np.ndarray | None:
        if w < 1 or h < 1:
            return None
        try:
            shot = self._sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
        except Exception:
            return None
        return np.ascontiguousarray(np.asarray(shot, dtype=np.uint8)[:, :, :3])

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


def client():
    rect = roblox_client_rect()
    if rect is None or rect.w < 64 or rect.h < 64:
        return None
    return rect


def area_of(cfg: dict, key: str) -> dict:
    return cfg.get(key) or DEFAULT_AREAS[key]


def point_of(cfg: dict, key: str) -> dict:
    return (cfg.get("points") or {}).get(key) or DEFAULT_POINTS[key]


def _union(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def search_box(cfg: dict, w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = area_px(area_of(cfg, "mg_area"), w, h)
    pad = max(4, int(round(min(w, h) * 0.02)))
    side = pad + int(round((x1 - x0) * 0.02))
    up = pad + int(round((y1 - y0) * 0.3))
    return max(0, x0 - side), max(0, y0 - up), min(w, x1 + side), min(h, y1 + pad)


def menu_box(cfg: dict, w: int, h: int) -> tuple[int, int, int, int]:
    return _union(area_px(area_of(cfg, "event_area"), w, h), area_px(MENU_BAND, w, h))


def en_areas(cfg: dict) -> list[dict]:
    area = area_of(cfg, "en_area")
    dy = area["h"] * 0.75
    out = [area, {"x": area["x"], "y": max(0.0, area["y"] - dy), "w": area["w"], "h": area["h"] + 2 * dy}]
    if cfg.get("en_area"):
        out.append(DEFAULT_AREAS["en_area"])
    return out


def read_en(reader: Reader, frame: np.ndarray, cfg: dict) -> tuple[int, int] | None:
    for area in en_areas(cfg):
        img, _x, _y = crop(frame, area)
        head = parse_header(reader.text(img))
        if head is not None and head[0] == "menu":
            return head[1], head[2]
    return None


def _panel_report(cfg: dict, frame: np.ndarray, rect) -> str | None:
    x0, y0, x1, y1 = search_box(cfg, rect.w, rect.h)
    img = frame[y0:y1, x0:x1]
    panel = find_panel(img, rect.w, rect.h)
    if panel is None:
        return None
    found = panel_game(panel, img, str(cfg.get("class") or ""))
    if found is None:
        return "There's a box up there but its top line isn't a minigame colour, so it keeps pressing Space."
    game, name, _who = found
    if game in (BAR, DODGE):
        return "%s box is up (box %d px wide), it plays the bar as soon as the bar shows up." % (name, panel.right - panel.left)
    scale = panel.scale
    body = img[panel.top + max(12, int(round(60 * scale))):, panel.left:panel.right]
    if game == LOCK:
        seen = "the frame is gold right now" if lock_box(body, scale) is not None else "waiting for the frame to turn gold"
    elif game == LANE:
        seen = "found the ring" if find_ring(body, scale) is not None else "can't see the ring yet"
    else:
        seen = "found the power meter" if find_meter(body, scale) is not None else "can't see the power meter yet"
    return "%s minigame box is up, %s." % (name, seen)


def read_label(reader: Reader, img: np.ndarray, box: Box) -> str:
    part = img[box.y:box.y + box.h, box.x:box.x + box.w]
    f = max(1.0, min(5.0, 60.0 / max(1, box.h)))
    if f > 1.05:
        part = cv2.resize(part, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
    return reader.text(part)


def _title(lines: list[Line]) -> str:
    return lines[0].text if lines else ""


STATUS_LOG_MAX = 400_000


def log_status(msg: str) -> None:
    # debug/status.log: every status change with a time, trimmed to the newest half when it grows.
    try:
        out = writable_dir() / "debug"
        out.mkdir(exist_ok=True)
        path = out / "status.log"
        if path.exists() and path.stat().st_size > STATUS_LOG_MAX:
            text = path.read_text(encoding="utf-8", errors="ignore")
            path.write_text(text[len(text) // 2:], encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def save_debug(tag: str, img: np.ndarray | None, lines: list[Line]) -> None:
    # Keeps the last DEBUG_KEEP misses in a "debug" folder so a bad read can be looked at later.
    try:
        out = writable_dir() / "debug"
        out.mkdir(exist_ok=True)
        stem = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), "".join(c if c.isalnum() else "_" for c in tag)[:40])
        if img is not None and img.size:
            cv2.imwrite(str(out / (stem + ".png")), img)
        (out / (stem + ".txt")).write_text("\n".join("%s  (x=%d y=%d w=%d h=%d)" % (ln.text, ln.x, ln.y, ln.w, ln.h) for ln in lines) or "(nothing read)", encoding="utf-8")
        for old in sorted(out.glob("*.txt"))[:-DEBUG_KEEP]:
            old.unlink(missing_ok=True)
            old.with_suffix(".png").unlink(missing_ok=True)
    except Exception:
        pass


def choose(cards: list[Box], lines: list[Line], cfg: dict) -> int | None:
    if not cards:
        return None
    prefer = list(cfg.get("path_prefer") or [])
    avoid = list(cfg.get("path_avoid") or [])
    scored = []
    for i, card in enumerate(cards):
        text = " ".join(ln.text for ln in lines_in(lines, card))
        scored.append((rank(text, prefer, avoid), i))
    return min(scored)[1]


def describe(cfg: dict, reader: Reader, grabber: Grabber) -> str:
    rect = client()
    if rect is None:
        return "Roblox not found, open it first."
    frame = grabber.grab(rect.x, rect.y, rect.w, rect.h)
    if frame is None:
        return "Couldn't capture Roblox."
    sx0, sy0, sx1, sy1 = search_box(cfg, rect.w, rect.h)
    panel = _panel_report(cfg, frame, rect)
    if panel is not None:
        return panel
    ref = ui_ref(rect.w, rect.h)
    img, _x, _y = crop(frame, area_of(cfg, "mg_area"))
    bar = find_bar(img, ref) or find_bar(frame[sy0:sy1, sx0:sx1], ref)
    if bar is not None:
        return "A %s bar is on screen but there's no minigame box above it to read, so it leaves it alone and keeps pressing Space." % ("dodge" if bar.kind == BAR_DODGE else "attack")
    if in_battle(frame):
        name = str(cfg.get("skill_name") or "").strip()
        skill = bool(cfg.get("skill_on")) and bool(name)
        gap = float(cfg["advanced"]["skill_space_sec" if skill else "battle_space_sec"])
        if back_header(frame) and skill_list_open(frame, area_of(cfg, "skills_area")):
            return "Battle, the skill list is open. Unless it's picking your skill right now it clicks BACK and goes back to attacking."
        if back_header(frame):
            return "Battle, CHOOSE A FOE is up. Space every %.2f s, and it clicks BACK if it sticks for %.0f s." % (gap, float(cfg["advanced"]["stuck_fix_sec"]))
        if your_turn(frame) and cfg.get("guard_on", True) and guard_alert(frame, point_of(cfg, "guard_btn")):
            return "Battle, your turn, GUARD ! is lit up, it guards this turn instead of attacking."
        if not your_turn(frame):
            return "Battle, enemy's turn. It stays quiet so it can't ruin the dodge (one Space if nothing happens for %.1f s), and it plays a minigame the moment one shows up." % float(cfg["advanced"]["enemy_space_sec"])
        if cfg.get("scroll_on") and row_lit(frame, point_of(cfg, "scroll_btn")):
            return "Battle, your turn, SCROLL is ready, it uses it this turn."
        combo = [str(cfg.get(k) or "").strip() for k in ("combo_1", "combo_2")] if cfg.get("combo_on") else ["", ""]
        first = "Turn 1 %s, turn 2 %s, every fight. " % (combo[0] or "normal", combo[1] or "normal") if any(combo) else ""
        if not skill:
            return "Battle, your turn. %sMouse on ATTACK, Space every %.2f s." % (first, gap)
        en = read_en(reader, frame, cfg)
        if en is None:
            img, _x, _y = crop(frame, area_of(cfg, "en_area"))
            return "Battle, your turn, but the EN area read '%s' instead of EN 2/10, so it just attacks. Fix it with Select on EN area." % (reader.text(img) or "nothing")
        need = int(cfg.get("skill_en") or 0)
        plan = "it goes for %s now" % name if en[0] >= need else "it attacks until EN is %d" % need
        return "Battle, your turn. %sEN %d/%d, %s needs %d, %s." % (first, en[0], en[1], name, need, plan)
    x0, y0, x1, y1 = menu_box(cfg, rect.w, rect.h)
    img = frame[y0:y1, x0:x1]
    btn = find_button(img, rect.w, rect.h)
    dim = find_dim_button(img, rect.w, rect.h) if btn is None else None
    if dim is not None and button_kind(read_label(reader, img, dim.box)) == "light":
        btn = dim
    if btn is not None:
        label = read_label(reader, img, btn.box)
        kind = button_kind(label)
        if kind == "buy":
            return "Shop, it leaves the BUY buttons alone and clicks DONE - TO BATTLE!."
        if kind == "light":
            if cfg.get("follow_light"):
                return "The Light is fading, it clicks FOLLOW THE LIGHT and goes on to act 6."
            line = next((ln for ln in reader.read(img) if is_castle(ln.text)), None)
            return "The Light is fading, it clicks RETURN TO THE CASTLE (%s)." % ("found its label" if line or is_castle(label) else "label not read, it clicks right of FOLLOW THE LIGHT")
        if kind == "retry":
            return "Run finished, PLAY AGAIN is %s." % ("ready, it clicks it" if btn.active else "not lit up yet")
        if kind == "continue":
            return "CONTINUE button, it presses Space (and clicks it if Space doesn't work)."
        if btn.active and kind == "battle":
            return "%s is ready, it clicks it." % label
        if not btn.active:
            ev, _ex, _ey = crop(frame, area_of(cfg, "event_area"))
            opts = find_options(ev, rect.h)
            lines = reader.read(ev)
            names = [_title(lines_in(lines, o)) or "?" for o in opts]
            return "Event screen, TO BATTLE! is greyed out. Choices: %s" % (", ".join(names) or "none found")
        return "Gold button reading '%s', it presses Space on it." % (label or "nothing")
    if path_banner(frame):
        img, _x, _y = crop(frame, area_of(cfg, "path_area"))
        cards = find_cards(img, rect.h)
        lines = reader.read(img)
        if not cards:
            return "Choose Your Path screen, but no path cards were found in the path area, it clicks where the cards usually are."
        names = [_title(lines_in(lines, c)) or "?" for c in cards]
        pick = choose(cards, lines, cfg)
        return "Choose Your Path: %s. It would pick %s." % (", ".join(names), names[pick] if pick is not None else "nothing")
    if victory_banner(frame):
        return "VICTORY, it presses Space until the Choose Your Path screen shows up."
    img, _x, _y = crop(frame, CHEST_BAND)
    if is_chest(reader.text(img)):
        return "Chest, it presses Space to open it."
    img, _x, _y = crop(frame, SKIP_BAND)
    if any(is_skip(ln.text) for ln in reader.read(img)):
        return "Cutscene, it clicks SKIP."
    return "Not in a fight and nothing to click, it presses Space every %.2f s." % float(cfg["advanced"]["wait_space_sec"])


class Runner:
    def __init__(
        self,
        cfg: dict,
        reader: Reader,
        player: Player,
        aborted: Callable[[], bool],
        status: Callable[[str], None],
        note: Callable[[str, str], None],
    ) -> None:
        self.cfg = cfg
        self.reader = reader
        self.player = player
        self.panels = PanelPlayer()
        self.aborted = aborted
        self._status_cb = status
        self._status_last = ""
        self.note = note
        self.grabber = Grabber()
        self._last_screen = ""
        self._event_clicks: dict[int, int] = {}
        self._chest_tries = 0
        self._continue_tries = 0
        self._retry_at = 0.0
        self._retry_tries = 0
        self._next_chest = 0.0
        self._label = ("", 0, 0, 0.0)
        self._next_space = 0.0
        self._hover = ""
        self._mode = HIT
        self._turn = False
        self._menu_at = 0.0
        self._nudges = 0
        self._en: tuple[int, int] | None = None
        self._en_read = False
        self._en_tries = 0
        self._en_wait = 0.0
        self._want = ""
        self._want_combo = False
        self._misses = 0
        self._turn_no = 0
        self._turn_off = 0.0
        self._combo_step = 0
        self._combo_turn = -1
        self._combo_tries = 0
        self._skill_off = False
        self._skill_block = 0.0
        self._skill_at = 0.0
        self._skill_tries = 0
        self._mg_block = 0.0
        self._mg_game = ""
        self._bar_at = 0.0
        self._seen: tuple | None = None
        self._win = 0.0
        self._scrolls = 0
        self._scroll_dir = 1
        self._list_text = ""
        self._reread = False
        self._back_at = 0.0
        self._castle_tries = 0
        self._next_skip = 0.0
        self._loot_done = False
        self._loot_sent: dict[tuple[str, str], float] = {}
        self._back_tries = 0
        self._scroll_turn = False
        self._scroll_tries = 0
        self._scroll_at = 0.0
        self._guard_tries = 0
        self._guarded = False
        self._path_at = 0.0
        self._path_tries = 0
        self._path_cards = 0
        self._path_pick = 0
        self._fight_at = time.perf_counter()
        self._replay_at = 0.0
        self._moved = time.perf_counter()

    @property
    def adv(self) -> dict:
        return self.cfg["advanced"]

    def status(self, msg: str) -> None:
        self._status_cb(msg)
        if msg != self._status_last:
            self._status_last = msg
            log_status("[turn %d, step %d] %s" % (self._turn_no, self._combo_step, msg))

    def _num(self, key: str, low: float) -> float:
        try:
            return max(low, float(self.adv[key]))
        except (KeyError, TypeError, ValueError):
            return max(low, float(DEFAULT_ADVANCED.get(key, low)))

    def close(self) -> None:
        self.grabber.close()
        release_inputs()

    def _sleep(self, sec: float) -> bool:
        return sleep_interruptible(max(0.0, float(sec)), self.aborted)

    def _progress(self) -> None:
        self._moved = time.perf_counter()

    def _screen(self, name: str) -> None:
        if name != self._last_screen:
            self._last_screen = name
            self.note("screen", name)
            if name in OUT_OF_FIGHT:
                self._new_fight()
        if name != "event":
            self._event_clicks.clear()
        if name != "chest":
            self._chest_tries = 0
        if name != "victory":
            self._win = 0.0
        if name != "continue":
            self._continue_tries = 0
            self._loot_done = False
        if name != "light":
            self._castle_tries = 0
        if name != "end":
            self._retry_at = 0.0
            self._retry_tries = 0
        if name != "path":
            self._path_at = 0.0
            self._path_tries = 0
            self._path_cards = 0

    def _abs(self, rect, pt: dict) -> tuple[int, int]:
        return rect.x + int(round(pt["x"] * rect.w)), rect.y + int(round(pt["y"] * rect.h))

    def _click(self, rect, x: int, y: int) -> None:
        gui_click_at(rect.x + int(x), rect.y + int(y))
        self._progress()
        self.note("action", "")

    def _click_point(self, rect, key: str) -> None:
        gui_click_at(*self._abs(rect, point_of(self.cfg, key)))
        self._progress()
        self.note("action", "")

    def _press(self, hold: float) -> None:
        try:
            key_press(SPACE)
            time.sleep(max(0.0, hold))
        finally:
            key_release(SPACE)

    def _focus(self) -> None:
        if self.cfg.get("auto_focus_roblox"):
            focus_roblox()

    def _tap(self, action: bool = True, key: str = SPACE) -> None:
        self._focus()
        tap_key(key, self._num("key_hold_sec", 0.01), self.aborted)
        self._progress()
        if action:
            self.note("action", "")

    def _frame(self, rect) -> np.ndarray | None:
        frame = self.grabber.grab(rect.x, rect.y, rect.w, rect.h)
        if frame is None or frame.shape[0] != rect.h or frame.shape[1] != rect.w:
            return None
        return frame

    def loop(self) -> None:
        while not self.aborted():
            rect = client()
            if rect is None:
                self.status("Roblox not found, open it.")
                if self._sleep(1.0):
                    return
                continue
            frame = self._frame(rect)
            if frame is None:
                if self._sleep(0.2):
                    return
                continue
            battle = in_battle(frame)
            if battle:
                seen = time.perf_counter()
                if seen - self._fight_at > FIGHT_GAP_SEC:
                    self._new_fight()
                self._fight_at = seen
            state = self._minigame(rect, frame, battle)
            now = time.perf_counter()
            if battle or state != CLEAR:
                self._fight_at = now
            if state == PLAYED:
                continue
            busy = state == SEEN
            if battle:
                self._fight(rect, frame, now, busy)
            else:
                self._outside(rect, frame, now, busy)
            if self._sleep(self._num("poll_sec", 0.005)):
                return

    def _minigame(self, rect, frame: np.ndarray, battle: bool) -> str:
        sx0, sy0, sx1, sy1 = search_box(self.cfg, rect.w, rect.h)
        area = frame[sy0:sy1, sx0:sx1]
        dodge = find_bar(area, ui_ref(rect.w, rect.h))
        if dodge is not None and dodge.kind == BAR_DODGE and has_block(area, dodge):
            self._bar_at = 0.0
            self._seen = None
            return self._play_bar(rect, dodge, sx0, sy0, sx1)
        panel = find_panel(area, rect.w, rect.h)
        found = panel_game(panel, area, str(self.cfg.get("class") or "")) if panel is not None else None
        if found is None:
            self._bar_at = 0.0
            self._seen = None
            return CLEAR
        now = time.perf_counter()
        game, name, who = found
        if now < self._mg_block and game == self._mg_game:
            return CLEAR
        if game in (BAR, DODGE):
            self._seen = None
            bar, bx0, by0, bx1 = self._bar_in_box(rect, frame, panel, sx0, sy0)
            if bar is not None:
                self._bar_at = 0.0
                return self._play_bar(rect, bar, bx0, by0, bx1)
            if not self._bar_at:
                self._bar_at = now
            if now - self._bar_at > BAR_WAIT_SEC:
                return CLEAR
            self.status("%s box is up, waiting for the bar." % name)
            return SEEN
        self._bar_at = 0.0
        if not battle:
            self._seen = None
            return CLEAR
        key = (game, panel.left // 8, panel.top // 8, (panel.right - panel.left) // 8)
        if self._seen != key:
            self._seen = key
            return SEEN
        self._seen = None
        return self._play_panel(rect, panel, game, name, who)

    def _bar_in_box(self, rect, frame: np.ndarray, panel, sx0: int, sy0: int):
        bw = panel.right - panel.left
        x0 = sx0 + panel.left
        x1 = sx0 + panel.right
        y0 = sy0 + panel.top + int(round(bw * 0.09))
        y1 = min(rect.h, sy0 + panel.top + int(round(bw * 0.45)))
        if y1 - y0 < 12 or x1 - x0 < 60:
            return None, 0, 0, 0
        bar = find_bar(frame[y0:y1, x0:x1], bw / 0.3938)
        if bar is None:
            return None, 0, 0, 0
        return bar, x0, y0, x1

    def _play_bar(self, rect, bar, x0: int, y0: int, x1: int) -> str:
        dodge = bar.kind == BAR_DODGE
        if dodge and not self.cfg["play_dodge"]:
            self.status("Dodge minigame is up, you play it (Play dodge minigame is off).")
            return SEEN
        if not dodge and not self.cfg["play_attack"]:
            self.status("Attack minigame is up, you play it (Play attack minigame is off).")
            return SEEN
        early = bool(self.cfg.get("early_mode")) and not dodge
        self._focus()
        self._screen("minigame")
        if dodge:
            self.status("Dodging...")
        else:
            self.status("Attacking (Blade Focus, Early Mode)..." if early else "Attacking (Blade Focus)...")
        sx, sy = rect.x + x0, rect.y + y0 + bar.above
        sh = bar.mid - bar.above + 1
        sw = x1 - x0
        want = {ATTACK: bool(self.cfg["play_attack"]), BAR_DODGE: bool(self.cfg["play_dodge"])}

        def grab():
            strip = self.grabber.grab(sx, sy, sw, sh)
            return strip, time.perf_counter()

        result = self.player.play(grab, bar, self._press, self.aborted, want, early)
        self.note(result["kind"], str(result["presses"]))
        self._after_play(self.player.timed_out, DODGE if dodge else BAR)
        return PLAYED

    def _play_panel(self, rect, panel, game: str, name: str, who: str) -> str:
        if not self.cfg["play_attack"]:
            self.status("%s is up, you play it (Play attack minigame is off)." % name)
            return SEEN
        x0, y0, x1, y1 = search_box(self.cfg, rect.w, rect.h)
        early = bool(self.cfg.get("early_mode"))
        scale = panel.scale
        self.panels.configure(self.adv)
        play = None if early else self.panels.make(game, scale, who)
        self._focus()
        self._screen("minigame")
        self.status("Attacking (%s, Early Mode)..." % name if early else "Attacking (%s)..." % name)
        margin = max(8, int(round(20 * scale)))
        gx = rect.x + x0 + panel.left
        gy = rect.y + max(0, y0 + panel.top - margin)
        gw = panel.right - panel.left
        gh = min(rect.h - (gy - rect.y), int(round(363 * scale)))

        def grab():
            img = self.grabber.grab(gx, gy, gw, gh)
            return img, time.perf_counter()

        presses = self.panels.play(play, grab, scale, self._press, self.aborted, margin * 2 + 4)
        self.note("attack", str(presses))
        self._after_play(self.panels.timed_out, game)
        return PLAYED

    def _after_play(self, timed_out: bool, game: str) -> None:
        now = time.perf_counter()
        # A minigame means the turn is over (your attack, or the enemy's attack you dodged). The
        # turn border isn't watched while playing, so without this the next turn could be missed
        # and Turn 2 skills never came up.
        self._turn = False
        self._turn_off = now - TURN_GAP_SEC
        if timed_out and game == DODGE:
            self.status("That dodge never ended, back to Space.")
        elif timed_out:
            block = self._num("minigame_block_sec", 0.0)
            self._mg_block = now + block
            self._mg_game = game
            self.status("That minigame never ended, ignoring it for %.1f s." % block)
        self._next_space = now + self._num("battle_space_sec", 0.02)
        self._progress()

    def _fight(self, rect, frame: np.ndarray, now: float, busy: bool) -> None:
        self._screen("battle")
        if busy:
            self._menu_at = 0.0
            return
        turn = your_turn(frame)
        back = back_header(frame)
        if turn and not self._turn:
            if not self._turn_no or now - self._turn_off >= TURN_GAP_SEC:
                self._turn_no += 1
            self._en = None
            self._en_read = False
            self._en_tries = 0
            self._en_wait = 0.0
            self._guard_tries = 0
            self._scroll_turn = False
            self._hover = ""
            if self.cfg.get("combo_on") and self._combo_step < 2 and self._turn_no != self._combo_turn \
                    and not str(self.cfg.get("combo_%d" % (self._combo_step + 1)) or "").strip():
                # Empty Turn N box = a normal turn, the next box waits for the turn after.
                self._resolve_combo()
        elif self._turn and not turn:
            self._turn_off = now
        self._turn = turn
        if not (turn or back):
            self._menu_at = 0.0
            self._nudges = 0
        elif not self._menu_at:
            self._menu_at = now
        if self._mode == CAST:
            self._check_scroll(rect, frame, now, turn, back)
            return
        if self._mode in (OPEN, PICK) and not (turn or back):
            if now - self._turn_off >= TURN_GAP_SEC:
                self.status("The turn moved on before the skill went in, back to attacking.")
                self._back_to_attack(rect)
            return
        if self._mode == PICK:
            self._pick_skill(rect, now)
            return
        if self._mode == OPEN:
            self._open_skills(rect, frame, now, back)
            return
        if self._mode == CHECK:
            self._check_skill(rect, frame, now)
            return
        if not (back and skill_list_open(frame, area_of(self.cfg, "skills_area"))):
            self._back_tries = 0
        elif turn and self._use_open_list():
            return
        elif self._close_list(rect, now):
            return
        if turn and not back and self._guard(rect, frame, now):
            return
        if self._menu_at and now - self._menu_at > self._num("stuck_fix_sec", 1.0):
            self._unstick(rect, now, back)
            return
        if turn and not back and self._use_scroll(rect, frame, now):
            return
        if turn and not back and self._skill_due(frame, now):
            return
        if not (turn or back) and now - self._moved < self._num("enemy_space_sec", 0.5):
            self.status("Enemy's turn, waiting for the dodge.")
            return
        if now < self._next_space:
            return
        if turn and not back:
            self._hover = ""
        self._face(rect, "attack_btn")
        if turn and self._en:
            self.status("Your turn (EN %d/%d), ATTACK." % self._en)
        elif turn:
            self.status("Your turn, ATTACK.")
        else:
            self.status("In a fight, Space.")
        self._tap(False)
        self._next_space = time.perf_counter() + self._pace(turn)

    def _guard(self, rect, frame: np.ndarray, now: float) -> bool:
        if not self.cfg.get("guard_on", True):
            return False
        if not guard_alert(frame, point_of(self.cfg, "guard_btn")):
            if self._hover != "guard_btn":
                self._guarded = False
            return False
        if self._guard_tries >= 2 or (self._guarded and not self._guard_tries):
            return False
        if now < self._next_space:
            return True
        self._menu_at = now
        self._guard_tries += 1
        self._guarded = True
        if self._guard_tries == 2:
            self.status("GUARD ! is up and Space didn't take, clicking GUARD.")
            self._click_point(rect, "guard_btn")
            self._hover = "guard_btn"
        else:
            self.status("GUARD ! is up, guarding.")
            self._face(rect, "guard_btn")
            time.sleep(0.08)
            self._tap()
            self.note("guard", "")
        time.sleep(0.15)
        self._face(rect, "attack_btn")
        self._next_space = time.perf_counter() + max(1.0, self._pace())
        return True

    def _close_list(self, rect, now: float) -> bool:
        if self._back_tries >= BACK_TRIES:
            return False
        if now - self._back_at < max(BACK_GAP_SEC, self._num("skill_wait_sec", 0.05)):
            return True
        self._back_tries += 1
        self._back_at = now
        self._menu_at = now
        self.status("The skill list is up, clicking BACK and going back to attacking.")
        self._click_point(rect, "back_btn")
        self._hover = ""
        # Let the menu settle first: Space right after BACK went in as an attack before a Turn skill could.
        self._next_space = time.perf_counter() + max(BACK_GAP_SEC, self._pace())
        return True

    def _use_scroll(self, rect, frame: np.ndarray, now: float) -> bool:
        if not self.cfg.get("scroll_on") or self._scroll_turn:
            return False
        if self._combo_pending():
            return False
        if not row_lit(frame, point_of(self.cfg, "scroll_btn")):
            return False
        if now < self._next_space:
            return True
        self._scroll_turn = True
        self._scroll_tries = 0
        self._press_scroll(rect)
        return True

    def _press_scroll(self, rect) -> None:
        self._scroll_tries += 1
        self._menu_at = time.perf_counter()
        self._hover = ""
        if self._scroll_tries == 1:
            self.status("SCROLL is lit up, using it.")
            self._face(rect, "scroll_btn")
            time.sleep(0.08)
            self._tap()
        else:
            self.status("SCROLL didn't go through, clicking it (%d/%d)." % (self._scroll_tries, SCROLL_TRIES))
            self._click_point(rect, "scroll_btn")
            self._hover = "scroll_btn"
        self._scroll_at = time.perf_counter()
        self._mode = CAST

    def _check_scroll(self, rect, frame: np.ndarray, now: float, turn: bool, back: bool) -> None:
        if now - self._scroll_at < BACK_GAP_SEC:
            return
        failed = False
        if back and skill_list_open(frame, area_of(self.cfg, "skills_area")):
            self.status("That opened the skill list instead of SCROLL, clicking BACK.")
            self._click_point(rect, "back_btn")
            self._back_at = time.perf_counter()
            self._back_tries = 1
            if self._scroll_tries < SCROLL_TRIES:
                self._scroll_at = time.perf_counter()
                return
            failed = True
        elif turn and not back and row_lit(frame, point_of(self.cfg, "scroll_btn")):
            if self._scroll_tries < SCROLL_TRIES:
                self._press_scroll(rect)
                return
            failed = True
        if failed:
            self.status("SCROLL didn't go through, attacking until SCROLL is lit up again.")
            self._en_read = True
        else:
            self.status("Used SCROLL, back to attacking.")
            self.note("scroll", "")
        self._mode = HIT
        self._hover = ""
        self._face(rect, "attack_btn")
        self._next_space = time.perf_counter() + self._pace()

    def _pace(self, turn: bool = True) -> float:
        if turn and self._skill_set():
            return self._num("skill_space_sec", 0.05)
        return self._num("battle_space_sec", 0.02)

    def _face(self, rect, key: str) -> bool:
        if self._hover == key:
            return False
        self._hover = key
        row = DEFAULT_POINTS["attack_btn"]
        pt = point_of(self.cfg, key)
        if key == "attack_btn" and (abs(pt["x"] - row["x"]) > 0.08 or abs(pt["y"] - row["y"]) > 0.02):
            # A custom ATTACK spot off the menu doesn't move the game's cursor, so after GUARD /
            # SCROLL / SKILLS it stayed there and every Space pressed GUARD. Touch the real row first.
            hover_at(*self._abs(rect, row))
            time.sleep(0.05)
        if key in JITTER_KEYS:
            jitter_at(*self._abs(rect, point_of(self.cfg, key)))
        else:
            hover_at(*self._abs(rect, point_of(self.cfg, key)))
        return True

    def _new_fight(self) -> None:
        self._turn_no = 0
        self._turn = False
        self._combo_step = 0
        self._combo_turn = -1
        self._combo_tries = 0

    def _resolve_combo(self) -> None:
        # Turn 2 is "the turn after Turn 1's skill was settled" (used, greyed out or not in the list),
        # not a raw turn count: the turn border flickering during an ULTRA used to eat turn 2.
        self._combo_step += 1
        self._combo_turn = self._turn_no
        self._combo_tries = 0

    def _skill_set(self) -> bool:
        name = str(self.cfg.get("skill_name") or "").strip()
        return bool(self.cfg.get("skill_on")) and bool(name) and not self._skill_off

    def _skill_name(self) -> str:
        if not self._skill_set() or time.perf_counter() < self._skill_block:
            return ""
        return str(self.cfg.get("skill_name") or "").strip()

    def _plan(self) -> tuple[str, bool]:
        if self.cfg.get("combo_on") and self._turn_no >= 1 and self._combo_step < 2 and self._turn_no != self._combo_turn:
            name = str(self.cfg.get("combo_%d" % (self._combo_step + 1)) or "").strip()
            if name:
                return name, True
        return self._skill_name(), False

    def _combo_pending(self) -> bool:
        return not self._en_read and self._plan()[1]

    def _skill_due(self, frame: np.ndarray, now: float) -> bool:
        if self._en_read:
            return False
        name, combo = self._plan()
        if not name:
            return False
        if combo:
            self._combo_tries += 1
            if self._combo_tries > COMBO_TRIES:
                self.status("Turn %d skill %s didn't go in %d turns running, skipping it." % (self._combo_step + 1, name, COMBO_TRIES))
                self._resolve_combo()
                self._en_read = True
                return False
            self.status("Turn %d skill, going for %s." % (self._combo_step + 1, name))
            return self._go_skill(name, True)
        if now < self._en_wait:
            return True
        self._en = read_en(self.reader, frame, self.cfg)
        if self._en is None:
            self._en_tries += 1
            if self._en_tries < EN_TRIES:
                self._en_wait = now + 0.15
                self.status("Your turn, reading your EN...")
                return True
            self._en_read = True
            self.status("Your turn, couldn't read your EN, attacking (Test the EN area).")
            return False
        self._en_read = True
        if self._en[0] < int(self.cfg.get("skill_en") or 0):
            return False
        return self._go_skill(name, False)

    def _use_open_list(self) -> bool:
        # The skill list is already open on our turn (a stray Space hit SKILLS). If a Turn skill is
        # due, pick it from here instead of clicking BACK and losing the turn to a plain attack.
        if self._en_read:
            return False
        name, combo = self._plan()
        if not (name and combo):
            return False
        self._combo_tries += 1
        self.status("The skill list is already open, picking Turn %d skill %s." % (self._combo_step + 1, name))
        self._go_skill(name, True)
        self._mode = PICK
        self._skill_at = time.perf_counter()
        self._scrolls = 0
        self._scroll_dir = 1
        self._list_text = ""
        self._reread = False
        return True

    def _go_skill(self, name: str, combo: bool) -> bool:
        self._want = name
        self._want_combo = combo
        self._en_read = True
        self._mode = OPEN
        self._skill_at = 0.0
        self._skill_tries = 0
        return True

    def _open_skills(self, rect, frame: np.ndarray, now: float, back: bool) -> None:
        if self._skill_at and now - self._skill_at < self._num("skill_wait_sec", 0.05):
            return
        if back:
            if skill_list_open(frame, area_of(self.cfg, "skills_area")):
                self._mode = PICK
                return
            self.status("Space went to ATTACK instead of SKILLS, letting the attack go through.")
            self._back_to_attack(rect)
            return
        if self._skill_tries >= 3:
            self._drop_skill(rect, "SKILLS wouldn't open, back to attacking.", False)
            return
        self._skill_tries += 1
        if self._en:
            self.status("EN %d/%d, opening SKILLS for %s." % (self._en[0], self._en[1], self._want))
        else:
            self.status("Opening SKILLS for %s." % self._want)
        self._hover = ""
        self._face(rect, "skills_btn")
        self._tap()
        self._skill_at = time.perf_counter()
        self._scrolls = 0
        self._scroll_dir = 1
        self._list_text = ""
        self._reread = False
        self._mode = PICK

    def _pick_skill(self, rect, now: float) -> None:
        wait = self._num("skill_wait_sec", 0.05)
        if now - self._skill_at < wait:
            return
        name = self._want
        frame = self._frame(rect)
        if frame is None:
            if now - self._skill_at > wait * 4:
                self._drop_skill(rect, "Lost the screen while the skill list was open.", False)
            return
        area = area_of(self.cfg, "skills_area")
        back = back_header(frame)
        if not (back and skill_list_open(frame, area)):
            if back:
                self.status("Space went to ATTACK instead of SKILLS, letting the attack go through.")
                self._back_to_attack(rect)
                return
            self._mode = OPEN
            return
        img, ax, ay = crop(frame, area)
        lines = self.reader.read(img)
        line = skill_line(lines, name, int(self.cfg.get("skill_letters") or 0), self._want_combo)
        if line is None:
            # The list can still be sliding in on the first read, give it one more look before scrolling.
            if not self._reread and not self._scrolls:
                self._reread = True
                self.status("%s not read yet, looking at the skill list again." % name)
                self._skill_at = time.perf_counter()
                return
            if self._scroll_list(rect, area, lines, name):
                return
            save_debug("missing " + name, img, lines)
            self._missed(rect, name)
            return
        if not text_lit(img, line):
            save_debug("greyed " + name, img, lines)
            if self._want_combo:
                self._resolve_combo()
                if self._next_combo_now(name):
                    return
            self._drop_skill(rect, "%s is greyed out (short on EN or locked), BACK and attack." % name, True)
            return
        if not self._want_combo:
            self._misses = 0
        self.status("Using %s." % name)
        jitter_at(rect.x + ax + line.x + min(line.w // 3, 60), rect.y + ay + line.cy)
        time.sleep(0.05)
        self._tap()
        self._skill_at = time.perf_counter()
        self._skill_block = self._skill_at + self._num("skill_retry_sec", 0.0)
        self._mode = CHECK

    def _next_combo_now(self, skipped: str) -> bool:
        # Turn skill greyed out / on cooldown / missing: go for the next Turn skill in the same
        # open list (e.g. Legion Gate on CD after a boss phase change, Dragon Gate is ready).
        if self._combo_step >= 2:
            return False
        name = str(self.cfg.get("combo_%d" % (self._combo_step + 1)) or "").strip()
        if not name or norm(name) == norm(skipped):
            return False
        self.status("%s can't be used, going for %s instead." % (skipped, name))
        self._want = name
        self._combo_turn = -1
        self._combo_tries = 1
        self._scrolls = 0
        self._scroll_dir = 1
        self._list_text = ""
        self._reread = True
        self._skill_at = time.perf_counter()
        return True

    def _missed(self, rect, name: str) -> None:
        if self._want_combo:
            self._resolve_combo()
            if self._next_combo_now(name):
                return
            self._drop_skill(rect, "%s isn't in the skill list, BACK and attack this turn." % name, True)
            return
        self._misses += 1
        if self._misses >= SKILL_MISSES:
            self._skill_off = True
            msg = "%s wasn't in the skill list %d times in a row, skills are off until you press F1 again." % (name, self._misses)
        else:
            msg = "%s isn't in the skill list (%d/%d), BACK and attack." % (name, self._misses, SKILL_MISSES)
        self._drop_skill(rect, msg, True)

    def _scroll_list(self, rect, area: dict, lines: list[Line], name: str) -> bool:
        if not self.cfg.get("skill_scroll"):
            return False
        most = int(self.cfg.get("skill_scrolls") or 0)
        text = norm(" ".join(ln.text for ln in lines))
        if self._scrolls and text == self._list_text:
            if self._scroll_dir < 0:
                return False
            self._scroll_dir = -1
        if self._scrolls >= most:
            return False
        self._list_text = text
        self._scrolls += 1
        x0, y0, x1, y1 = area_px(area, rect.w, rect.h)
        self.status("%s isn't showing yet, scrolling the skill list %s (%d/%d)." % (name, "down" if self._scroll_dir > 0 else "up", self._scrolls, most))
        self._focus()
        cx, cy = rect.x + (x0 + x1) // 2, rect.y + (y0 + y1) // 2
        # Roblox only scrolls the list the mouse is already over, so settle there before the wheel.
        hover_at(cx, cy)
        time.sleep(0.08)
        wheel_at(cx, cy, -self._scroll_dir)
        self._progress()
        self._skill_at = time.perf_counter()
        return True

    def _check_skill(self, rect, frame: np.ndarray, now: float) -> None:
        if now - self._skill_at < max(BACK_GAP_SEC, self._num("skill_wait_sec", 0.05)):
            return
        name = self._want
        if self._want_combo:
            self._resolve_combo()
        if back_header(frame) and skill_list_open(frame, area_of(self.cfg, "skills_area")):
            self.status("%s didn't go through (short on EN or it's locked), clicking BACK." % name)
            self._click_point(rect, "back_btn")
            self._back_at = time.perf_counter()
            self._back_tries = 1
        else:
            self.status("Used %s, back to attacking." % name)
            self.note("skill", name)
        self._back_to_attack(rect)

    def _drop_skill(self, rect, msg: str, back: bool) -> None:
        if msg:
            self.status(msg)
        if back:
            self._click_point(rect, "back_btn")
            self._back_at = time.perf_counter()
            self._back_tries = 1
        self._skill_block = time.perf_counter() + self._num("skill_retry_sec", 0.0)
        self._back_to_attack(rect)

    def _back_to_attack(self, rect) -> None:
        self._mode = HIT
        self._scrolls = 0
        self._scroll_dir = 1
        self._list_text = ""
        self._skill_at = 0.0
        self._skill_tries = 0
        self._en = None
        self._en_read = True
        self._menu_at = 0.0
        self._nudges = 0
        self._hover = ""
        self._face(rect, "attack_btn")
        self._next_space = time.perf_counter() + self._pace()

    def _unstick(self, rect, now: float, back: bool) -> None:
        self._menu_at = now
        self._nudges += 1
        self._hover = ""
        if self._nudges == 1:
            self.status("The menu hasn't moved, putting the mouse back on ATTACK.")
            self._face(rect, "attack_btn")
            self._tap()
            return
        if self._nudges == 2:
            self.status("The menu still hasn't moved, clicking ATTACK.")
            self._click_point(rect, "attack_btn")
            self._hover = "attack_btn"
            return
        self.status("The menu is stuck, clicking BACK.")
        self._click_point(rect, "back_btn")
        self._nudges = 0
        self._next_space = time.perf_counter() + self._pace()

    def _outside(self, rect, frame: np.ndarray, now: float, busy: bool) -> None:
        self._hover = ""
        self._mode = HIT
        self._menu_at = 0.0
        self._en_read = False
        self._guarded = False
        self._scroll_turn = False
        self._back_tries = 0
        handled = self._menus(rect, frame, now)
        if (not handled or self._last_screen == "end") and not busy and self._replay(rect, now):
            return
        if handled or busy:
            return
        gap = self._num("wait_space_sec", 0.1)
        if now - self._moved < gap:
            return
        self.status("Nothing to click, Space.")
        self._tap(False)

    def _menus(self, rect, frame: np.ndarray, now: float) -> bool:
        x0, y0, x1, y1 = menu_box(self.cfg, rect.w, rect.h)
        img = frame[y0:y1, x0:x1]
        btn = find_button(img, rect.w, rect.h)
        if btn is not None and self._button(rect, frame, img, x0, y0, btn):
            return True
        dim = find_dim_button(img, rect.w, rect.h) if btn is None else None
        if dim is not None:
            label = self._read_button(img, dim.box)
            if button_kind(label) == "light":
                self._screen("light")
                self._castle(rect, img, x0, y0, dim.box, label)
                return True
        if path_banner(frame):
            self._screen("path")
            self._path(rect)
            return True
        if now >= self._next_chest:
            self._next_chest = now + self._num("chest_check_sec", 0.3)
            if self._chest(rect, frame):
                return True
        if now >= self._next_skip:
            self._next_skip = now + self._num("chest_check_sec", 0.3)
            if self._skip(rect, frame):
                return True
        if self._victory(rect, frame, now):
            return True
        if self._last_screen in ("battle", "minigame"):
            self.status("Fight over, waiting for the next screen...")
        else:
            self.status("Waiting...")
        return False

    def _victory(self, rect, frame: np.ndarray, now: float) -> bool:
        if victory_banner(frame):
            if not self._win:
                self._win = now
            self._screen("victory")
        elif not self._win or now - self._win > self._num("victory_max_sec", 1.0):
            return False
        if now - self._moved >= self._num("victory_gap_sec", 0.1):
            self.status("VICTORY, Space until Choose Your Path.")
            self._tap()
        return True

    def _replay(self, rect, now: float) -> bool:
        if not self.cfg.get("replay_check"):
            return False
        every = max(3.0, float(self.cfg.get("replay_sec") or 10.0))
        if now - self._fight_at < every or now - self._replay_at < every:
            return False
        self._replay_at = now
        x, y = self._abs(rect, point_of(self.cfg, "replay_btn"))
        self.status("No fight for %.0f s, clicking the replay spot." % every)
        self._focus()
        self._hover = ""
        hover_at(x, y)
        time.sleep(0.15)
        gui_click_at(x, y)
        self._progress()
        self.note("action", "")
        return True

    def _read_button(self, img: np.ndarray, box: Box) -> str:
        now = time.perf_counter()
        text, bx, by, at = self._label
        if text and abs(bx - box.x) <= 4 and abs(by - box.y) <= 4 and now - at < self._num("label_read_sec", 0.0):
            return text
        text = read_label(self.reader, img, box)
        self._label = (text, box.x, box.y, now)
        return text

    def _button(self, rect, frame: np.ndarray, img: np.ndarray, x0: int, y0: int, btn) -> bool:
        b = btn.box
        label = self._read_button(img, b)
        kind = button_kind(label)
        cx, cy = x0 + b.cx, y0 + b.cy
        if kind in ("buy", "ignore"):
            return False
        if kind == "light":
            self._screen("light")
            self._castle(rect, img, x0, y0, b, label)
            return True
        if kind == "retry":
            self._screen("end")
            now = time.perf_counter()
            if not btn.active:
                self._retry_at = 0.0
                self.status("Run finished, waiting for PLAY AGAIN to light up.")
                self._sleep(0.3)
                return True
            if not self._retry_at:
                self._retry_at = now
            if now - self._retry_at < 0.6:
                self.status("Run finished, letting PLAY AGAIN finish fading in.")
                return True
            self._retry_tries += 1
            if self._retry_tries == 1:
                self.note("run", "")
            x, y = rect.x + cx, rect.y + cy
            self._hover = ""
            hover_at(x, y)
            time.sleep(0.15)
            if self._retry_tries % 3 == 0:
                self.status("PLAY AGAIN didn't take the click, trying Space.")
                self._tap()
            else:
                self.status("Run finished, clicking PLAY AGAIN.")
                gui_click_at(x, y)
                self._progress()
                self.note("action", "")
            self._sleep(1.0)
            return True
        if kind == "continue" and btn.active:
            self._screen("continue")
            if not self._loot_done:
                self._loot_done = True
                if self._loot(rect, y0 + b.y):
                    return True
            # Click first: Space never took on CONTINUE, so it always waited ~3 s for the click.
            self._continue_tries += 1
            if self._continue_tries % 3:
                self.status("CONTINUE, clicking it.")
                self._focus()
                self._hover = ""
                hover_at(rect.x + cx, rect.y + cy)
                time.sleep(0.08)
                self._click(rect, cx, cy)
            else:
                self.status("CONTINUE didn't take the click, trying Space.")
                self._tap()
            self._sleep(min(CONTINUE_GAP_SEC, self._num("after_pick_sec", 0.0)))
            return True
        if kind == "battle" and btn.active:
            self._screen("event")
            self.status("%s" % (label.strip() or "TO BATTLE!"))
            self._click(rect, cx, cy)
            self.note("event", "")
            self._sleep(self._num("after_pick_sec", 0.0))
            return True
        if not btn.active and kind in ("battle", None):
            ev, ex, ey = crop(frame, area_of(self.cfg, "event_area"))
            opts = find_options(ev, rect.h)
            if not opts:
                return False
            self._screen("event")
            self._event(rect, ev, ex, ey, opts)
            return True
        if btn.active and kind is None:
            self._screen("continue")
            self.status("Gold button (%s), Space." % (label.strip() or "can't read it"))
            self._tap()
            self._sleep(self._num("after_pick_sec", 0.0))
            return True
        return False

    def _castle(self, rect, img: np.ndarray, x0: int, y0: int, gold: Box, label: str) -> None:
        # THE LIGHT IS FADING after act 5: the gold button is FOLLOW THE LIGHT (on into acts 6-10),
        # the dark one next to it is RETURN TO THE CASTLE. "Follow the Light" picks which.
        self._castle_tries += 1
        if self.cfg.get("follow_light"):
            if is_castle(label):
                # The lit-up one is the castle button, so FOLLOW THE LIGHT is the one to its left.
                x, y = x0 + gold.cx - int(round(gold.w * 1.085)), y0 + gold.cy
            else:
                x, y = x0 + gold.cx, y0 + gold.cy
            self.status("The Light is fading, clicking FOLLOW THE LIGHT (on to act 6).")
        elif is_castle(label):
            x, y = x0 + gold.cx, y0 + gold.cy
            how = "the lit-up button"
        else:
            line = next((ln for ln in self.reader.read(img) if is_castle(ln.text) and abs(ln.cy - gold.cy) <= gold.h), None)
            if line is not None and self._castle_tries % 3:
                x, y = x0 + line.cx, y0 + line.cy
                how = "its label"
            else:
                # Same size as the gold button, just to its right.
                x, y = x0 + gold.cx + int(round(gold.w * 1.085)), y0 + gold.cy
                how = "right of FOLLOW THE LIGHT"
        if self.cfg.get("follow_light"):
            pass
        elif self._castle_tries > CASTLE_TRIES:
            self.status("RETURN TO THE CASTLE still hasn't gone through after %d clicks, trying again." % CASTLE_TRIES)
            self._castle_tries = 1
        else:
            self.status("The Light is fading, clicking RETURN TO THE CASTLE (%s)." % how)
        self._focus()
        self._hover = ""
        hover_at(rect.x + x, rect.y + y)
        time.sleep(0.15)
        gui_click_at(rect.x + x, rect.y + y)
        self._progress()
        self.note("action", "")
        self._sleep(max(1.0, self._num("after_pick_sec", 0.0)))

    def _loot(self, rect, bottom: int) -> bool:
        # Spoils screen (BOSS DEFEATED / chests): if a watched rarity shows up, report it and hold
        # the screen a moment so the webhook screenshot still has the loot on it.
        if not (self.cfg.get("loot_alert") and self.cfg.get("webhook_url")):
            return False
        rarities = rarity_list(self.cfg.get("loot_rarities") or "")
        if not rarities:
            return False
        self.status("Loot screen, checking for %s drops..." % " / ".join(r.title() for r in rarities))
        # Plain sleep, not _sleep: stopping the macro the moment a Mythic shows up used to cancel
        # the check, so the drop was never sent.
        time.sleep(LOOT_SETTLE_SEC)
        top = int(rect.h * 0.08)
        # The cards slide in after BOSS DEFEATED / YOUR SPOILS: reading too early saw only the title
        # and could miss a drop, so wait until some rarity tag (any rarity) is on screen.
        # Popups like "THE WITHERED MEADOW CLEARED!" have no loot at all: don't wait on those.
        end = time.perf_counter() + LOOT_WAIT_SEC
        while True:
            frame = self._frame(rect)
            if frame is None:
                return False
            img = frame[top:max(top + 1, bottom), int(rect.w * 0.25):int(rect.w * 0.75)]
            words = {w for ln in self.reader.read(img) for w in norm(ln.text).split()}
            if words & ANY_RARITY or find_tags(img, rect.h):
                break
            if words and not words & LOOT_TITLES:
                self.status("Loot screen, nothing to check here.")
                return False
            if time.perf_counter() >= end:
                break
            time.sleep(0.4)
        return self._scan_loot(rect, img, rarities, "Loot screen")

    def _scan_loot(self, rect, img: np.ndarray, rarities: list[str], where: str) -> bool:
        start = time.perf_counter()
        lines = self.reader.read(img)
        tags = [(r, b, self.reader.text(tag_crop(img, b))) for r, b in find_tags(img, rect.h)]
        if tags:
            lines = with_tags(lines, tags)
        took = time.perf_counter() - start
        found = find_loot(lines, rarities, rect.h)
        save_debug("loot " + (", ".join(r for r, _ in found) or "none"), img, lines)
        now = time.perf_counter()
        self._loot_sent = {k: t for k, t in self._loot_sent.items() if now - t < LOOT_DEDUP_SEC}
        # Same drop read twice (chest reveal, then spoils) can come back as "WHETSTONE" / "WI-ETSTONE".
        def seen(r: str, item: str) -> bool:
            n = norm(item)
            return any(sr == r and difflib.SequenceMatcher(None, n, sn).ratio() >= 0.7 for sr, sn in self._loot_sent)

        fresh = [(r, item) for r, item in found if not seen(r, item)]
        if not fresh:
            self.status("%s, no new %s (read in %.1f s)." % (where, " / ".join(r.title() for r in rarities), took))
            return False
        for r, item in fresh:
            self._loot_sent[(r, norm(item))] = now
        what = ", ".join("%s: %s" % (r.title(), item) for r, item in fresh)
        self.status("%s drop! Sending a screenshot to the webhook (read in %.1f s)." % (what, took))
        self.note("loot", what)
        self._sleep(LOOT_HOLD_SEC)
        return True

    def _chest_loot(self, rect) -> None:
        # Chests reveal their item without a CONTINUE button, Space went straight past a Mythic.
        if not (self.cfg.get("loot_alert") and self.cfg.get("webhook_url")):
            return
        rarities = rarity_list(self.cfg.get("loot_rarities") or "")
        frame = self._frame(rect) if rarities else None
        if frame is None:
            return
        img, _x, _y = crop(frame, CHEST_LOOT_BAND)
        self._scan_loot(rect, img, rarities, "Chest")

    def _skip(self, rect, frame: np.ndarray) -> bool:
        img, sx0, sy0 = crop(frame, SKIP_BAND)
        line = next((ln for ln in self.reader.read(img) if is_skip(ln.text)), None)
        if line is None:
            return False
        self._screen("skip")
        self.status("Cutscene, clicking SKIP.")
        x, y = rect.x + sx0 + line.cx, rect.y + sy0 + line.cy
        self._focus()
        self._hover = ""
        hover_at(x, y)
        time.sleep(0.15)
        gui_click_at(x, y)
        self._progress()
        self.note("action", "")
        self._sleep(1.0)
        return True

    def _event(self, rect, img: np.ndarray, ex: int, ey: int, opts: list[Box]) -> None:
        lines = self.reader.read(img)
        names = [_title(lines_in(lines, o)) for o in opts]
        prefer = list(self.cfg.get("event_prefer") or [])
        order = sorted(range(len(opts)), key=lambda i: (rank(names[i], prefer, [])[1], i))
        pick = None
        for i in order:
            if self._event_clicks.get(i, 0) < 2:
                pick = i
                break
        if pick is None:
            self._event_clicks.clear()
            pick = order[0]
        self._event_clicks[pick] = self._event_clicks.get(pick, 0) + 1
        opt = opts[pick]
        self.status("Event: picking %s." % (names[pick] or "choice %d" % (pick + 1)))
        self._click(rect, ex + opt.x + max(20, opt.w // 4), ey + opt.cy)
        self._sleep(self._num("option_wait_sec", 0.0))

    def _chest(self, rect, frame: np.ndarray) -> bool:
        img, cx0, cy0 = crop(frame, CHEST_BAND)
        label = next((ln for ln in self.reader.read(img) if is_chest(ln.text)), None)
        if label is None:
            return False
        if self._last_screen != "chest":
            self.note("chest", "")
        self._screen("chest")
        self._chest_tries += 1
        if self._chest_tries <= 2:
            self.status("Chest, opening it with Space.")
            self._tap()
        else:
            self.status("The chest didn't open with Space, clicking it.")
            self._click(rect, cx0 + label.cx, cy0 + label.y + label.h + int(round(rect.h * 0.07)))
            self._chest_tries = 0
        self._sleep(1.0)
        self._chest_loot(rect)
        return True

    def _path(self, rect) -> None:
        now = time.perf_counter()
        if self._path_at and now - self._path_at < self._num("path_retry_sec", 0.5):
            self.status("Choose Your Path, waiting for the pick to go through...")
            return
        self.status("Choose Your Path, reading the paths...")
        if self._sleep(self._num("path_settle_sec", 0.0)):
            return
        frame = self._frame(rect)
        if frame is None or not path_banner(frame):
            return
        img, px, py = crop(frame, area_of(self.cfg, "path_area"))
        cards = find_cards(img, rect.h)
        self._path_tries += 1
        tries = self._path_tries
        if tries > 1 and self._path_cards and not cards:
            pt = PATH_CONFIRM[(tries - 2) % len(PATH_CONFIRM)]
            self.status("Something is covering the path cards, clicking where its confirm button would be.")
            self._click_point_at(rect, pt)
            if tries % 2 == 0:
                self._tap(False)
            self._path_at = time.perf_counter()
            return
        if not cards:
            spot = (1, 0, 2)[(tries - 1) % 3]
            self.status("Couldn't find the path cards, clicking where they usually are.")
            self._click_point_at(rect, USUAL_CARDS[spot])
            if tries == 1:
                self.note("path", "path %d" % (spot + 1))
            self._path_at = time.perf_counter()
            self._sleep(self._num("after_pick_sec", 0.0))
            return
        self._path_cards = max(self._path_cards, len(cards))
        lines = self.reader.read(img)
        pick = choose(cards, lines, self.cfg)
        self._path_pick = pick
        card = cards[pick]
        title = _title(lines_in(lines, card)) or "path %d" % (pick + 1)
        if tries > 1 and tries % 2 == 0 and len(cards) == len(USUAL_CARDS):
            self.status("%s didn't go through, clicking where that card usually is." % title)
            self._click_point_at(rect, USUAL_CARDS[pick])
        else:
            self.status("Picked %s." % title)
            self._click(rect, px + card.cx, py + card.cy)
        if tries == 1:
            self.note("path", title)
        self._path_at = time.perf_counter()
        self._sleep(self._num("after_pick_sec", 0.0))

    def _click_point_at(self, rect, pt: dict) -> None:
        gui_click_at(*self._abs(rect, pt))
        self._progress()
        self.note("action", "")
