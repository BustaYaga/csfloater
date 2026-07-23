"""
Terminal color system.

Two colour tables:
  RARITY_COLORS  - CS2 rarity tier -> hex colour. Left as None on purpose -
                   fill these in yourself with the exact hex codes you want.
  MESSAGE_COLORS - log/message categories (WARNING, TERMINATED, STRATA, ...) -
                   sensible defaults are set, override any of them freely.

Usage:
    from terminal_colors import cprint, colorize, enable_windows_ansi
    enable_windows_ansi()  # call once, at program start

    cprint("Warning: ...", "WARNING")
    print(colorize("Restricted", RARITY_COLORS["Restricted"]))
"""
import os

RESET = "\033[0m"
BOLD = "\033[1m"


def enable_windows_ansi():
    """
    Windows' classic console doesn't render ANSI escape codes by default.
    This is the standard no-dependency trick to turn on VT100 processing -
    call once at the very start of your entry-point script.
    """
    if os.name == "nt":
        os.system("")


def hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def colorize(text: str, hex_color: str, bold: bool = False) -> str:
    """Wrap text in a 24-bit ANSI colour code. Falls back to plain text if
    hex_color is None (i.e. not filled in yet)."""
    if not hex_color:
        return text
    r, g, b = hex_to_rgb(hex_color)
    prefix = f"{BOLD if bold else ''}\033[38;2;{r};{g};{b}m"
    return f"{prefix}{text}{RESET}"


# --- CS2 rarity tiers -------------------------------------------------
RARITY_COLORS = {
    "Consumer Grade": "#FFFFFF",      # White
    "Industrial Grade": "#ADD8E6",    # Light Blue
    "Mil-Spec Grade": "#0000FF",      # Blue (Rare)
    "Restricted": "#854085",          # Purple (Mythical)
    "Classified": "#FF54A9",          # Pink (Legendary)
    "Covert": "#CE2B15",              # Red (Ancient)
    "Contraband": "#FFA500",          # Orange
    "Extraordinary": "#FFD700",       # Gold (Knives / Gloves, Exceedingly Rare)
}

# --- Message/log categories --------------------------------------------
# Defaults set below - change any hex code to taste.
MESSAGE_COLORS = {
    "WARNING": "#FF3B30",       # red, as requested
    "TERMINATED": "#FF0000",    # red, bold applied separately
    "STRATA": "#00BFFF",        # cyan-ish, real-time per-stratum lines
    "SUCCESS": "#32CD32",       # green, session summaries
    "INFO": None,               # plain
    "ERROR": "#FF0000",
}

MESSAGE_BOLD = {
    "TERMINATED": True,
    "WARNING": True,
}

MESSAGE_SYMBOLS = {
    "WARNING": "!",
    "TERMINATED": "X",
    "STRATA": ">",
    "SUCCESS": "OK",
    "INFO": "*",
    "ERROR": "X",
}


def cprint(text: str, category: str = "INFO"):
    """Print text coloured according to MESSAGE_COLORS[category], prefixed
    with a consistent symbol so message types are scannable at a glance."""
    color = MESSAGE_COLORS.get(category)
    bold = MESSAGE_BOLD.get(category, False)
    symbol = MESSAGE_SYMBOLS.get(category, "")
    prefix = f"[{symbol}] " if symbol else ""
    print(colorize(f"{prefix}{text}", color, bold=bold))


def rarity_text(name: str, rarity: str) -> str:
    """Colour `name` using the colour registered for `rarity`."""
    return colorize(name, RARITY_COLORS.get(rarity), bold=False)


def divider(char: str = "-", width: int = 64):
    print(char * width)


def print_banner(title: str, lines: list, color: str = None):
    """Boxed section header, e.g. for run-start / run-summary blocks."""
    width = max(64, len(title) + 4)
    divider("=", width)
    print(colorize(f" {title}", color, bold=True))
    divider("=", width)
    for line in lines:
        print(f"  {line}")
    divider("=", width)


def format_strata_line(index: int, total: int, full_skin_name: str, wear: str, rarity: str) -> str:
    """
    Builds a strata progress line where ONLY the skin name itself is
    coloured by rarity - the weapon prefix, brackets, and wear suffix stay
    in the terminal's default colour.

    e.g. "[18/273] Searching: M4A4 | Asiimov (Minimal Wear)"
                                     ^^^^^^^ only this part is coloured
    """
    if " | " in full_skin_name:
        weapon_part, skin_part = full_skin_name.split(" | ", 1)
        weapon_prefix = f"{weapon_part} | "
    else:
        weapon_prefix, skin_part = "", full_skin_name

    colored_skin = colorize(skin_part, RARITY_COLORS.get(rarity))
    return f"[{index + 1}/{total}] Searching: {weapon_prefix}{colored_skin} ({wear})"