# Pixel Lineage Macro

1vtt's Pixel Lineage Macro (youtube.com/@1-vtt) with my changes:

- Turn 1 / Turn 2 ULTRA skills read reliably (split OCR rows joined, cooldown fallback to the next Turn skill)
- Clicks SKIP, and RETURN TO THE CASTLE or FOLLOW THE LIGHT (Options > "Follow the Light (acts 6-10)")
- Guard on/off toggle
- Discord loot alerts with a screenshot for chosen rarities (Webhook tab, e.g. `Mythic, Heirloom`)
- `debug/status.log` and debug pictures for anything it misses

## Setting it up on another PC

1. Install Python 3.10+ (64-bit) and tick "Add python.exe to PATH".
2. Copy `config.example.json` to `config.json` (keeps my click spots and settings).
3. Run `Setup.bat` once, then `Launch.bat`.
4. Paste your Discord webhook URL into the Webhook tab (it isn't stored in this repo).

Click spots and read areas are saved as fractions of the Roblox window, but re-check them with Select if the laptop's screen size is different.
