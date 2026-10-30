from __future__ import annotations

import difflib
import time
from typing import Callable

import cv2
import numpy as np

from mouse_control import gui_click_at, hover_at
from ocr import Line, Reader
from screens import join_rows, matches, norm

DIFFICULTIES = ("NORMAL", "HARD", "NIGHTMARE", "TORMENT")
# TORMENT I, II, ... picked with the < > under the NORMAL button.
TORMENTS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
# In carousel order (the dots under the name).
MODIFIERS = ("NO MODIFIER", "ELITE PATROLS", "VOLATILE ENEMIES", "EXHAUSTING BATTLES", "BOSS RUSH")
LANDS = (
    "SUNMEADOW WILDS", "THE DUNGEON", "THE CURSED FOREST", "MOONSTONE RISE", "THE UNDERWORLD",
    "THE WITHERED MEADOW", "THE DROWNED CATHEDRAL", "THE GLASS WASTES", "THE HOLLOW SKY", "THE HEART OF BLIGHT",
)

PORTAL = "portal"
SET_OUT = "setout"
MULTIPLAYER = "multiplayer"
LOBBY = "lobby"
CASTLE = "castle"

# YOUR CASTLE hub: the gold SET OUT > button, bottom right. "Start spot" in the Lobby tab moves it.
START_SPOT = {"x": 0.922, "y": 0.962}
CASTLE_TRIES = 4

# Waits start once the click is done (see step()), so they only cover the game catching up.
IDLE_RECHECK_SEC = 0.8
STEP_SETTLE_SEC = 1.0
SET_SETTLE_SEC = 0.6
CHECK_AGAIN_SEC = 0.3
START_SETTLE_SEC = 3.0
FRIENDS_SETTLE_SEC = 1.1
FRIENDS_TRIES = 2
DIFF_TRIES = 3
CLEAN_CHECKS = 2
NAME_FLOOR = 0.55
# Arrows sit this far from the middle of the name, as a share of the label-to-middle distance.
ARROW_NEAR = 0.35
ARROW_FAR = 0.8


def find_line(lines: list[Line], keyword: str) -> Line | None:
    # Shortest matching line: the button itself, not a sentence that happens to mention it.
    best = None
    for ln in lines:
        if matches(keyword, ln.text) and (best is None or len(norm(ln.text)) < len(norm(best.text))):
            best = ln
    return best


def classify(lines: list[Line]) -> str | None:
    def has(kw: str) -> bool:
        return find_line(lines, kw) is not None

    # Most specific first. Set Out's Multiplayer card says "Host a lobby for friends", and
    # FIND A PARTY reads as "F A PAR W >", so it's told apart by its title and PLAY SOLO.
    # The lobby is a popup over the castle: two of its own labels are enough even when the dark
    # START RUN text isn't read, or it was taken for the castle and SET OUT got clicked under it.
    own = sum(has(kw) for kw in ("MODIFIER", "FRIENDS ONLY", "LEAVE LOBBY"))
    if own >= 2 or (own and has("START RUN")):
        return LOBBY
    if has("HOW DO YOU WANT TO TRAVEL") or has("PLAY SOLO") or has("FIND A PARTY"):
        return SET_OUT
    if has("HOST A LOBBY") and (has("OPEN LOBBIES") or has("QUEUE") or has("JOIN")):
        return MULTIPLAYER
    # On a narrow window STEP THROUGH reads as two lines ("STEP", "THROUGH").
    if has("STEP THROUGH") or has("ANCIENT PORTAL"):
        return PORTAL
    # "YOUR CASTLE" reads as "YOUR CASIIE": go by the hint line, or the building signs together.
    if has("BUILDING TO VISIT") or (has("AUCTION HOUSE") and has("GUILD HALL") and has("SET OUT")):
        return CASTLE
    return None


def start_spot(cfg: dict) -> tuple[dict, bool]:
    pt = (cfg.get("points") or {}).get("start_btn")
    return (pt, True) if pt else (START_SPOT, False)


def _squash(text: str) -> str:
    return norm(text).replace(" ", "")


