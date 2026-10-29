from __future__ import annotations

DEFAULT_ADVANCED: dict[str, float] = {
    "dodge_lead_s": 0.035,
    "press_lead_s": 0.035,
    "aim_bias": 0.0,
    "min_speed": 0.12,
    "press_hold_s": 0.03,
    "meter_lead_s": 0.05,
    "bard_lead_s": 0.035,
    "mage_lead_s": 0.035,
    "mage_close": 1.3,
    "thief_delay_s": 0.045,
    "early_gap_sec": 0.35,
    "minigame_lost_s": 0.6,
    "minigame_max_s": 8.0,
    "dodge_max_s": 3.0,
    "minigame_block_sec": 3.0,
    "poll_sec": 0.02,
    "key_hold_sec": 0.06,
    "battle_space_sec": 0.15,
    "enemy_space_sec": 4.0,
    "skill_space_sec": 0.45,
    "stuck_fix_sec": 3.0,
    "wait_space_sec": 0.5,
    "victory_gap_sec": 0.35,
    "victory_max_sec": 15.0,
    "skill_wait_sec": 0.45,
    "skill_retry_sec": 8.0,
    "chest_check_sec": 1.5,
    "label_read_sec": 0.5,
    "path_settle_sec": 0.6,
    "after_pick_sec": 1.2,
    "option_wait_sec": 0.9,
    "path_retry_sec": 3.0,
    "stuck_alert_sec": 180.0,
    "mouse_nudge_mid_sec": 0.01,
    "mouse_nudge_settle_sec": 0.04,
    "mouse_click_hold_sec": 0.04,
}

