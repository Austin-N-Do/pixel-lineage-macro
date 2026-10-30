from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from app_paths import resource_dir, writable_dir
from advanced_settings import ADVANCED_SECTIONS, DEFAULT_ADVANCED, merge_advanced
from area_selector import AreaSelector, PixelRect
from battle_cycle import DEFAULT_POINTS, Grabber, Runner, _panel_report, describe, log_status, read_en
from credits import LABEL_BY_AUTHOR, LABEL_YT_HOST, YOUTUBE_URL
from games import CLASSES
from input_actions import release_inputs
from lobby import DIFFICULTIES, LANDS, MODIFIERS, TORMENTS
from mouse_control import apply_mouse_timings
from ocr import Reader
import platform_keys
from point_selector import ClickCapture, FracPoint
from roblox_geo import (
    clamp_rect,
    ensure_dpi_awareness,
    roblox_client_rect,
    rect_from_screen,
    rect_to_screen,
    resolve_origin,
)
from scan_outline import OUTLINE_COLOR, PLAYING_COLOR, ScanOutline
from screens import (
    DEFAULT_AREAS,
    crop,
    fight_layout,
    find_cards,
    find_options,
    forget_layouts,
    layout_known,
    lines_in,
    narrow,
    parse_header,
    skill_line,
    text_lit,
)
from timing import DODGE, Player, find_bar
from webhook import LiveMessage, Webhook, capture_roblox, embed
from win_focus import focus_roblox, minimize_tk, pin_topmost_no_activate, place_roblox, restore_tk

APP_DIR = writable_dir()
IS_WINDOWS = sys.platform == "win32"
CONFIG_PATH = APP_DIR / "config.json"
ICON_PATH = resource_dir() / "app.ico"
APP_TITLE = "1vtt's Pixel Lineage Macro"
CONFIG_REV = 8

BG = "#1e1e21"
SURFACE = "#2b2b30"
FIELD = "#161618"
INK = "#eeeae6"
MUTED = "#a39e98"
LINE = "#46464e"
ACCENT = "#e8792b"
ACCENT_DIM = "#a8541a"
ACCENT_TX = "#ffa257"
LINK = "#ffa257"
KEY_FG = "#ffc57a"
GOOD = "#7fd18b"

HOTKEY_LABELS = {
    "hotkey_1": "Start / Stop",
    "hotkey_2": "Minigame area",
    "hotkey_3": "Screen check",
    "hotkey_4": "Exit",
    "hotkey_5": "Auto farm / Manual",
}

AREA_LABELS = {
    "en_area": "EN area",
    "skills_area": "Skill list",
    "path_area": "Path cards",
    "event_area": "Event box",
    "mg_area": "Minigame area",
}

AREA_WHAT = {
    "en_area": "EN text in the bottom left box (NAME  EN 2/10)",
    "skills_area": "skill list that pops up after SKILLS",
    "path_area": "three path cards",
    "event_area": "event box with its choices and the TO BATTLE! button",
    "mg_area": "whole minigame box, from its coloured top line down to the bottom",
}

POINT_LABELS = {
    "attack_btn": "ATTACK row",
    "skills_btn": "SKILLS row",
    "scroll_btn": "SCROLL row",
    "back_btn": "< BACK button",
    "guard_btn": "GUARD row",
    "replay_btn": "Replay spot",
    "start_btn": "Start spot (castle)",
}

# Index = cfg["lobby_torment"]: 0 leaves the level as it is.
TORMENT_CHOICES = ("As it is",) + tuple("Torment " + t for t in TORMENTS)

MANUAL_OPTS = {
    "dodge": "Auto dodge",
    "attack": "Auto attack minigame",
    "skill": "Auto skill (Turn 1/2)",
    "event": "Auto path / event",
    "continue": "Auto continue / loot",
}

SKILL_POINTS = ("attack_btn", "skills_btn", "scroll_btn", "back_btn", "guard_btn")

DEFAULT_CONFIG = {
    "hotkeys": {"hotkey_1": "F1", "hotkey_2": "F2", "hotkey_3": "F3", "hotkey_4": "F4", "hotkey_5": "F5"},
    "class": "Warrior",
    "early_mode": False,
    "play_attack": True,
    "play_dodge": True,
    "manual_mode": False,
    "manual_dodge": True,
    "manual_attack": False,
    "manual_skill": False,
    "manual_event": True,
    "manual_continue": True,
    "skill_on": False,
    "skill_name": "",
    "skill_en": 3,
    "skill_letters": 5,
    "skill_scroll": True,
    "skill_scrolls": 6,
    "scroll_on": False,
    "guard_on": True,
    "follow_light": False,
    "combo_on": False,
    "combo_1": "",
    "combo_2": "",
    "replay_check": True,
    "replay_sec": 10,
    "path_prefer": ["TRAINER'S SHRINE", "SCOUT", "MYSTERY", "BLOOD ALTAR"],
    "path_avoid": ["SHOP", "MERCHANT", "TRADER", "STORE"],
    "event_prefer": [],
    "auto_minimize": False,
    "auto_focus_roblox": True,
    "always_on_top": True,
    "show_outline": True,
    "webhook_log": False,
    "webhook_stuck": True,
    "webhook_url": "",
    "webhook_user": "",
    "loot_alert": True,
    "loot_rarities": "Mythic, Heirloom",
    "loot_skip": "Mythic Whetstone",
    "auto_lobby": False,
    "lobby_difficulty": "NIGHTMARE",
    "lobby_torment": 0,
    "lobby_modifier": "BOSS RUSH",
    "lobby_stage": "",
    "lobby_friends_only": True,
    "lobby_start": True,
    "farm_stage": False,
    "welcome_done": False,
    "points": {},
    "config_rev": CONFIG_REV,
    "advanced": dict(DEFAULT_ADVANCED),
}
for _key, _area in DEFAULT_AREAS.items():
    DEFAULT_CONFIG[_key] = None

AS_IS = "Leave as is"
LAND_CHOICES = (AS_IS,) + tuple("%d  %s" % (i, name) for i, name in enumerate(LANDS, 1))

LIST_KEYS = ("path_prefer", "path_avoid", "event_prefer")
LISTEN_TIMEOUT_MS = 5000
RUN_ERROR_PAUSE_SEC = 1.5
LOG_PATHS = 12
RUN_COLOR = 0xE8792B
STUCK_COLOR = 0xED4245
LOOT_COLOR = 0xE84FA8

BLOCKED_KEYS = {
    "Win_L", "Win_R", "Escape", "Caps_Lock", "Shift_L", "Shift_R",
    "Control_L", "Control_R", "Alt_L", "Alt_R", "BackSpace", "Tab",
    "Enter", "Return", "space",
}

NOTES_TEXT = "Warrior, Mage, Thief, Bard, Fist and Archer are in. I will keep updating this, the last 2 classes get added once I record their minigames.\n\nKeep checking back constantly for updates.\n\nUpdate Log\n\nOct 20 (2)\n- Turn 1 and 2 skills, pick a skill for your first turn and a different one for your second turn of every fight to nuke bosses\n- Skills fixed, EN reads retry and still work when the EN area is a bit off, the mouse jitters onto SKILLS and your skill so the right one gets picked, greyed out skills get skipped, one miss doesnt turn skills off anymore\n- Scroll fixed, if the scroll fails it attacks and uses it again as soon as SCROLL lights up, it never stops using it\n\nOct 20\n- Archer works again, the Power Shot box and power are green now so it was playing it like Thief\n- Use scroll, uses the SCROLL row once a fight\n- Scrolling in the main tab, scrolls the skill list with the mouse wheel to find your skill (S didnt scroll it)\n- After a skill it clicks BACK if the skill list is still up and goes back to attacking\n\nOct 15\n- Mage reads each ring and how fast its closing now, every ring has its own speed so it doesnt fire too early anymore\n- Fixed Warrior bugging out on the 5th bar from taking too long\n- Ultra skills, if your skill isnt showing it presses S to scroll down and find it, set how many letters have to match in the main tab\n- Path backup clicks for when OCR messes up and it doesnt pick a path\n- Replay check, clicks PLAY AGAIN every x seconds if theres no fight going on\n- GUARD, when a boss is about to hit you with an unblockable attack (GUARD !) it guards instead of attacking\n- Fixed it not picking the boss path, it was clicking the hills behind the card instead of the card"