def name_index(text: str, names: tuple[str, ...]) -> int | None:
    # OCR reads THE as "TYE-" or "II-IE-", so whole names are compared letter by letter.
    t = _squash(text)
    if not t:
        return None
    scores = [difflib.SequenceMatcher(None, t, _squash(n)).ratio() for n in names]
    best = max(range(len(names)), key=lambda i: scores[i])
    return best if scores[best] >= NAME_FLOOR else None


def _exact(lines: list[Line], word: str) -> Line | None:
    # Leftmost line that is just this word: "NO MODIFIER" reads as "NO" + "MODIFIER".
    hits = [ln for ln in lines if norm(ln.text) == word]
    return min(hits, key=lambda ln: ln.x) if hits else None


def modifier_value(lines: list[Line]) -> tuple[Line | None, Line | None]:
    # MODIFIER  <  [ NO MODIFIER ]  >  The usual adventure.
    label = _exact(lines, "MODIFIER")
    if label is None:
        return None, None
    row = [ln for ln in lines if ln is not label and abs(ln.cy - label.cy) <= max(6, label.h * 0.8) and ln.x > label.x + label.w]
    pieces = sorted(join_rows(row), key=lambda ln: ln.x)
    return label, (pieces[0] if pieces else None)


def land_value(lines: list[Line]) -> tuple[Line | None, Line | None]:
    # <  [ START AT / THE HEART OF BLIGHT ]  >   between LEAVE LOBBY and START RUN.
    label = find_line(lines, "START AT")
    if label is None:
        return None, None
    below = [ln for ln in lines if ln.y > label.y + label.h // 2 and ln.y <= label.y + label.h * 4]
    for ln in join_rows(below):
        if ln.x <= label.cx <= ln.x + ln.w:
            return label, ln
    return label, None


def difficulty_line(lines: list[Line], want: str) -> Line | None:
    label = find_line(lines, "DIFFICULTY")
    row = lines
    if label is not None:
        row = sorted((ln for ln in lines if abs(ln.cy - label.cy) <= max(5, label.h * 0.8) and ln.x > label.x + label.w), key=lambda ln: ln.x)
    for ln in row:
        if name_index(ln.text, DIFFICULTIES) == DIFFICULTIES.index(want):
            return ln
    # Names too garbled to tell apart: the four buttons are still in order.
    if label is not None and len(row) >= len(DIFFICULTIES):
        return row[DIFFICULTIES.index(want)]
    return None


def torment_value(lines: list[Line]) -> tuple[Line | None, Line | None]:
    # The TORMENT button reads "TORMENT V": hand back just the numeral (OCR's 1 / l / | are I).
    label = difficulty_line(lines, "TORMENT")
    if label is None:
        return None, None
    words = norm(label.text).split()
    tail = words[-1] if len(words) > 1 else _squash(label.text)[7:]
    tail = "".join("I" if c in "1L|!" else c for c in tail)
    if not tail or any(c not in "IVX" for c in tail):
        return label, None
    return label, Line(tail, label.x, label.y, label.w, label.h)


def read_torment(reader: Reader, frame: np.ndarray, lines: list[Line]) -> list[Line]:
    # Full-window OCR drops the small numeral ("TORMENT IV" reads "TORMENT"): read the button
    # again from a 3x crop and put that text on its line.
    label = difficulty_line(lines, "TORMENT")
    if label is None:
        return lines
    h, w = frame.shape[:2]
    x0, x1 = max(0, label.x - label.h * 3), min(w, label.x + label.w + label.h * 5)
    y0, y1 = max(0, label.y - label.h), min(h, label.y + label.h * 2)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return lines
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    text = " ".join(ln.text for ln in reader.read(big))
    if "TORM" not in norm(text):
        return lines
    return [Line(text, ln.x, ln.y, ln.w, ln.h) if ln is label else ln for ln in lines]


def torment_arrows(frame: np.ndarray, lines: list[Line]):
    # [ < ] [ > ]  foes x6.24  gold x5.33 ...  under the NORMAL button: the two glyphs left of "foes".
    normal = difficulty_line(lines, "NORMAL")
    foes = next((ln for ln in lines if norm(ln.text).startswith("FOES")), None)
    if normal is None or foes is None or foes.cy <= normal.cy:
        return None
    h, w = frame.shape[:2]
    y0, y1 = max(0, foes.cy - foes.h), min(h, foes.cy + foes.h + 1)
    x0 = max(0, int(normal.cx - normal.w * 2))
    x1 = max(x0, foes.x - 2)
    if y1 - y0 < 3 or x1 - x0 < 8:
        return None
    px = frame[y0:y1, x0:x1].astype(np.int16)
    hi, lo = px.max(axis=2), px.min(axis=2)
    # The arrow at the end of the range is dimmer (greyed out), so a lower bar than find_arrows.
    bright = (hi >= 120) & (hi - lo <= 45)
    cols = bright.sum(axis=0) >= 1
    d = np.diff(np.concatenate(([0], cols.astype(np.int8), [0])))
    spans = list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))
    if len(spans) < 2:
        return None
    out = []
    for s, e in spans[-2:]:
        ys = np.flatnonzero(bright[:, s:e].any(axis=1))
        out.append((x0 + (s + e - 1) // 2, y0 + int((ys[0] + ys[-1]) / 2)))
    return out[0], out[1]


def find_arrows(frame: np.ndarray, value: Line, y0: int, y1: int, anchor: float,
                skip: list[Line]) -> tuple[tuple[int, int], tuple[int, int]] | None:
    # The < and > glyphs are thin grey/white marks the same distance either side of the name.
    # Gold buttons, purple land names and green toggles are left out by colour, the name and
    # labels by their OCR boxes, and only a mirrored pair counts.
    h, w = frame.shape[:2]
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    if y1 - y0 < 3 or anchor < 8:
        return None
    px = frame[y0:y1].astype(np.int16)
    hi, lo = px.max(axis=2), px.min(axis=2)
    bright = (hi >= 150) & (hi - lo <= 45)
    cols = bright.sum(axis=0) >= 2
    for ln in skip:
        cols[max(0, ln.x - 2):min(w, ln.x + ln.w + 2)] = False
    centre = value.x + value.w / 2.0
    d = np.diff(np.concatenate(([0], cols.astype(np.int8), [0])))
    spans = list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] <= 3:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    found = []
    for s, e in merged:
        cx = (s + e - 1) / 2.0
        if ARROW_NEAR * anchor <= abs(cx - centre) <= ARROW_FAR * anchor:
            ys = np.flatnonzero(bright[:, s:e].any(axis=1))
            found.append((cx, y0 + (ys[0] + ys[-1]) / 2.0))
    best = None
    for lx, ly in (f for f in found if f[0] < centre):
        for rx, ry in (f for f in found if f[0] > centre):
            dl, dr = centre - lx, rx - centre
            gap = abs(dl - dr)
            if gap <= 0.12 * (dl + dr) / 2 and (best is None or gap < best[0]):
                best = (gap, (int(round(lx)), int(round(ly))), (int(round(rx)), int(round(ry))))
    return (best[1], best[2]) if best else None


def modifier_arrows(frame: np.ndarray, lines: list[Line]):
    label, value = modifier_value(lines)
    if label is None or value is None:
        return None
    half = max(label.h, value.h) * 1.6
    return find_arrows(frame, value, value.cy - half, value.cy + half, value.cx - label.cx, [label, value])


def land_arrows(frame: np.ndarray, lines: list[Line]):
    label, value = land_value(lines)
    if label is None or value is None:
        return None
    leave = find_line(lines, "LEAVE LOBBY")
    start = find_line(lines, "START RUN")
    if leave is not None:
        anchor = value.cx - leave.cx
    elif start is not None:
        anchor = start.cx - value.cx
    else:
        return None
    pad = label.h
    return find_arrows(frame, value, label.y - pad, value.y + value.h + pad, anchor, [label, value])


def friends_on(frame: np.ndarray, label: Line) -> bool:
    # Checkbox left of FRIENDS ONLY: the box and the whole pill go green when it's on.
    h, w = frame.shape[:2]
    x0 = max(0, label.x - int(round(label.h * 3)))
    x1 = min(w, label.x + label.w)
    y0 = max(0, label.cy - label.h)
    y1 = min(h, label.cy + label.h + 1)
    reg = frame[y0:y1, x0:x1]
    if reg.size == 0:
        return False
    px = reg.astype(np.int16)
    b, g, r = px[..., 0], px[..., 1], px[..., 2]
    green = (g >= 110) & (g - r >= 40) & (g - b >= 30)
    return float(green.mean()) >= 0.12


def _want(cfg: dict, key: str, names: tuple[str, ...]) -> int | None:
    name = str(cfg.get(key) or "").strip().upper()
    return names.index(name) if name in names else None


def difficulty_selected(frame: np.ndarray, lines: list[Line]) -> int | None:
    # The picked difficulty has a bright coloured box round its button, the others a dull one.
    # Only each button's own box is looked at, and its label is left out (the labels are coloured too).
    h, w = frame.shape[:2]
    counts = {}
    for i, d in enumerate(DIFFICULTIES):
        ln = difficulty_line(lines, d)
        if ln is None:
            continue
        px, py = 2 * ln.h, int(round(2.2 * ln.h))
        x0, y0 = max(0, ln.x - px), max(0, ln.y - py)
        reg = frame[y0:min(h, ln.y + ln.h + py), x0:min(w, ln.x + ln.w + px)].astype(np.int16)
        hi, lo = reg.max(axis=2), reg.min(axis=2)
        lit = (hi >= 150) & (hi - lo >= 80)
        lit[max(0, ln.y - y0 - 2):ln.y - y0 + ln.h + 2, max(0, ln.x - x0 - 2):ln.x - x0 + ln.w + 2] = False
        counts[i] = int(lit.sum())
    if len(counts) < 2:
        return None
    order = sorted(counts, key=counts.get, reverse=True)
    top, second = counts[order[0]], counts[order[1]]
    return order[0] if top >= 40 and top >= 3 * max(1, second) else None


def lobby_checks(cfg: dict, frame: np.ndarray, lines: list[Line], diff_clicked: bool = False) -> list[tuple[str, str, bool, str]]:
    # Everything the lobby should show, read off the screen: (key, wanted, ok, what it reads).
    out = []
    diff = str(cfg.get("lobby_difficulty") or "NIGHTMARE").upper()
    if diff in DIFFICULTIES:
        sel = difficulty_selected(frame, lines)
        if sel is None:
            # Can't see the highlight (other window size?): only trusted once it was clicked.
            out.append(("difficulty", diff.title(), diff_clicked, "can't see which is lit" + (", clicked it" if diff_clicked else "")))
        else:
            out.append(("difficulty", diff.title(), DIFFICULTIES[sel] == diff, DIFFICULTIES[sel].title()))
    level = int(cfg.get("lobby_torment") or 0)
    if diff == "TORMENT" and 1 <= level <= len(TORMENTS):
        _label, value = torment_value(lines)
        cur = name_index(value.text, TORMENTS) if value is not None else None
        reads = "Torment " + TORMENTS[cur] if cur is not None else "not read"
        out.append(("torment", "Torment " + TORMENTS[level - 1], cur == level - 1, reads))
    # Torment lobbies have a set GAUNTLET of lands instead of a modifier and START AT.
    gauntlet = diff == "TORMENT" or find_line(lines, "GAUNTLET") is not None
    if cfg.get("lobby_friends_only", True):
        label = find_line(lines, "FRIENDS ONLY")
        on = friends_on(frame, label) if label is not None else None
        out.append(("friends", "Friends Only", on is True, {True: "on", False: "off", None: "not read"}[on]))
    for key, cfg_key, names, value_of in (("modifier", "lobby_modifier", MODIFIERS, modifier_value),
                                          ("start at", "lobby_stage", LANDS, land_value)):
        want = _want(cfg, cfg_key, names)
        if want is None or gauntlet:
            continue
        _label, value = value_of(lines)
        cur = name_index(value.text, names) if value is not None else None
        reads = names[cur].title() if cur is not None else ("'%s'" % value.text if value is not None else "not read")
        out.append((key, names[want].title(), cur == want, reads))
    return out


def checklist(checks) -> str:
    return ", ".join("%s ✓" % what if ok else "%s ✗ (reads %s)" % (what, reads) for _key, what, ok, reads in checks)


def describe_lobby(screen: str, cfg: dict, lines: list[Line], frame: np.ndarray) -> str:
    if screen == CASTLE:
        pt, custom = start_spot(cfg)
        return "Auto lobby: Your Castle, it clicks the %s start spot (%.0f%% across, %.0f%% down)." % (
            "custom" if custom else "default SET OUT >", pt["x"] * 100, pt["y"] * 100)
    if screen == PORTAL:
        return "Auto lobby: Ancient Portal, it clicks STEP THROUGH."
    if screen == SET_OUT:
        return "Auto lobby: Set Out, it clicks FIND A PARTY (Multiplayer)."
    if screen == MULTIPLAYER:
        return "Auto lobby: Multiplayer menu, it clicks HOST A LOBBY."
    checks = lobby_checks(cfg, frame, lines)
    arrows = []
    for key, arrows_of in (("torment", torment_arrows), ("modifier", modifier_arrows), ("start at", land_arrows)):
        if any(c[0] == key for c in checks):
            arrows.append("%s arrows %s" % (key, "found" if arrows_of(frame, lines) else "NOT found"))
    start = "it clicks START RUN after 2 clean checks" if cfg.get("lobby_start", True) else "it waits for you to start"
    return "Auto lobby: Lobby. Check: %s. %s%s." % (checklist(checks) or "nothing to set", "; ".join(arrows) + ", " if arrows else "", start)


class LobbyNav:
    def __init__(
        self,
        cfg: dict,
        reader: Reader,
        status: Callable[[str], None],
        note: Callable[[str, str], None],
        focus: Callable[[], None],
    ) -> None:
        self.cfg = cfg
        self.reader = reader
        self._status = status
        self._note = note
        self._focus = focus
        self.active = False
        self.looked = False
        self.reset()

    def reset(self) -> None:
        self.active = False
        self._next = 0.0
        self._screen = ""
        self._castle_tries = 0
        self._diff_clicks = 0
        self._friends_clicks = 0
        self._friends_offs = 0
        self._spin: dict[str, dict] = {}
        self._why: dict[str, str] = {}
        self._clean = 0

    def step(self, rect, frame: np.ndarray, now: float) -> bool:
        # looked: the screen was read this call, which takes a while, so the frame is old by now.
        self.looked = False
        if not self.cfg.get("auto_lobby"):
            return False
        if now < self._next:
            return self.active
        self.looked = True
        began = time.perf_counter()
        try:
            return self._step(rect, frame, now)
        finally:
            # Reading the screen takes about a second: the wait after a click starts once the
            # click is done, or the next look saw the old screen and clicked every arrow twice.
            self._next += time.perf_counter() - began

    def _step(self, rect, frame: np.ndarray, now: float) -> bool:
        lines = self.reader.read(frame)
        screen = classify(lines)
        if screen is None:
            self.reset()
            self._next = now + IDLE_RECHECK_SEC
            return False
        if screen != self._screen:
            self.reset()
            self._screen = screen
        self.active = True
        self._focus()
        self._next = now + STEP_SETTLE_SEC
        if screen == CASTLE:
            self._castle(rect)
        elif screen == PORTAL:
            if not self._click_label(rect, lines, "STEP THROUGH", "Portal, stepping through."):
                # Not "STEP": that also matches SET OUT on the castle behind the portal.
                self._click_label(rect, lines, "THROUGH", "Portal, stepping through.")
        elif screen == SET_OUT:
            self._set_out(rect, lines)
        elif screen == MULTIPLAYER:
            self._click_label(rect, lines, "HOST A LOBBY", "Multiplayer, hosting a lobby.")
        else:
            self._lobby(rect, frame, lines, now)
        return True

    def _castle(self, rect) -> None:
        pt, custom = start_spot(self.cfg)
        self._castle_tries += 1
        if self._castle_tries > CASTLE_TRIES:
            # Still on the castle: the spot isn't opening anything, keep trying but say so.
            self._status("Your Castle, the start spot didn't open anything after %d clicks, Select it again in the Lobby tab." % CASTLE_TRIES)
        else:
            self._status("Your Castle, clicking the %s start spot." % ("custom" if custom else "SET OUT >"))
        self._click(rect, int(round(pt["x"] * rect.w)), int(round(pt["y"] * rect.h)))

    def _set_out(self, rect, lines: list[Line]) -> None:
        if self._click_label(rect, lines, "FIND A PARTY", "Set Out, picking Multiplayer."):
            return
        # FIND A PARTY sits under the MULTIPLAYER card, as far in as PLAY SOLO is under SOLO.
        title = _exact(lines, "MULTIPLAYER")
        solo, play = _exact(lines, "SOLO"), find_line(lines, "PLAY SOLO")
        if title is None:
            self._status("Set Out, can't read the MULTIPLAYER card.")
            return
        row = [ln for ln in lines if play is not None and abs(ln.cy - play.cy) <= play.h and title.x - 4 <= ln.x <= title.x + title.w * 2]
        if row:
            x, y = row[0].cx, row[0].cy
        elif solo is not None and play is not None:
            x, y = title.x + (play.cx - solo.x), play.cy
        else:
            x, y = title.cx, title.cy
        self._status("Set Out, picking Multiplayer.")
        self._click(rect, x, y)

    def _lobby(self, rect, frame: np.ndarray, lines: list[Line], now: float) -> None:
        # Every look reads the whole lobby. Something wrong: fix that one thing with one click,
        # move the mouse off the controls and look again. START RUN only after CLEAN_CHECKS
        # looks in a row where everything reads right.
        self._next = now + SET_SETTLE_SEC
        lines = read_torment(self.reader, frame, lines)
        checks = lobby_checks(self.cfg, frame, lines, self._diff_clicks > 0)
        bad = [c for c in checks if not c[2]]
        if not bad:
            self._friends_offs = 0
            self._clean += 1
            if self._clean < CLEAN_CHECKS:
                self._status("Lobby check %d/%d: %s." % (self._clean, CLEAN_CHECKS, checklist(checks) or "nothing to set"))
                self._next = now + CHECK_AGAIN_SEC
                return
            if not self.cfg.get("lobby_start", True):
                self._status("Lobby checked (%s), waiting for you to press START RUN." % (checklist(checks) or "nothing to set"))
                self._next = now + IDLE_RECHECK_SEC
                return
            if self._click_label(rect, lines, "START RUN", "Lobby checked (%s), clicking START RUN." % (checklist(checks) or "nothing to set")):
                self._clean = 0
                self._next = now + START_SETTLE_SEC
                return
            self._status("Lobby is set up, but START RUN isn't read yet.")
            return
        self._clean = 0
        for key, what, _ok, reads in bad:
            if self._fix(rect, frame, lines, key, what, reads, now):
                self._park(rect, lines)
                return
        why = ", ".join("%s ✗ (reads %s%s)" % (what, reads, "; " + self._why[key] if key in self._why else "") for key, what, _ok, reads in bad)
        self._status("Lobby NOT ready, not starting: %s." % why)
        self._next = now + IDLE_RECHECK_SEC

    def _fix(self, rect, frame, lines, key: str, what: str, reads: str, now: float) -> bool:
        if key == "difficulty":
            line = difficulty_line(lines, what.upper())
            if self._diff_clicks >= DIFF_TRIES:
                self._why[key] = "clicked it %d times" % DIFF_TRIES
                return False
            if line is None:
                self._why[key] = "button not read"
                return False
            self._diff_clicks += 1
            self._status("Lobby, difficulty reads %s, clicking %s." % (reads, what))
            self._click(rect, line.cx, line.cy)
            return True
        if key == "friends":
            label = find_line(lines, "FRIENDS ONLY")
            if label is None:
                self._why[key] = "button not read"
                return False
            self._friends_offs += 1
            # It's a toggle: a second click only after it has read "off" on two looks in a row
            # since the first one (the game can take a moment), and never more than two clicks.
            if self._friends_clicks and self._friends_offs < 2:
                self._status("Lobby, Friends Only still reads off, giving the click a moment...")
                self._next = now + FRIENDS_SETTLE_SEC
                return True
            if self._friends_clicks >= FRIENDS_TRIES:
                self._why[key] = "clicked it %d times and it still reads off" % FRIENDS_TRIES
                return False
            self._friends_clicks += 1
            self._friends_offs = 0
            self._status("Lobby, Friends Only reads off, clicking it once (%d/%d)." % (self._friends_clicks, FRIENDS_TRIES))
            self._click(rect, label.cx, label.cy)
            self._next = now + FRIENDS_SETTLE_SEC
            return True
        if key == "torment":
            want = int(self.cfg.get("lobby_torment") or 1) - 1
            return self._spin_to(rect, frame, lines, key, TORMENTS, want, torment_value, torment_arrows, False)
        if key == "modifier":
            return self._spin_to(rect, frame, lines, key, MODIFIERS, MODIFIERS.index(what.upper()), modifier_value, modifier_arrows, True)
        return self._spin_to(rect, frame, lines, key, LANDS, LANDS.index(what.upper()), land_value, land_arrows, False)

    def _spin_to(self, rect, frame, lines, key: str, names: tuple[str, ...], want: int, value_of, arrows_of, wraps: bool) -> bool:
        # Clicks < or > towards the wanted name, the short way round when the list wraps
        # (modifiers: Boss Rush is one < from No Modifier). > is taken to go down the list
        # until one click is seen going exactly one step the other way.
        st = self._spin.setdefault(key, {"tries": 0, "sign": 1, "last": None, "push": 0, "still": 0, "dir": 0})
        if st["tries"] >= len(names) + 3:
            self._why[key] = "never came up after %d clicks, not unlocked?" % st["tries"]
            return False
        _label, value = value_of(lines)
        arrows = arrows_of(frame, lines) if value is not None else None
        if arrows is None:
            self._why[key] = "name not read" if value is None else "< > arrows not found"
            return False
        cur = name_index(value.text, names)
        n = len(names)
        if st["last"] is not None and cur is not None:
            moved = cur - st["last"]
            if wraps:
                moved = (moved + n // 2) % n - n // 2
            if moved == 0:
                # Two clicks that changed nothing: the end of a list that doesn't wrap. Go the
                # other way and keep going that way (the short way round would just turn back).
                st["still"] += 1
                if st["still"] >= 2:
                    st["dir"], st["still"] = -st["push"], 0
            else:
                st["still"] = 0
                if moved == -st["push"]:
                    # > and < are the other way round; that also explains any clicks that did nothing.
                    st["sign"], st["dir"] = -st["sign"], 0
        if st["dir"]:
            push = st["dir"]
        elif cur is None:
            push = 1
        elif wraps:
            ahead = (want - cur) % n
            push = 1 if ahead <= n - ahead else -1
        else:
            push = 1 if want > cur else -1
        st["tries"] += 1
        st["last"], st["push"] = cur, push
        (lx, ly), (rx, ry) = arrows
        right = push * st["sign"] > 0
        show = (lambda i: names[i]) if names is TORMENTS else (lambda i: names[i].title())
        self._status("Lobby, %s reads %s, clicking %s for %s (%d)." % (
            key, show(cur) if cur is not None else "unread", ">" if right else "<", show(want), st["tries"]))
        self._click(rect, *((rx, ry) if right else (lx, ly)))
        return True

    def _park(self, rect, lines: list[Line]) -> None:
        # Off the controls before the next look: a hovered button can read as a different state.
        title = _exact(lines, "LOBBY")
        x, y = (title.cx, title.cy) if title is not None else (rect.w // 2, int(rect.h * 0.04))
        time.sleep(0.1)
        hover_at(rect.x + x, rect.y + y)

    def _click_label(self, rect, lines: list[Line], keyword: str, msg: str) -> bool:
        ln = find_line(lines, keyword)
        if ln is None:
            return False
        self._status(msg)
        self._click(rect, ln.cx, ln.cy)
        return True

    def _click(self, rect, wx: int, wy: int) -> None:
        x, y = rect.x + int(wx), rect.y + int(wy)
        hover_at(x, y)
        time.sleep(0.12)
        gui_click_at(x, y)
        self._note("action", "")