ADVANCED_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Minigames",
        [
            ("dodge_lead_s", "Dodge timing (sec)",
             "INCOMING! dodge, how early it presses before the marker reaches the middle of the white, raise it if it stops past the white, lower it if it stops before (on the blue at the near edge)"),
            ("press_lead_s", "Warrior timing (sec)",
             "Blade Focus, how early it presses before the marker reaches the middle of the zone, raise it if it stops past the zone, lower it if it stops before"),
            ("bard_lead_s", "Bard timing (sec)",
             "Encore, how early it presses before the note reaches the middle of the ring, raise it if it lands late, lower it if it lands early"),
            ("aim_bias", "Aim bias (zone widths)",
             "0 aims at the middle of the white zone, positive aims further along the way the marker is going, negative aims earlier"),
            ("min_speed", "Min marker speed",
             "The marker has to move at least this many bar widths a second before it presses, stops it from pressing on a marker that hasn't started yet"),
            ("meter_lead_s", "Fist / Archer timing (sec)",
             "Fist (Power Punch) and Archer (Power Shot), how early it presses before the power reaches the middle of the gold band, raise it if it stops above the middle, lower it if it stops below"),
            ("mage_lead_s", "Mage timing (sec)",
             "Arcane Sigils, it measures how fast each frame is closing (every one has its own speed) and presses this long before it closes onto the rune, raise it if it lands late, lower it if it lands early"),
            ("mage_close", "Mage closure (rune widths)",
             "How small the frame is when it counts as closed, in rune widths; the frame turns gold at about 1.55 and stops at about 1.15, lower it to press later in the gold, raise it to press earlier"),
            ("thief_delay_s", "Thief delay (sec)",
             "Shadow Cuts, waits this long after the reticle turns gold before pressing, raise it if it hits too early, lower it if it hits too late"),
            ("early_gap_sec", "Early Mode gap (sec)",
             "With Early Mode on it presses Space this often while the attack minigame is up"),
            ("press_hold_s", "Press hold (sec)",
             "How long Space stays down for each minigame press"),
            ("minigame_lost_s", "Minigame gone (sec)",
             "Once the bar or its marker is gone this long it stops playing and goes back to Space, if it is still there it just picks it up again on the next look"),
            ("minigame_max_s", "Minigame max (sec)",
             "Gives up on a minigame if it goes this long without a press, it starts again on every cut so a long Blade Focus with 5 cuts never runs out"),
            ("dodge_max_s", "Dodge max (sec)",
             "Gives up on a dodge after this long, a real dodge is over in about a second, if the dodge is still up it picks it straight back up"),
            ("minigame_block_sec", "Ignore stuck minigame (sec)",
             "If an attack minigame hits the max and is still on screen, it stops playing that one minigame for this long and pushes it along with Space, dodges and other minigames are never ignored"),
        ],
    ),
    (
        "Battle",
        [
            ("poll_sec", "Screen check every (sec)",
             "Pause between screen checks, this is how fast it spots a minigame starting, leave it low"),
            ("key_hold_sec", "Key hold (sec)",
             "How long Space stays down when it attacks, picks a foe, opens a chest or presses CONTINUE"),
            ("battle_space_sec", "Battle Space every (sec)",
             "On your turn (command menu or CHOOSE A FOE up) it presses Space this often, it never presses while a minigame box is up"),
            ("enemy_space_sec", "Enemy turn Space (sec)",
             "On the enemy's turn it stays quiet so a Space can never land in a dodge, it only presses once if nothing has happened for this long"),
            ("skill_space_sec", "Battle Space with a skill (sec)",
             "The same gap but for when Use a skill is on, it is slower on purpose so every turn gets read before it attacks"),
            ("stuck_fix_sec", "Menu stuck (sec)",
             "If your command menu or CHOOSE A FOE is still up after this long it nudges the mouse back onto ATTACK, then clicks, then clicks BACK"),
            ("wait_space_sec", "Waiting Space every (sec)",
             "Outside a fight, with nothing to click, it presses Space this often to get through dialogs"),
            ("victory_gap_sec", "VICTORY Space gap (sec)",
             "Once the VICTORY banner shows up it presses Space this often until the Choose Your Path screen appears"),
            ("victory_max_sec", "VICTORY give up (sec)",
             "How long it keeps pressing Space after a VICTORY before it goes back to the normal waiting Space"),
            ("skill_wait_sec", "Skill menu wait (sec)",
             "Wait after opening Skills before it reads the skill list, after each scroll of the list, and after it picks your skill before it checks the skill went through"),
            ("skill_retry_sec", "Skill retry (sec)",
             "How long it waits after going for a skill before it goes for one again"),
            ("chest_check_sec", "Chest check every (sec)",
             "How often it looks for CLICK TO OPEN! when it's not in a fight, it opens chests with Space"),
            ("label_read_sec", "Button label reread (sec)",
             "How long it trusts the words it read on a gold button before reading them again"),
        ],
    ),
    (
        "Choose your path",
        [
            ("path_settle_sec", "Path settle (sec)",
             "Wait after the Choose Your Path screen shows up before it reads the paths, raise it if it reads them while they're still sliding in"),
            ("after_pick_sec", "After pick (sec)",
             "Wait after clicking a path or TO BATTLE!"),
            ("option_wait_sec", "Choice wait (sec)",
             "Wait after clicking a choice in an event before it checks TO BATTLE! again"),
            ("path_retry_sec", "Path backup clicks (sec)",
             "If Choose Your Path is still up this long after a pick it clicks where the cards usually are, and if a box covers the cards it clicks where the confirm button would be"),
        ],
    ),
    (
        "Mouse click feel",
        [
            ("mouse_nudge_mid_sec", "Move nudge mid (sec)",
             "Timing for the little cursor nudge so Roblox actually registers the click"),
            ("mouse_nudge_settle_sec", "Move settle (sec)",
             "How long it waits after moving the cursor before clicking"),
            ("mouse_click_hold_sec", "Click hold (sec)",
             "How long a click stays down"),
        ],
    ),
    (
        "Webhook",
        [
            ("stuck_alert_sec", "Stuck alert (sec)",
             "Pings you if nothing happens for this long"),
        ],
    ),
]


def merge_advanced(raw: dict | None) -> dict[str, float]:
    out = dict(DEFAULT_ADVANCED)
    if isinstance(raw, dict):
        if "dodge_lead_s" not in raw and "press_lead_s" in raw:
            raw = dict(raw, dodge_lead_s=raw["press_lead_s"])
        for k, v in raw.items():
            if k in out:
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return out