# Everything that used to sit in grey under the boxes, kept out of the way in the Guide tab.
GUIDE = (
    ("Window (Main tab)", "Shows how big the Roblox window is. The macro works full screen or snapped to half the screen. The first time it's in a fight at a new size it reads the ATTACK / SKILLS menu on your turn (that turn waits up to 2 s for it) and moves every fight spot to match. Each size is remembered until you close the macro, so you can switch back and forth. Full screen / Left half / Right half resize Roblox for you. Read menu again forgets what it read, use it if it starts clicking next to the menu. Your own Select spots are used at full width, on a half-screen window it uses the spots it read."),
    ("Hotkeys", "Screen check tells you what the macro sees right now (battle, minigame, path cards, event), use it on every screen once before you leave it running."),
    ("Mode", "Auto farm plays everything. Manual leaves the fight to you and only does what's ticked: Auto dodge plays the dodge bar, Auto attack minigame plays the attack minigame after you attack, Auto skill casts your Turn 1 / Turn 2 skill (or Use a skill) on those turns and leaves every other turn to you, Auto path / event votes the path and picks event choices from your lists, Auto continue / loot clicks through VICTORY, chests, loot (rare drops still go to the webhook), SKIP and CONTINUE. Manual never does the lobby, the replay spot or a blind Space. F5 switches mode, even mid-run."),
    ("1. Battle", "The minigame is worked out from the box itself, only your class's minigame (and the INCOMING! dodge) gets played, so set Class to your hero's class. Early Mode presses Space as soon as the attack minigame shows up. Dodge lands late = raise Dodge timing a bit, early = lower it. Every class minigame has its own timing in Advanced."),
    ("2. Skill", "Type it how it shows in game. Once that many letters of the name match a line in the skill list it uses it, with Scrolling on it scrolls the list to find it (ultra skills). Turn 1 and 2 skills, every fight your first turn uses Turn 1 and your second uses Turn 2 (no EN check, greyed out = it attacks), empty = normal. After a skill it clicks BACK if the list is still up and goes back to attacking. Use scroll uses SCROLL whenever it's lit up and attacks while it's greyed out. GUARD row is used when GUARD ! lights up."),
    ("3. Replay check", "When there hasn't been a fight or a minigame for that long it clicks the replay spot (PLAY AGAIN), backup for when PLAY AGAIN isn't read. Select it on the end screen if your window is a different size."),
    ("4. Read areas", "Defaults are made for a full screen window, on a narrower window the macro moves and widens them itself. Test while that screen is up in game, it says what it read."),
    ("Paths", "It reads each path card (name, type and text) and picks the one highest in Go to first. A card with an Avoid word is only picked when every card is avoided. Typing part of a word is fine, it doesn't care about capitals."),
    ("Auto lobby", "On any of these screens it takes over: Your Castle (start spot), Ancient Portal (STEP THROUGH), Set Out (FIND A PARTY), Multiplayer (HOST A LOBBY), then in the lobby it checks the difficulty (and the Torment level, set with the < > under NORMAL), Friends Only, modifier and START AT, fixes whatever is wrong one click at a time, and only clicks START RUN after two checks in a row where everything reads right. If something can't be set (like a stage you haven't reached) it doesn't start and the status bar says what's wrong. Start at only lists lands your hero has reached in game, a land you haven't reached gets skipped. Use Screen check on each of those screens once, it tells you what it reads and if it found the arrows."),
    ("Start spot (Lobby tab)", "On YOUR CASTLE it clicks the start spot to begin. Default is the gold SET OUT > button bottom right, Select it (with the castle up) to click somewhere else, like the portal. Reset areas on the Main tab puts it back to default."),
    ("Farm one stage", "Reads ACT n/10 at the top left. Once the act goes past the one the run started on (that stage's boss is beaten) it picks the RETURN HOME path, or presses RETURN HOME on the left twice if there's no such card. Set Start at to the stage you want, and auto lobby makes the next lobby. Otherwise it never picks RETURN HOME unless every path is avoided."),
    ("Follow the Light", "When THE LIGHT IS FADING comes up after act 5, on = clicks FOLLOW THE LIGHT and goes on to act 6, off = clicks RETURN TO THE CASTLE. Farm one stage always goes back to the castle."),
    ("Webhook", "Run Log keeps one message updated with your attacks, dodges, skills and the last paths it took. Rare loot sends a screenshot when the spoils screen shows one of those rarities (e.g. Mythic, Heirloom). Drops on the don't-send list are left out, e.g. Mythic Whetstone (or just Whetstone for every rarity)."),
    ("Updates", NOTES_TEXT),
)

WELCOME_ASK = "Would you like to learn how to use this macro?"

WELCOME_GUIDE = "Ok, check this video for the FULL guide on how to utilize the macro:"

GUIDE_URL = "https://www.youtube.com/watch?v=NBm7Socw1SA"


def font(size: int = 9, weight: str = "normal") -> tuple:
    return ("Segoe UI", size, weight)


def normalize_key(event: tk.Event) -> str | None:
    keysym = event.keysym
    if not keysym or keysym in BLOCKED_KEYS:
        return None
    if keysym.startswith("F") and keysym[1:].isdigit():
        return keysym.upper()
    if len(keysym) == 1:
        return keysym.upper()
    special = {
        "plus": "Plus", "minus": "Minus", "equal": "Equal", "comma": "Comma", "period": "Period",
        "slash": "Slash", "backslash": "Backslash", "bracketleft": "LeftBracket",
        "bracketright": "RightBracket", "semicolon": "Semicolon", "apostrophe": "Quote",
        "grave": "Grave", "Prior": "PageUp", "Next": "PageDown", "Up": "Up", "Down": "Down",
        "Left": "Left", "Right": "Right", "Insert": "Insert", "Delete": "Delete",
        "Home": "Home", "End": "End",
    }
    if keysym in special:
        return special[keysym]
    if keysym.lower() in special:
        return special[keysym.lower()]
    return keysym


def _area(raw) -> dict | None:
    if not isinstance(raw, dict) or not all(k in raw for k in ("x", "y", "w", "h")):
        return None
    try:
        return {k: float(raw[k]) for k in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:20]


def _int(value, default: int) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return default


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not CONFIG_PATH.exists():
        save_config(cfg)
        return cfg
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        bak = CONFIG_PATH.with_suffix(".json.bak")
        try:
            CONFIG_PATH.replace(bak)
        except OSError:
            pass
        save_config(cfg)
        print(f"config.json was invalid ({exc}); reset to defaults (backup: {bak.name})")
        return cfg
    if not isinstance(data, dict):
        return cfg
    if isinstance(data.get("hotkeys"), dict):
        cfg["hotkeys"].update({k: str(v) for k, v in data["hotkeys"].items() if k in cfg["hotkeys"]})
    for key in ("early_mode", "play_attack", "play_dodge", "manual_mode", "manual_dodge", "manual_attack", "manual_skill", "manual_event", "manual_continue", "skill_on", "skill_scroll", "scroll_on", "guard_on", "follow_light", "combo_on", "auto_minimize",
                "auto_focus_roblox", "always_on_top", "show_outline", "webhook_log", "webhook_stuck", "loot_alert", "welcome_done",
                "replay_check", "auto_lobby", "lobby_friends_only", "lobby_start", "farm_stage"):
        if key in data:
            cfg[key] = bool(data[key])
    if data.get("class") in CLASSES:
        cfg["class"] = data["class"]
    if str(data.get("lobby_difficulty") or "").upper() in DIFFICULTIES:
        cfg["lobby_difficulty"] = str(data["lobby_difficulty"]).upper()
    try:
        cfg["lobby_torment"] = min(len(TORMENTS), max(0, int(data.get("lobby_torment") or 0)))
    except (TypeError, ValueError):
        pass
    for key, names in (("lobby_modifier", MODIFIERS), ("lobby_stage", LANDS)):
        if key in data:
            name = str(data.get(key) or "").strip().upper()
            cfg[key] = name if name in names else ""
    cfg["skill_name"] = str(data.get("skill_name") or "").strip()[:40]
    cfg["combo_1"] = str(data.get("combo_1") or "").strip()[:40]
    cfg["combo_2"] = str(data.get("combo_2") or "").strip()[:40]
    cfg["skill_en"] = _int(data.get("skill_en"), cfg["skill_en"])
    cfg["skill_letters"] = _int(data.get("skill_letters"), cfg["skill_letters"])
    old_adv = data["advanced"] if isinstance(data.get("advanced"), dict) else {}
    cfg["skill_scrolls"] = _int(data.get("skill_scrolls"), _int(old_adv.get("skill_scroll_max"), cfg["skill_scrolls"]))
    cfg["replay_sec"] = max(3, _int(data.get("replay_sec"), cfg["replay_sec"]))
    for key in LIST_KEYS:
        if isinstance(data.get(key), list):
            cfg[key] = [str(v).strip()[:40] for v in data[key] if str(v).strip()]
    cfg["webhook_url"] = str(data.get("webhook_url") or "").strip()
    cfg["webhook_user"] = _digits(data.get("webhook_user"))
    if "loot_rarities" in data:
        cfg["loot_rarities"] = str(data.get("loot_rarities") or "").strip()[:120]
    if "loot_skip" in data:
        cfg["loot_skip"] = str(data.get("loot_skip") or "").strip()[:200]
    for key in DEFAULT_AREAS:
        cfg[key] = _area(data.get(key))
    if isinstance(data.get("points"), dict):
        for k in DEFAULT_POINTS:
            raw = data["points"].get(k)
            if isinstance(raw, dict) and "x" in raw and "y" in raw:
                try:
                    cfg["points"][k] = {"x": float(raw["x"]), "y": float(raw["y"])}
                except (TypeError, ValueError):
                    pass
    cfg["advanced"] = merge_advanced(data.get("advanced"))
    if _int(data.get("config_rev"), 0) < CONFIG_REV:
        cfg["advanced"] = dict(DEFAULT_ADVANCED)
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(430, 600)
        self.geometry("460x720")
        self.configure(bg=BG)
        self._images: dict[str, tk.PhotoImage] = {}
        for name in ("app.png", "eye.png"):
            try:
                self._images[name] = tk.PhotoImage(file=str(resource_dir() / name))
            except tk.TclError:
                pass
        try:
            if IS_WINDOWS and ICON_PATH.is_file():
                self.iconbitmap(default=str(ICON_PATH))
            elif "app.png" in self._images:
                self.iconphoto(True, self._images["app.png"])
        except tk.TclError:
            pass

        self.cfg = load_config()
        self._listening_for: str | None = None
        self._listen_timer: str | None = None
        self._hotkey_btns: dict[str, ttk.Button] = {}
        self._hotkey_vars: dict[str, tk.StringVar] = {}
        self._hotkey_handles: list = []
        self._status = tk.StringVar(value="Ready.")
        self._running = False
        self._closing = False
        self._persisting = False
        self._area_selector: AreaSelector | None = None
        self._click_capture: ClickCapture | None = None
        self._busy_check = False

        self.class_var = tk.StringVar(value=self.cfg["class"])
        self.early_mode = tk.BooleanVar(value=self.cfg["early_mode"])
        self.play_attack = tk.BooleanVar(value=self.cfg["play_attack"])
        self.play_dodge = tk.BooleanVar(value=self.cfg["play_dodge"])
        self.manual_mode = tk.BooleanVar(value=self.cfg["manual_mode"])
        self.manual_opts = {k: tk.BooleanVar(value=self.cfg["manual_" + k]) for k in MANUAL_OPTS}
        self.skill_on = tk.BooleanVar(value=self.cfg["skill_on"])
        self.skill_name = tk.StringVar(value=self.cfg["skill_name"])
        self.skill_en = tk.StringVar(value=str(self.cfg["skill_en"]))
        self.skill_letters = tk.StringVar(value=str(self.cfg["skill_letters"]))
        self.skill_scroll = tk.BooleanVar(value=self.cfg["skill_scroll"])
        self.skill_scrolls = tk.StringVar(value=str(self.cfg["skill_scrolls"]))
        self.scroll_on = tk.BooleanVar(value=self.cfg["scroll_on"])
        self.guard_on = tk.BooleanVar(value=self.cfg["guard_on"])
        self.follow_light = tk.BooleanVar(value=self.cfg["follow_light"])
        self.combo_on = tk.BooleanVar(value=self.cfg["combo_on"])
        self.combo_1 = tk.StringVar(value=self.cfg["combo_1"])
        self.combo_2 = tk.StringVar(value=self.cfg["combo_2"])
        self.replay_check = tk.BooleanVar(value=self.cfg["replay_check"])
        self.replay_sec = tk.StringVar(value=str(self.cfg["replay_sec"]))
        self.auto_minimize = tk.BooleanVar(value=self.cfg["auto_minimize"])
        self.auto_focus_roblox = tk.BooleanVar(value=self.cfg["auto_focus_roblox"])
        self.always_on_top = tk.BooleanVar(value=self.cfg["always_on_top"])
        self.show_outline = tk.BooleanVar(value=self.cfg["show_outline"])
        self.webhook_log = tk.BooleanVar(value=self.cfg["webhook_log"])
        self.webhook_stuck = tk.BooleanVar(value=self.cfg["webhook_stuck"])
        self.webhook_url = tk.StringVar(value=self.cfg["webhook_url"])
        self.webhook_user = tk.StringVar(value=self.cfg["webhook_user"])
        self.loot_alert = tk.BooleanVar(value=self.cfg["loot_alert"])
        self.loot_rarities = tk.StringVar(value=self.cfg["loot_rarities"])
        self.loot_skip = tk.StringVar(value=self.cfg["loot_skip"])
        self.auto_lobby = tk.BooleanVar(value=self.cfg["auto_lobby"])
        self.lobby_difficulty = tk.StringVar(value=self.cfg["lobby_difficulty"])
        self.lobby_torment = tk.StringVar(value=TORMENT_CHOICES[self.cfg["lobby_torment"]])
        self.lobby_modifier = tk.StringVar(value=self.cfg["lobby_modifier"] or AS_IS)
        self.lobby_stage = tk.StringVar(value=LAND_CHOICES[LANDS.index(self.cfg["lobby_stage"]) + 1] if self.cfg["lobby_stage"] in LANDS else AS_IS)
        self.lobby_friends_only = tk.BooleanVar(value=self.cfg["lobby_friends_only"])
        self.lobby_start = tk.BooleanVar(value=self.cfg["lobby_start"])
        self.farm_stage = tk.BooleanVar(value=self.cfg["farm_stage"])
        self._advanced_vars = {key: tk.StringVar(value=str(self.cfg["advanced"][key])) for key in DEFAULT_ADVANCED}
        for var in self._advanced_vars.values():
            var.trace_add("write", lambda *_: self._persist())
        self._area_labels = {k: tk.StringVar() for k in DEFAULT_AREAS}
        self._point_labels = {k: tk.StringVar() for k in DEFAULT_POINTS}
        self._lists: dict[str, tk.Listbox] = {}

        self._live_screen = tk.StringVar(value="-")
        self._live_counts = tk.StringVar()
        self._window_info = tk.StringVar(value="Looking for Roblox...")
        self._counts = {"attack": 0, "dodge": 0, "skill": 0, "path": 0, "event": 0, "chest": 0, "run": 0}
        self._paths_taken: list[str] = []
        self._run_started = 0.0
        self._last_action = 0.0
        self._stuck_sent = 0

        self._reader = Reader()
        self._player = Player()
        self._outline = ScanOutline(self)
        self._webhook = Webhook()
        self._live_log = LiveMessage()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._posted: queue.SimpleQueue = queue.SimpleQueue()
        self.after(15, self._pump_posted)
        self._apply_runtime_settings()

        self._build_ui()
        self._refresh_labels()
        self._refresh_counts()
        self._apply_always_on_top()
        self._register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind_all("<ButtonPress-1>", self._on_any_click, add="+")
        self._refresh_hotkey_text()
        self.after(300, self._tick_window)
        if not self.cfg.get("welcome_done"):
            self.after(400, self._welcome)
        threading.Thread(target=self._reader.warm, daemon=True).start()

    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, fieldbackground=FIELD, font=font(9))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=INK)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Live.TLabel", foreground=ACCENT_TX, font=font(9, "bold"))
        s.configure("Key.TLabel", background=FIELD, foreground=KEY_FG, font=font(9, "bold"), anchor="center", padding=(6, 2))
        s.configure("TLabelframe", background=BG, bordercolor=LINE, relief="groove")
        s.configure("TLabelframe.Label", background=BG, foreground=ACCENT_TX, font=font(9, "bold"))
        s.configure("TCheckbutton", background=BG, foreground=INK)
        s.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        s.configure("TRadiobutton", background=BG, foreground=INK)
        s.map("TRadiobutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        s.configure("TButton", background=SURFACE, foreground=INK, bordercolor=LINE, padding=(8, 2))
        s.map("TButton", background=[("active", ACCENT), ("pressed", ACCENT_DIM)], foreground=[("active", "#141414")])
        s.configure("Big.TButton", font=font(14, "bold"), padding=(10, 8), background=ACCENT_DIM, foreground=INK)
        s.map("Big.TButton", background=[("active", ACCENT), ("pressed", ACCENT_DIM)], foreground=[("active", "#141414")])
        s.configure("Toolbutton", background=SURFACE, foreground=INK, bordercolor=LINE, padding=(8, 4), anchor="center")
        s.map("Toolbutton", background=[("selected", ACCENT_DIM), ("active", ACCENT)], foreground=[("active", "#141414")])
        s.configure("TEntry", fieldbackground=FIELD, foreground=INK, insertcolor=INK, bordercolor=LINE)
        s.configure("TCombobox", fieldbackground=FIELD, foreground=INK, bordercolor=LINE, arrowcolor=INK, background=SURFACE)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)], selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
        s.configure("TNotebook", background=BG, bordercolor=LINE, tabmargins=(2, 4, 2, 0))
        s.configure("TNotebook.Tab", background=SURFACE, foreground=INK, padding=(6, 3))
        s.map("TNotebook.Tab", background=[("selected", ACCENT_DIM)], foreground=[("disabled", MUTED), ("selected", INK)])
        s.configure("Vertical.TScrollbar", background=SURFACE, troughcolor=BG, bordercolor=LINE, arrowcolor=INK)

    def _link_label(self, parent, text: str, url: str) -> ttk.Label:
        lbl = ttk.Label(parent, text=text, foreground=LINK, cursor="hand2")
        lbl.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        return lbl

    def _muted(self, parent, text: str, wrap: int = 380) -> ttk.Label:
        return ttk.Label(parent, text=text, style="Muted.TLabel", wraplength=wrap, justify="left")

    def _number_entry(self, parent, key: str, width: int) -> ttk.Entry:
        var = self._advanced_vars[key]
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.bind("<FocusOut>", lambda _e, k=key: self._tidy_number(k))
        return entry

    def _tidy_number(self, key: str) -> None:
        var = self._advanced_vars[key]
        try:
            float(var.get())
        except ValueError:
            var.set(str(self.cfg["advanced"][key]))

    def _build_ui(self) -> None:
        self._style()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self._start_btn = ttk.Button(top, text="Press To Start", style="Big.TButton", command=self._on_hotkey_start_stop)
        self._start_btn.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(top, text=LABEL_BY_AUTHOR, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._link_label(top, LABEL_YT_HOST, YOUTUBE_URL).grid(row=1, column=1, sticky="e", pady=(4, 0))

        live = ttk.LabelFrame(self, text="Live", padding=(8, 4))
        live.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 0))
        live.columnconfigure(1, weight=1)
        ttk.Label(live, text="Screen").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(live, textvariable=self._live_screen, style="Live.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(live, textvariable=self._live_counts, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")

        self._tabs = ttk.Notebook(self)
        self._tabs.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        tabs = (
            ("Main", self._build_main_tab),
            ("Paths", self._build_paths_tab),
            ("Lobby", self._build_lobby_tab),
            ("Advanced", self._build_advanced_tab),
            ("Webhook", self._build_webhook_tab),
            ("Guide", self._build_guide_tab),
        )
        for title, build in tabs:
            frame = ttk.Frame(self._tabs)
            self._tabs.add(frame, text=title)
            build(frame)

        foot = ttk.Frame(self, padding=(8, 2, 8, 6))
        foot.grid(row=3, column=0, sticky="ew")
        if "eye.png" in self._images:
            ttk.Label(foot, image=self._images["eye.png"]).pack(side="left", padx=(0, 6))
        ttk.Label(foot, textvariable=self._status, style="Muted.TLabel", wraplength=380, anchor="w").pack(side="left", fill="x", expand=True)

    def _scrollable(self, parent, row: int) -> ttk.Frame:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=row, column=0, sticky="nsew", padx=(6, 0), pady=6)
        bar.grid(row=row, column=1, sticky="ns", pady=6)
        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))

        def wheel(e):
            if not canvas.winfo_exists():
                return
            step = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
            canvas.yview_scroll(step, "units")

        def grab(_e):
            canvas.bind_all("<MouseWheel>", wheel)

        def drop(_e):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", grab)
        canvas.bind("<Leave>", drop)
        return inner

    def _build_main_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        hk = ttk.LabelFrame(parent, text="Hotkeys", padding=6)
        hk.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        hk.columnconfigure(1, weight=1)
        for r, key_id in enumerate(HOTKEY_LABELS):
            ttk.Label(hk, text=HOTKEY_LABELS[key_id]).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=1)
            var = tk.StringVar(value=self.cfg["hotkeys"][key_id])
            self._hotkey_vars[key_id] = var
            ttk.Label(hk, textvariable=var, style="Key.TLabel", width=8).grid(row=r, column=1, sticky="w", pady=1)
            btn = ttk.Button(hk, text="Change", width=11, command=lambda kid=key_id: self._start_listen(kid))
            btn.grid(row=r, column=2, sticky="e", pady=1)
            self._hotkey_btns[key_id] = btn

        mode = ttk.LabelFrame(parent, text="Mode", padding=6)
        mode.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Radiobutton(mode, text="Auto farm", variable=self.manual_mode, value=False, command=self._on_mode_toggled).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode, text="Manual (you play)", variable=self.manual_mode, value=True, command=self._on_mode_toggled).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(mode, text="In Manual, it still does:", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for i, (key, text) in enumerate(MANUAL_OPTS.items()):
            ttk.Checkbutton(mode, text=text, variable=self.manual_opts[key], command=self._persist).grid(row=2 + i // 3, column=i % 3, sticky="w", padx=(0 if i % 3 == 0 else 12, 0))

        win = ttk.LabelFrame(parent, text="Window", padding=6)
        win.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        win.columnconfigure(4, weight=1)
        ttk.Label(win, textvariable=self._window_info, style="Live.TLabel", wraplength=380, justify="left").grid(row=0, column=0, columnspan=5, sticky="w")
        for c, (text, where) in enumerate((("Full screen", "full"), ("Left half", "left"), ("Right half", "right"))):
            ttk.Button(win, text=text, command=lambda w=where: self._place_roblox(w)).grid(row=1, column=c, sticky="w", padx=(0 if c == 0 else 4, 0), pady=(6, 0))
        ttk.Button(win, text="Read menu again", command=self._reread_menu).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(parent, text="What every box does: Guide tab.", style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

        battle = ttk.LabelFrame(parent, text="1. Battle", padding=6)
        battle.grid(row=2, column=0, sticky="nsew", padx=(0, 3), pady=(0, 6))
        crow = ttk.Frame(battle)
        crow.grid(row=0, column=0, sticky="w")
        ttk.Label(crow, text="Class").pack(side="left")
        combo = ttk.Combobox(crow, textvariable=self.class_var, values=CLASSES, width=10, state="readonly")
        combo.pack(side="left", padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._persist())
        ttk.Checkbutton(battle, text="Early Mode", variable=self.early_mode, command=self._persist).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(battle, text="Play attack minigame", variable=self.play_attack, command=self._persist).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(battle, text="Play dodge minigame", variable=self.play_dodge, command=self._persist).grid(row=3, column=0, sticky="w")
        prow = ttk.Frame(battle)
        prow.grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Label(prow, text="Dodge timing").pack(side="left")
        self._number_entry(prow, "dodge_lead_s", 6).pack(side="left", padx=(6, 0))

        skill = ttk.LabelFrame(parent, text="2. Skill", padding=6)
        skill.grid(row=2, column=1, sticky="nsew", padx=(3, 0), pady=(0, 6))
        ttk.Checkbutton(skill, text="Use a skill", variable=self.skill_on, command=self._persist).grid(row=0, column=0, columnspan=2, sticky="w")
        grow = ttk.Frame(skill)
        grow.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(grow, text="Use scroll", variable=self.scroll_on, command=self._persist).pack(side="left")
        ttk.Checkbutton(grow, text="Guard", variable=self.guard_on, command=self._persist).pack(side="left", padx=(10, 0))
        ttk.Label(skill, text="Skill name").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Entry(skill, textvariable=self.skill_name, width=20).grid(row=3, column=0, columnspan=2, sticky="w")
        self.skill_name.trace_add("write", lambda *_: self._persist())
        erow = ttk.Frame(skill)
        erow.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(erow, text="When EN is at least").pack(side="left")
        ttk.Entry(erow, textvariable=self.skill_en, width=4).pack(side="left", padx=(6, 0))
        self.skill_en.trace_add("write", lambda *_: self._persist())
        lrow = ttk.Frame(skill)
        lrow.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(lrow, text="Letters that must match").pack(side="left")
        ttk.Entry(lrow, textvariable=self.skill_letters, width=4).pack(side="left", padx=(6, 0))
        self.skill_letters.trace_add("write", lambda *_: self._persist())
        srow = ttk.Frame(skill)
        srow.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(srow, text="Scrolling, up to", variable=self.skill_scroll, command=self._persist).pack(side="left")
        ttk.Entry(srow, textvariable=self.skill_scrolls, width=4).pack(side="left", padx=(6, 0))
        ttk.Label(srow, text="scrolls").pack(side="left", padx=(4, 0))
        self.skill_scrolls.trace_add("write", lambda *_: self._persist())
        ttk.Checkbutton(skill, text="Turn 1 and 2 skills", variable=self.combo_on, command=self._persist).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for r, (label, var) in enumerate((("Turn 1", self.combo_1), ("Turn 2", self.combo_2)), 8):
            trow = ttk.Frame(skill)
            trow.grid(row=r, column=0, columnspan=2, sticky="w", pady=(2, 0))
            ttk.Label(trow, text=label, width=6).pack(side="left")
            ttk.Entry(trow, textvariable=var, width=15).pack(side="left", padx=(4, 0))
            var.trace_add("write", lambda *_: self._persist())
        for r, key in enumerate(SKILL_POINTS, 10):
            self._point_row(skill, key).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))

        replay = ttk.LabelFrame(parent, text="3. Replay check", padding=6)
        replay.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        rrow = ttk.Frame(replay)
        rrow.grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(rrow, text="Click the replay spot every", variable=self.replay_check, command=self._persist).pack(side="left")
        ttk.Entry(rrow, textvariable=self.replay_sec, width=4).pack(side="left", padx=(6, 0))
        ttk.Label(rrow, text="sec").pack(side="left", padx=(4, 0))
        self.replay_sec.trace_add("write", lambda *_: self._persist())
        self._point_row(replay, "replay_btn").grid(row=1, column=0, sticky="w", pady=(4, 0))

        areas = ttk.LabelFrame(parent, text="4. Read areas", padding=6)
        areas.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        areas.columnconfigure(3, weight=1)
        for r, key in enumerate(("en_area", "skills_area", "path_area", "event_area", "mg_area")):
            ttk.Label(areas, text=AREA_LABELS[key]).grid(row=r, column=0, sticky="w", pady=1)
            ttk.Button(areas, text="Select", width=7, command=lambda k=key: self._select_area(k)).grid(row=r, column=1, sticky="w", padx=(6, 0), pady=1)
            ttk.Button(areas, text="Test", width=5, command=lambda k=key: self._test_area(k)).grid(row=r, column=2, sticky="w", padx=(4, 0), pady=1)
            ttk.Label(areas, textvariable=self._area_labels[key], style="Muted.TLabel").grid(row=r, column=3, sticky="w", padx=(8, 0))
        ttk.Button(areas, text="Reset areas", command=self._reset_areas).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        opts = ttk.LabelFrame(parent, text="Options", padding=6)
        opts.grid(row=5, column=0, columnspan=2, sticky="ew")
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)
        items = (
            ("Auto minimize", self.auto_minimize, self._on_auto_minimize_toggled),
            ("Auto focus Roblox", self.auto_focus_roblox, self._persist),
            ("Always on top", self.always_on_top, self._on_always_on_top_toggled),
            ("Minigame outline", self.show_outline, self._on_outline_toggled),
        )
        for i, (text, var, cmd) in enumerate(items):
            ttk.Checkbutton(opts, text=text, variable=var, command=cmd).grid(row=i // 2, column=i % 2, sticky="w", pady=1)

    def _point_row(self, parent, key: str) -> ttk.Frame:
        row = ttk.Frame(parent)
        ttk.Button(row, text="Select", width=7, command=lambda k=key: self._capture_point(k)).pack(side="left")
        ttk.Label(row, text=POINT_LABELS[key]).pack(side="left", padx=(6, 0))
        ttk.Label(row, textvariable=self._point_labels[key], style="Muted.TLabel").pack(side="left", padx=(6, 0))
        return row

    def _build_paths_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        boxes = (
            ("path_prefer", "Go to first (top = best)", "e.g. TRAINER'S SHRINE, SCOUT, MYSTERY"),
            ("path_avoid", "Avoid", "e.g. SHOP, MINI-BOSS"),
            ("event_prefer", "Event choices (top = best)", "e.g. TRAIN, empty = the first choice"),
        )
        for r, (key, title, hint) in enumerate(boxes, 1):
            self._list_editor(parent, r, key, title, hint)

    def _list_editor(self, parent, row: int, key: str, title: str, hint: str) -> None:
        box = ttk.LabelFrame(parent, text=title, padding=6)
        box.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 6))
        box.columnconfigure(0, weight=1)
        lb = tk.Listbox(
            box, height=5, activestyle="none", bg=FIELD, fg=INK, selectbackground=ACCENT_DIM,
            selectforeground=INK, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
            relief="flat", font=font(9), exportselection=False,
        )
        lb.grid(row=0, column=0, rowspan=3, sticky="nsew")
        for item in self.cfg[key]:
            lb.insert("end", item)
        self._lists[key] = lb
        side = ttk.Frame(box)
        side.grid(row=0, column=1, rowspan=3, sticky="n", padx=(6, 0))
        ttk.Button(side, text="Up", width=7, command=lambda: self._list_move(key, -1)).pack(pady=(0, 2))
        ttk.Button(side, text="Down", width=7, command=lambda: self._list_move(key, 1)).pack(pady=2)
        ttk.Button(side, text="Remove", width=7, command=lambda: self._list_remove(key)).pack(pady=2)
        add = ttk.Frame(box)
        add.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        add.columnconfigure(0, weight=1)
        var = tk.StringVar()
        entry = ttk.Entry(add, textvariable=var)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self._list_add(key, var))
        ttk.Button(add, text="Add", width=7, command=lambda: self._list_add(key, var)).grid(row=0, column=1, padx=(6, 0))
        self._muted(box, hint).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def _list_save(self, key: str) -> None:
        self.cfg[key] = [str(v) for v in self._lists[key].get(0, "end")]
        self._persist()

    def _list_add(self, key: str, var: tk.StringVar) -> None:
        text = " ".join(var.get().split())[:40]
        if not text:
            return
        lb = self._lists[key]
        if text.upper() in (str(v).upper() for v in lb.get(0, "end")):
            self._status.set(f"{text} is already in the list.")
            return
        lb.insert("end", text)
        var.set("")
        self._list_save(key)

    def _list_remove(self, key: str) -> None:
        lb = self._lists[key]
        sel = lb.curselection()
        if not sel:
            return
        lb.delete(sel[0])
        self._list_save(key)

    def _list_move(self, key: str, step: int) -> None:
        lb = self._lists[key]
        sel = lb.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + step
        if j < 0 or j >= lb.size():
            return
        text = lb.get(i)
        lb.delete(i)
        lb.insert(j, text)
        lb.selection_set(j)
        self._list_save(key)

    def _build_lobby_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        box = ttk.LabelFrame(parent, text="Auto lobby", padding=8)
        box.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        box.columnconfigure(1, weight=1)
        ttk.Checkbutton(box, text="Make lobbies and start runs on its own", variable=self.auto_lobby, command=self._persist).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="Difficulty").grid(row=1, column=0, sticky="w", pady=(8, 0))
        diff = ttk.Combobox(box, textvariable=self.lobby_difficulty, values=DIFFICULTIES, width=12, state="readonly")
        diff.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        diff.bind("<<ComboboxSelected>>", lambda _e: self._persist())
        ttk.Label(box, text="Torment level").grid(row=6, column=0, sticky="w", pady=(4, 0))
        tlev = ttk.Combobox(box, textvariable=self.lobby_torment, values=TORMENT_CHOICES, width=12, state="readonly")
        tlev.grid(row=6, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        tlev.bind("<<ComboboxSelected>>", lambda _e: self._persist())
        for r, (text, var, values) in enumerate((("Modifier", self.lobby_modifier, (AS_IS,) + MODIFIERS), ("Start at", self.lobby_stage, LAND_CHOICES)), 2):
            ttk.Label(box, text=text).grid(row=r, column=0, sticky="w", pady=(4, 0))
            pick = ttk.Combobox(box, textvariable=var, values=values, width=26, state="readonly")
            pick.grid(row=r, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
            pick.bind("<<ComboboxSelected>>", lambda _e: self._persist())
        ttk.Checkbutton(box, text="Friends only (private lobby)", variable=self.lobby_friends_only, command=self._persist).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(box, text="Click START RUN once it's set up", variable=self.lobby_start, command=self._persist).grid(row=5, column=0, columnspan=2, sticky="w")
        self._point_row(box, "start_btn").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        run = ttk.LabelFrame(parent, text="During the run", padding=8)
        run.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        ttk.Checkbutton(run, text="Farm one stage, then return home", variable=self.farm_stage, command=self._persist).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(run, text="Follow the Light (acts 6-10)", variable=self.follow_light, command=self._persist).grid(row=2, column=0, sticky="w")

    def _build_advanced_tab(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        head = ttk.Frame(parent, padding=(6, 6, 6, 0))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Saves as you type, Reset defaults fixes anything you mess up", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(head, text="Reset defaults", command=self._reset_advanced).grid(row=0, column=1, sticky="e")
        inner = self._scrollable(parent, 1)
        for section_title, fields in ADVANCED_SECTIONS:
            box = ttk.LabelFrame(inner, text=section_title, padding=6)
            box.pack(fill="x", pady=(0, 6), padx=(0, 4))
            box.columnconfigure(2, weight=1)
            for r, (key, label, help_text) in enumerate(fields):
                ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", pady=1)
                self._number_entry(box, key, width=7).grid(row=r, column=1, sticky="w", padx=6)
                ttk.Label(box, text=help_text, style="Muted.TLabel", wraplength=210, justify="left").grid(row=r, column=2, sticky="w")

    def _build_webhook_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        box = ttk.LabelFrame(parent, text="Discord webhook", padding=8)
        box.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        box.columnconfigure(0, weight=1)
        ttk.Checkbutton(box, text="Keep a Run Log message updated", variable=self.webhook_log, command=self._persist).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(box, text="Ping me when it gets stuck (with a screenshot)", variable=self.webhook_stuck, command=self._persist).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(box, text="Webhook URL").grid(row=2, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(box, textvariable=self.webhook_url).grid(row=3, column=0, sticky="ew")
        self.webhook_url.trace_add("write", lambda *_: self._persist())
        ttk.Label(box, text="Your Discord user ID (pinged when it's stuck)").grid(row=4, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(box, textvariable=self.webhook_user, width=24).grid(row=5, column=0, sticky="w")
        self.webhook_user.trace_add("write", lambda *_: self._persist())
        ttk.Checkbutton(box, text="Screenshot rare loot drops", variable=self.loot_alert, command=self._persist).grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Label(box, text="Rarities to send (comma separated)").grid(row=7, column=0, sticky="w", pady=(4, 2))
        ttk.Entry(box, textvariable=self.loot_rarities).grid(row=8, column=0, sticky="ew")
        self.loot_rarities.trace_add("write", lambda *_: self._persist())
        ttk.Label(box, text="Don't send these drops (comma separated)").grid(row=9, column=0, sticky="w", pady=(4, 2))
        ttk.Entry(box, textvariable=self.loot_skip).grid(row=10, column=0, sticky="ew")
        self.loot_skip.trace_add("write", lambda *_: self._persist())
        ttk.Button(box, text="Send test", command=self._test_webhook).grid(row=11, column=0, sticky="w", pady=(10, 0))

    def _build_guide_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        for r, (title, text) in enumerate(GUIDE):
            box = ttk.LabelFrame(parent, text=title, padding=8)
            box.grid(row=r, column=0, sticky="ew", padx=6, pady=(6 if r == 0 else 0, 6))
            ttk.Label(box, text=text, wraplength=370, justify="left").grid(row=0, column=0, sticky="w")

    def _key_name(self, key_id: str) -> str:
        var = self._hotkey_vars.get(key_id)
        name = var.get().strip() if var is not None else ""
        return name or str(self.cfg["hotkeys"].get(key_id) or "")

    def _refresh_hotkey_text(self) -> None:
        start = self._key_name("hotkey_1")
        if self._running:
            self._start_btn.configure(text="Press To Stop (%s)" % start if start else "Press To Stop")
        else:
            self._start_btn.configure(text="Press To Start (%s)" % start if start else "Press To Start")
        if self._status.get().startswith("Ready"):
            check = self._key_name("hotkey_3")
            self._status.set("Ready. %s to enable, %s to screen check." % (start, check) if start and check else "Ready.")

    def _dialog(self, title: str, message: str):
        win = tk.Toplevel(self)
        win.withdraw()
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        eye = self._images.get("eye.png")
        if eye is not None:
            self._images["eye_big.png"] = eye.zoom(2)
            ttk.Label(frame, image=self._images["eye_big.png"]).pack(pady=(0, 8))
        text = ttk.Label(frame, text=message, wraplength=300, justify="center")
        text.pack()
        row = ttk.Frame(frame)
        row.pack(pady=(12, 0))
        return win, frame, text, row

    def _show_dialog(self, win: tk.Toplevel, buttons: list, ready: dict, seconds: int = 3) -> None:
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()

        def tick(left: int) -> None:
            try:
                if left > 0:
                    for button, label in buttons:
                        button.configure(text=f"{label} ({left})")
                    win.after(1000, tick, left - 1)
                    return
                ready["open"] = True
                for button, label in buttons:
                    button.configure(text=label, state="normal")
            except tk.TclError:
                pass

        tick(seconds)

    def _welcome(self) -> None:
        self.cfg["welcome_done"] = True
        self._persist()
        win, frame, text, row = self._dialog("Welcome", WELCOME_ASK)
        ready = {"open": False}

        def close() -> None:
            if not ready["open"]:
                return
            try:
                win.grab_release()
            except tk.TclError:
                pass
            win.destroy()

        def guide() -> None:
            for child in row.winfo_children():
                child.destroy()
            text.configure(text=WELCOME_GUIDE)
            self._link_label(frame, GUIDE_URL, GUIDE_URL).pack(before=row, pady=(6, 0))
            ttk.Button(row, text="OK", command=close).pack(side="left", padx=6)

        yes = ttk.Button(row, text="Yes", command=guide, state="disabled")
        no = ttk.Button(row, text="No", command=close, state="disabled")
        yes.pack(side="left", padx=6)
        no.pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", close)
        self._show_dialog(win, [(yes, "Yes"), (no, "No")], ready)

    def _reset_advanced(self) -> None:
        for key, var in self._advanced_vars.items():
            var.set(str(DEFAULT_ADVANCED[key]))
        self._apply_runtime_settings()
        self._status.set("Advanced settings reset to defaults.")

    def _collect_advanced(self) -> dict[str, float]:
        out = dict(self.cfg["advanced"])
        for key, var in self._advanced_vars.items():
            try:
                out[key] = float(var.get())
            except ValueError:
                continue
        return out

    def _apply_runtime_settings(self) -> None:
        adv = self.cfg["advanced"]
        apply_mouse_timings(
            nudge_mid_sec=adv["mouse_nudge_mid_sec"],
            nudge_settle_sec=adv["mouse_nudge_settle_sec"],
            click_hold_sec=adv["mouse_click_hold_sec"],
        )
        self._player.configure(adv)

    def _persist(self) -> None:
        if self._persisting:
            return
        self._persisting = True
        try:
            self.cfg["hotkeys"] = {kid: var.get() for kid, var in self._hotkey_vars.items()} or self.cfg["hotkeys"]
            self.cfg["class"] = self.class_var.get() if self.class_var.get() in CLASSES else CLASSES[0]
            self.cfg["early_mode"] = bool(self.early_mode.get())
            self.cfg["play_attack"] = bool(self.play_attack.get())
            self.cfg["play_dodge"] = bool(self.play_dodge.get())
            self.cfg["manual_mode"] = bool(self.manual_mode.get())
            for k, var in self.manual_opts.items():
                self.cfg["manual_" + k] = bool(var.get())
            self.cfg["skill_on"] = bool(self.skill_on.get())
            self.cfg["skill_name"] = " ".join(self.skill_name.get().split())[:40]
            self.cfg["skill_en"] = _int(self.skill_en.get(), self.cfg["skill_en"])
            self.cfg["skill_letters"] = _int(self.skill_letters.get(), self.cfg["skill_letters"])
            self.cfg["skill_scroll"] = bool(self.skill_scroll.get())
            self.cfg["skill_scrolls"] = _int(self.skill_scrolls.get(), self.cfg["skill_scrolls"])
            self.cfg["scroll_on"] = bool(self.scroll_on.get())
            self.cfg["guard_on"] = bool(self.guard_on.get())
            self.cfg["follow_light"] = bool(self.follow_light.get())
            self.cfg["combo_on"] = bool(self.combo_on.get())
            self.cfg["combo_1"] = " ".join(self.combo_1.get().split())[:40]
            self.cfg["combo_2"] = " ".join(self.combo_2.get().split())[:40]
            self.cfg["replay_check"] = bool(self.replay_check.get())
            self.cfg["replay_sec"] = max(3, _int(self.replay_sec.get(), self.cfg["replay_sec"]))
            self.cfg["auto_minimize"] = bool(self.auto_minimize.get())
            self.cfg["auto_focus_roblox"] = bool(self.auto_focus_roblox.get())
            self.cfg["always_on_top"] = bool(self.always_on_top.get())
            self.cfg["show_outline"] = bool(self.show_outline.get())
            self.cfg["webhook_log"] = bool(self.webhook_log.get())
            self.cfg["webhook_stuck"] = bool(self.webhook_stuck.get())
            self.cfg["webhook_url"] = self.webhook_url.get().strip()
            self.cfg["webhook_user"] = _digits(self.webhook_user.get())
            self.cfg["loot_alert"] = bool(self.loot_alert.get())
            self.cfg["loot_rarities"] = self.loot_rarities.get().strip()[:120]
            self.cfg["loot_skip"] = self.loot_skip.get().strip()[:200]
            self.cfg["auto_lobby"] = bool(self.auto_lobby.get())
            diff = self.lobby_difficulty.get().upper()
            self.cfg["lobby_difficulty"] = diff if diff in DIFFICULTIES else "NIGHTMARE"
            tlev = self.lobby_torment.get()
            self.cfg["lobby_torment"] = TORMENT_CHOICES.index(tlev) if tlev in TORMENT_CHOICES else 0
            mod = self.lobby_modifier.get()
            self.cfg["lobby_modifier"] = mod if mod in MODIFIERS else ""
            stage = self.lobby_stage.get()
            self.cfg["lobby_stage"] = LANDS[LAND_CHOICES.index(stage) - 1] if stage in LAND_CHOICES[1:] else ""
            self.cfg["lobby_friends_only"] = bool(self.lobby_friends_only.get())
            self.cfg["lobby_start"] = bool(self.lobby_start.get())
            self.cfg["farm_stage"] = bool(self.farm_stage.get())
            self.cfg["advanced"] = self._collect_advanced()
            self._player.configure(self.cfg["advanced"])
            save_config(self.cfg)
        finally:
            self._persisting = False

    def _refresh_labels(self) -> None:
        for key, var in self._area_labels.items():
            area = self.cfg.get(key)
            var.set("custom" if area else "default")
        for key, var in self._point_labels.items():
            raw = (self.cfg.get("points") or {}).get(key)
            var.set("custom" if raw else "default")

    def _refresh_counts(self) -> None:
        c = self._counts
        run = self._run_time() if self._running else "0:00:00"
        self._live_counts.set(
            "Attacks %d   Dodges %d   Skills %d   Paths %d   Events %d\nChests %d   Runs done %d   Run time %s"
            % (c["attack"], c["dodge"], c["skill"], c["path"], c["event"], c["chest"], c["run"], run)
        )

    def _window_text(self) -> str:
        rect = roblox_client_rect()
        if rect is None:
            return "Roblox not found."
        kind = "half screen" if narrow(rect.w, rect.h) > 1.05 else "full width"
        lay = fight_layout(rect.w, rect.h)
        if not layout_known(rect.w, rect.h):
            menu = "Fight menu not read yet, it reads it on your first turn."
        elif lay is None:
            menu = "Fight menu read, the spots fit."
        else:
            menu = "Fight menu read (%d%% size), fight spots moved to match." % round(lay.scale * 100)
        return "Roblox %d x %d (%s). %s" % (rect.w, rect.h, kind, menu)

    def _tick_window(self) -> None:
        if self._closing:
            return
        try:
            self._window_info.set(self._window_text())
        except Exception:
            pass
        self.after(1500, self._tick_window)

    def _place_roblox(self, where: str) -> None:
        if not place_roblox(where):
            self._status.set("Couldn't move the Roblox window (is it open?).")
            return
        self._status.set("Roblox moved, the fight menu gets read on your next turn if the size is new.")
        self.after(400, lambda: self._window_info.set(self._window_text()))

    def _reread_menu(self) -> None:
        forget_layouts()
        self._status.set("It reads the fight menu again on your next turn.")
        self._window_info.set(self._window_text())

    def _tick_counts(self) -> None:
        if not self._running or self._closing:
            return
        self._refresh_counts()
        self.after(1000, self._tick_counts)

    def _run_time(self) -> str:
        run = int(time.monotonic() - self._run_started)
        return f"{run // 3600}:{run // 60 % 60:02d}:{run % 60:02d}"

    def _on_note(self, kind: str, info: str) -> None:
        if kind == "loot":
            # Sent even if you stopped the macro right as the drop showed up.
            if self.cfg["webhook_url"]:
                payload = {"allowed_mentions": {"parse": []}, "embeds": [embed("Rare drop!", LOOT_COLOR, [], info.replace(", ", "\n"))]}
                threading.Thread(target=self._send_webhook, args=(payload, "loot"), daemon=True).start()
            return
        if not self._running:
            return
        self._last_action = time.monotonic()
        self._stuck_sent = 0
        if kind == "screen":
            self._outline.set_color(PLAYING_COLOR if info == "minigame" else OUTLINE_COLOR)
            self._live_screen.set({
                "minigame": "Minigame",
                "battle": "Battle",
                "path": "Choose Your Path",
                "event": "Event",
                "chest": "Chest",
                "victory": "Victory",
                "continue": "Continue",
                "end": "Run finished",
                "lobby": "Lobby",
            }.get(info, info))
            return
        if kind == "action":
            return
        if kind in self._counts:
            if kind in ("attack", "dodge") and info == "0":
                return
            self._counts[kind] += 1
        if kind == "path":
            self._paths_taken.append(info)
            self._paths_taken = self._paths_taken[-LOG_PATHS:]
        self._refresh_counts()
        if kind in ("path", "skill", "chest", "run") or (kind in ("attack", "dodge") and (self._counts["attack"] + self._counts["dodge"]) % 5 == 0):
            self._push_log()

    def _push_log(self) -> None:
        if not (self.cfg["webhook_log"] and self.cfg["webhook_url"]):
            return
        c = self._counts
        paths = "\n".join("• %s" % p for p in reversed(self._paths_taken)) or "No paths yet"
        log = embed("Run Log", RUN_COLOR, [
            ("Attacks", str(c["attack"])),
            ("Dodges", str(c["dodge"])),
            ("Skills", str(c["skill"])),
            ("Paths", str(c["path"])),
            ("Chests", str(c["chest"])),
            ("Runs done", str(c["run"])),
            ("Running for", self._run_time()),
        ], "\nLast paths:\n" + paths)
        payload = {"allowed_mentions": {"parse": []}, "embeds": [log]}
        self._live_log.update(self.cfg["webhook_url"], payload, lambda msg: self._post(lambda: self._status.set(f"Webhook run log: {msg}.")))

    def _ping(self, payload: dict) -> dict:
        uid = self.cfg["webhook_user"]
        if uid:
            payload["content"] = f"<@{uid}>"
            payload["allowed_mentions"] = {"users": [uid]}
        else:
            payload["allowed_mentions"] = {"parse": []}
        return payload

    def _test_webhook(self) -> None:
        if not self.cfg["webhook_url"]:
            self._status.set("Paste your webhook URL first.")
            return
        self._status.set("Sending a test to the webhook...")
        payload = self._ping({"embeds": [embed("Webhook works :)", RUN_COLOR, [], "Test from " + APP_TITLE + ".")]})
        threading.Thread(target=self._send_webhook, args=(payload, "test"), daemon=True).start()

    def _send_webhook(self, payload: dict, what: str) -> bool:
        try:
            frame = capture_roblox()
        except Exception:
            frame = None

        def report(msg: str) -> None:
            log_status(f"Webhook {what}: {msg}.")
            self._post(lambda: self._status.set(f"Webhook {what}: {msg}."))

        if self._webhook.send(self.cfg["webhook_url"], payload, frame, report, wait=what == "loot"):
            return True
        report("still sending the last one, skipped")
        return False

    def _stuck_watch(self, stop: threading.Event) -> None:
        while not stop.wait(1.0):
            if not (self.cfg["webhook_stuck"] and self.cfg["webhook_url"]):
                continue
            limit = max(30.0, float(self.cfg["advanced"]["stuck_alert_sec"]))
            idle = time.monotonic() - self._last_action
            if idle < (self._stuck_sent + 1) * limit:
                continue
            payload = self._ping({"embeds": [embed(
                "Possibly stuck OR disconnected", STUCK_COLOR,
                [("Paths", str(self._counts["path"])), ("Running for", self._run_time())],
                f"Nothing happened in the last {int(idle)} seconds.",
            )]})
            if self._send_webhook(payload, "stuck alert"):
                self._stuck_sent = int(idle // limit)

    def _on_hotkey_mode(self) -> None:
        if self._listening_for is not None:
            return
        self.manual_mode.set(not self.manual_mode.get())
        self._on_mode_toggled()

    def _on_mode_toggled(self) -> None:
        # The runner reads cfg every loop, so this switches mid-run.
        self._persist()
        if self.manual_mode.get():
            on = [MANUAL_OPTS[k].lower() for k, var in self.manual_opts.items() if var.get()]
            self._status.set("Manual: you play, it handles %s." % (", ".join(on) or "nothing"))
        else:
            self._status.set("Auto farm: it plays everything.")

    def _on_auto_minimize_toggled(self) -> None:
        self._persist()
        if not self.auto_minimize.get() and not self._running:
            restore_tk(self, keep_topmost=bool(self.always_on_top.get()), activate=False)

    def _on_always_on_top_toggled(self) -> None:
        self._persist()
        self._apply_always_on_top()

    def _apply_always_on_top(self) -> None:
        pin_topmost_no_activate(self, bool(self.always_on_top.get()))

    def _on_outline_toggled(self) -> None:
        self._persist()
        if self._running and self.show_outline.get():
            self._show_outline()
        else:
            self._outline.hide()

    def _show_outline(self) -> None:
        origin = resolve_origin()
        if origin.source != "roblox":
            return
        area = self.cfg.get("mg_area") or DEFAULT_AREAS["mg_area"]
        try:
            self._outline.update(rect_to_screen(area["x"], area["y"], area["w"], area["h"], origin))
        except tk.TclError:
            pass

    def _minimize_gui(self) -> None:
        try:
            minimize_tk(self)
        except tk.TclError:
            pass

    def _restore_gui(self, *, activate: bool = True) -> None:
        restore_tk(self, keep_topmost=bool(self.always_on_top.get()), activate=activate)

    def _focus_roblox_keep_gui_on_top(self) -> None:
        focus_roblox()
        pin_topmost_no_activate(self, True)

    def _on_hotkey_window_effects(self, *, turning_on: bool) -> None:
        auto_min = bool(self.auto_minimize.get())
        auto_focus = bool(self.auto_focus_roblox.get())
        on_top = bool(self.always_on_top.get())
        if turning_on:
            if auto_min:
                self.after(30, self._minimize_gui)
            if auto_focus:
                delay = 120 if auto_min else 40
                if on_top and not auto_min:
                    self.after(delay, self._focus_roblox_keep_gui_on_top)
                else:
                    self.after(delay, focus_roblox)
            elif on_top and not auto_min:
                self.after(40, self._apply_always_on_top)
            return
        if auto_min:
            self.after(0, lambda: self._restore_gui(activate=True))
        if on_top:
            self.after(80 if auto_min else 0, self._apply_always_on_top)

    def _calibrator_open(self) -> bool:
        if self._area_selector is not None and self._area_selector.winfo_exists():
            return True
        if self._click_capture is not None and self._click_capture.winfo_exists():
            return True
        return False

    def _select_area(self, key: str) -> None:
        if self._running:
            self._status.set("Stop first, then select the area.")
            return
        if self._calibrator_open():
            return
        origin = resolve_origin()
        if origin.source != "roblox":
            self._status.set("Open Roblox first, areas are saved inside the Roblox window.")
            return
        area = self.cfg.get(key) or DEFAULT_AREAS[key]
        bounds = origin.as_pixel_rect
        initial = rect_to_screen(area["x"], area["y"], area["w"], area["h"], origin).clamp_within(bounds)
        self._status.set(f"Drag the box over the {AREA_WHAT[key]}. Enter saves, Esc cancels.")
        self._area_selector = AreaSelector(
            self,
            initial=initial,
            bounds=bounds,
            on_saved=lambda rect: self._on_area_saved(key, rect),
            on_cancelled=self._on_area_cancelled,
        )
        self._on_hotkey_window_effects(turning_on=True)

    def _on_area_saved(self, key: str, rect: PixelRect) -> None:
        self._area_selector = None
        origin = resolve_origin()
        fx, fy, fw, fh = clamp_rect(*rect_from_screen(rect, origin))
        self.cfg[key] = {"x": fx, "y": fy, "w": fw, "h": fh}
        self._persist()
        self._refresh_labels()
        self._on_hotkey_window_effects(turning_on=False)
        self._status.set(f"{AREA_LABELS[key]} saved. Press Test while that screen is up.")

    def _on_area_cancelled(self) -> None:
        self._area_selector = None
        self._on_hotkey_window_effects(turning_on=False)
        self._status.set("Area select cancelled.")

    def _reset_areas(self) -> None:
        if self._running:
            self._status.set("Stop first, then reset the areas.")
            return
        for key in DEFAULT_AREAS:
            self.cfg[key] = None
        self.cfg["points"] = {}
        self._persist()
        self._refresh_labels()
        self._status.set("Every area and button is back to default.")

    def _capture_point(self, key: str) -> None:
        if self._running:
            self._status.set("Stop first, then set points.")
            return
        if self._calibrator_open():
            self._status.set("Finish the current select first.")
            return
        label = POINT_LABELS[key]
        self._status.set(f"Click the {label} in game...")

        def on_saved(pt: FracPoint, source: str) -> None:
            self._click_capture = None
            self.cfg.setdefault("points", {})[key] = {"x": pt.x, "y": pt.y}
            self._persist()
            self._refresh_labels()
            self._status.set(f"{label} saved ({source}).")

        def on_cancelled() -> None:
            self._click_capture = None
            self._status.set("Point set cancelled.")

        self._click_capture = ClickCapture(self, prompt=f"Click the {label}", on_saved=on_saved, on_cancelled=on_cancelled)

    def _test_area(self, key: str) -> None:
        if self._busy_check:
            return
        self._busy_check = True
        self._status.set(f"Testing the {AREA_LABELS[key]}...")
        cfg = json.loads(json.dumps(self.cfg))

        def run() -> None:
            grabber = Grabber()
            try:
                msg = self._area_report(key, cfg, grabber)
            except Exception as exc:
                msg = f"Test failed: {exc}"
            finally:
                grabber.close()
            self._post(lambda: self._finish_check(msg))

        threading.Thread(target=run, daemon=True).start()

    def _area_report(self, key: str, cfg: dict, grabber: Grabber) -> str:
        origin = resolve_origin()
        if origin.source != "roblox":
            return "Roblox not found, open it first."
        frame = grabber.grab(origin.x, origin.y, origin.w, origin.h)
        img, _x, _y = crop(frame, cfg.get(key) or DEFAULT_AREAS[key])
        if img is None or img.size == 0:
            return "Couldn't capture Roblox."
        if key == "mg_area":
            bar = find_bar(img)
            if bar is not None:
                return "Minigame bar found (%s)." % ("dodge" if bar.kind == DODGE else "attack")
            return _panel_report(cfg, frame, origin) or "No minigame in the minigame area right now."
        lines = self._reader.read(img)
        text = " / ".join(ln.text for ln in lines)
        if key == "en_area":
            head = parse_header(text)
            if head and head[0] == "menu":
                return "EN %d/%d (read: %s)" % (head[1], head[2], text)
            en = read_en(self._reader, frame, cfg)
            if en is not None:
                return "The EN area read '%s', a bit bigger it reads EN %d/%d so it still works, Select it again over the whole EN line to be safe." % (text or "nothing", en[0], en[1])
            return "No EN read (read: %s)" % (text or self._reader.why or "nothing")
        if key == "skills_area":
            name = self.cfg.get("skill_name") or ""
            line = skill_line(lines, name, int(self.cfg.get("skill_letters") or 0)) if name else None
            found = (" Found %s." % name) if line else (" %s not found." % name if name else "")
            for k in ("combo_1", "combo_2"):
                want = str(self.cfg.get(k) or "").strip()
                if want:
                    hit = skill_line(lines, want, 0, True)
                    found += " Turn %s %s: %s." % (k[-1], want, ("found, " + ("lit" if text_lit(img, hit) else "greyed out")) if hit else "not found")
            return "Skill list read: %s.%s" % (text or "nothing", found)
        if key == "path_area":
            cards = find_cards(img, origin.h)
            names = [(lines_in(lines, c)[0].text if lines_in(lines, c) else "?") for c in cards]
            return "%d path cards: %s" % (len(cards), ", ".join(names) or "none")
        opts = find_options(img, origin.h)
        names = [(lines_in(lines, o)[0].text if lines_in(lines, o) else "?") for o in opts]
        return "Event box: %d choices (%s). Read: %s" % (len(opts), ", ".join(names) or "none", text or "nothing")

    def _finish_check(self, msg: str) -> None:
        self._busy_check = False
        self._status.set(msg)

    def _on_hotkey_screen_check(self) -> None:
        if self._listening_for is not None or self._busy_check:
            return
        if self._running:
            self._status.set("Stop first, then press Screen check.")
            return
        self._busy_check = True
        self._status.set("Checking the screen...")
        cfg = json.loads(json.dumps(self.cfg))

        def run() -> None:
            grabber = Grabber()
            try:
                msg = describe(cfg, self._reader, grabber)
            except Exception as exc:
                msg = f"Screen check failed: {exc}"
            finally:
                grabber.close()
            self._post(lambda: self._finish_check(msg))

        threading.Thread(target=run, daemon=True).start()

    def _start_run(self) -> bool:
        if resolve_origin().source != "roblox":
            self._status.set("Open Roblox first.")
            return False
        self._persist()
        self._apply_runtime_settings()
        old = self._worker
        if old is not None and old.is_alive():
            old.join(timeout=1.0)
        self._running = True
        self._stop_event = threading.Event()
        self._counts = {k: 0 for k in self._counts}
        self._paths_taken = []
        self._run_started = time.monotonic()
        self._last_action = self._run_started
        self._stuck_sent = 0
        self._live_log.reset()
        self._live_screen.set("-")
        self._refresh_counts()
        self._refresh_hotkey_text()
        self._status.set("Running...")
        if self.show_outline.get():
            self._show_outline()
        self._worker = threading.Thread(target=self._run_loop, args=(self._stop_event,), daemon=True)
        self._worker.start()
        threading.Thread(target=self._stuck_watch, args=(self._stop_event,), daemon=True).start()
        self.after(1000, self._tick_counts)
        return True

    def _stop_run(self) -> None:
        self._running = False
        self._stop_event.set()
        release_inputs()
        self._outline.hide()
        self._status.set("Stopped.")
        self._refresh_hotkey_text()

    def _run_loop(self, stop: threading.Event) -> None:
        def aborted() -> bool:
            return stop.is_set() or self._closing

        def status(msg: str) -> None:
            self._post(lambda m=msg: None if stop.is_set() else self._status.set(m))

        def note(kind: str, info: str) -> None:
            self._post(lambda: self._on_note(kind, info))

        runner = None
        try:
            while not aborted():
                try:
                    if runner is None:
                        runner = Runner(self.cfg, self._reader, self._player, aborted, status, note)
                    runner.loop()
                except Exception as exc:
                    release_inputs()
                    log_status("ERROR, restarting:\n" + traceback.format_exc())
                    status(f"Error, restarting: {exc}")
                    if runner is not None:
                        runner.close()
                        runner = None
                    end = time.monotonic() + RUN_ERROR_PAUSE_SEC
                    while time.monotonic() < end and not aborted():
                        time.sleep(0.05)
        finally:
            if runner is not None:
                runner.close()
            release_inputs()

    def _unregister_hotkeys(self) -> None:
        for handle in self._hotkey_handles:
            try:
                platform_keys.remove_hotkey(handle)
            except Exception:
                pass
        self._hotkey_handles.clear()

    def _register_hotkeys(self) -> None:
        self._unregister_hotkeys()
        mapping = {
            "hotkey_1": self._on_hotkey_start_stop,
            "hotkey_2": self._on_hotkey_area,
            "hotkey_3": self._on_hotkey_screen_check,
            "hotkey_4": self._on_hotkey_exit,
            "hotkey_5": self._on_hotkey_mode,
        }
        for key_id, callback in mapping.items():
            name = self._hotkey_vars[key_id].get()
            try:
                self._hotkey_handles.append(platform_keys.add_hotkey(name, lambda cb=callback: self._post(cb)))
            except Exception as exc:
                self._status.set(f"Couldn't bind {HOTKEY_LABELS[key_id]}: {exc}")

    def _on_hotkey_start_stop(self) -> None:
        if self._listening_for is not None:
            return
        if self._calibrator_open():
            self._status.set("Finish selecting first.")
            return
        if self._running:
            self._stop_run()
            self._on_hotkey_window_effects(turning_on=False)
        elif self._start_run():
            self._on_hotkey_window_effects(turning_on=True)

    def _on_hotkey_area(self) -> None:
        if self._listening_for is not None:
            return
        if self._area_selector is not None and self._area_selector.winfo_exists():
            self._area_selector.cancel()
            return
        self._select_area("mg_area")

    def _on_hotkey_exit(self) -> None:
        if self._listening_for is not None:
            return
        self._on_close()

    def _post(self, fn) -> None:
        self._posted.put(fn)

    def _pump_posted(self) -> None:
        if self._closing:
            return
        try:
            for _ in range(64):
                try:
                    fn = self._posted.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception as exc:
                    self._status.set(f"Error: {exc}")
        finally:
            self.after(15, self._pump_posted)

    def _start_listen(self, key_id: str) -> None:
        if self._listening_for is not None:
            same = self._listening_for == key_id
            self._stop_listen("Hotkey change cancelled.")
            if same:
                return
        self._listening_for = key_id
        self._hotkey_btns[key_id].configure(text="Press a key")
        self._listen_timer = self.after(LISTEN_TIMEOUT_MS, lambda: self._stop_listen("Hotkey change timed out."))
        self._status.set(f"Press a key for {HOTKEY_LABELS[key_id]}... (Esc or a click cancels)")
        self.focus_force()

    def _stop_listen(self, message: str | None = None) -> None:
        if self._listening_for is None:
            return
        self._hotkey_btns[self._listening_for].configure(text="Change")
        self._listening_for = None
        if self._listen_timer is not None:
            self.after_cancel(self._listen_timer)
            self._listen_timer = None
        if message:
            self._status.set(message)

    def _on_any_click(self, event: tk.Event) -> None:
        if self._listening_for is not None and event.widget is not self._hotkey_btns.get(self._listening_for):
            self._stop_listen("Hotkey change cancelled.")

    def _on_key_press(self, event: tk.Event) -> str | None:
        if self._listening_for is None:
            return None
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Listbox)):
            self._stop_listen("Hotkey change cancelled.")
            return None
        if event.keysym == "Escape":
            self._stop_listen("Hotkey change cancelled.")
            return "break"
        new_key = normalize_key(event)
        if new_key is None:
            self._status.set("That key can't be used. Try another.")
            return "break"
        key_id = self._listening_for
        for other_id, var in self._hotkey_vars.items():
            if other_id != key_id and var.get().upper() == new_key.upper():
                messagebox.showwarning("Hotkey in use", f'"{new_key}" is already assigned to {HOTKEY_LABELS[other_id]}.', parent=self)
                return "break"
        self._hotkey_vars[key_id].set(new_key)
        self._stop_listen()
        self._persist()
        self._register_hotkeys()
        self._refresh_hotkey_text()
        self._status.set(f"{HOTKEY_LABELS[key_id]} set to {new_key}.")
        return "break"

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_event.set()
        self._running = False
        release_inputs()
        self._outline.hide()
        for widget in (self._area_selector, self._click_capture):
            if widget is not None and widget.winfo_exists():
                try:
                    widget.cancel()
                except Exception:
                    pass
        self._unregister_hotkeys()
        self._reader.stop()
        try:
            platform_keys.unhook_all()
        except Exception:
            pass
        self._persist()
        self.destroy()


def main() -> None:
    ensure_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
