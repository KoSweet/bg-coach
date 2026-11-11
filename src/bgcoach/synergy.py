"""How well a card fits what you're building right now.

Card statistics say how a card does on average; they don't know your board. Before the app suggests
"take B instead of A", B must fit your build at least as well as A. Fit comes from:
  - tribes: your MAIN tribe (most minions) vs a side tribe vs a tribe you don't play
  - themes in the card's text that match your board (Battlecry, Deathrattle, Divine Shield, ...)
  - themes that match how you actually play this game: spells cast on your minions, Discovers,
    golden minions (e.g. Balinda Stonehearth needs spells; Hooktusk needs Pirates and Discovers)

Levels: 3 = fits your build, 2 = neutral / flexible, 1 = side synergy, 0 = off your build.
"""
from __future__ import annotations

import re
from collections import Counter

from . import version as V

# text patterns -> theme (applied to the card's own text, lower-cased, tags stripped)
THEME_PATTERNS = {
    "spell": r"\bspells?\b",
    "battlecry": r"\bbattlecr",
    "deathrattle": r"\bdeathrattle",
    "discover": r"\bdiscover",
    "golden": r"\bgolden\b",
    "divine_shield": r"\bdivine shield",
    "end_of_turn": r"\bend of (your )?turn",
    "avenge": r"\bavenge\b",
    "blood_gem": r"\bblood gem",
    "taunt": r"\btaunt\b",
    "gold": r"\bgold\b|\brefresh",
}
# board mechanics that count toward a theme (a Deathrattle minion supports "deathrattle" synergy)
MECH_THEME = {"BATTLECRY": "battlecry", "DEATHRATTLE": "deathrattle", "DIVINE_SHIELD": "divine_shield",
              "TAUNT": "taunt", "AVENGE": "avenge", "END_OF_TURN": "end_of_turn"}
TRIBE_NAMES = {"MECHANICAL": "Mech", "MURLOC": "Murloc", "DEMON": "Demon", "BEAST": "Beast", "DRAGON": "Dragon",
               "PIRATE": "Pirate", "ELEMENTAL": "Elemental", "QUILBOAR": "Quilboar", "NAGA": "Naga", "UNDEAD": "Undead"}


def _db():
    return V.card_db(V.current_bg_meta_build())


def _text(card: dict) -> str:
    return re.sub(r"<[^>]+>|\[x\]", "", (card.get("text") or "")).lower()


def tribes_of(card: dict) -> list[str]:
    r = card.get("races") or ([card["race"]] if card.get("race") else [])
    return [x for x in r if x and x != "INVALID"]


def themes_of(card: dict) -> set[str]:
    t = _text(card)
    return {name for name, pat in THEME_PATTERNS.items() if re.search(pat, t)}


def context(board_ids: list[str], history: dict | None = None) -> dict:
    """Your build at a moment: tribe counts (main = largest), board themes, and how you've played."""
    db = _db()
    tribes, themes = Counter(), Counter()
    for cid in board_ids:
        c = db.get(cid)
        for tr in tribes_of(c):
            if tr == "ALL":
                for k in TRIBE_NAMES:  # an all-tribe minion counts for every tribe
                    tribes[k] += 0.5
            else:
                tribes[tr] += 1
        for m in c.get("mechanics") or []:
            if m in MECH_THEME:
                themes[MECH_THEME[m]] += 1
    main = None
    if tribes:
        top, n = tribes.most_common(1)[0]
        if n >= 2:
            main = top
    h = history or {}
    return {"tribes": tribes, "main": main, "themes": themes,
            "spells_on_minions": h.get("spells_on_minions", 0), "discovers": h.get("discovers", 0),
            "goldens": h.get("goldens", 0)}


def history_until(g: dict, rnd: int, before_line: int | None = None) -> dict:
    """How you've played so far this game (actions before round `rnd` / before a log line)."""
    spells = discovers = goldens = 0
    for t in g.get("turns") or []:
        if t["round"] > rnd:
            break
        for a in t.get("actions") or []:
            if before_line and a.get("line") and a["line"] >= before_line:
                break
            if a["type"] == "CAST" and a.get("target"):
                spells += 1
            elif a["type"] == "CHOICE" and a.get("kind") in ("DISCOVER", "TRIPLE_DISCOVER", "DARK_GIFT_PICK"):
                discovers += 1
            elif a["type"] == "CHOICE" and a.get("kind") == "TRIPLE_DISCOVER":
                goldens += 1
        if t["round"] == rnd and before_line is None:
            break
    golden_now = 0
    return {"spells_on_minions": spells, "discovers": discovers, "goldens": goldens + golden_now}


GENERIC_THEMES = {"spell", "gold"}          # Tavern spells / gold exist in every game for everyone
BOARD_THEMES = ("battlecry", "deathrattle", "divine_shield", "end_of_turn", "avenge", "taunt")


def fit(card_id: str, ctx: dict) -> tuple[int, str]:
    """(level, reason): 3 fits your build, 2 neutral/flexible, 1 side synergy, 0 off your build."""
    c = _db().get(card_id)
    all_tribe = "ALL" in tribes_of(c)
    trs = [t for t in tribes_of(c) if t != "ALL"]
    th = themes_of(c)

    theme: list[tuple[int, str]] = []
    if "spell" in th:
        s = ctx["spells_on_minions"]
        theme.append((3 if s >= 4 else 2, f"spell engine (you've cast {s} on your minions)"))
    if "gold" in th:
        theme.append((2, "gold/refresh engine"))
    if "discover" in th:
        d = ctx["discovers"]
        theme.append((3 if d >= 5 else 2 if d >= 3 else 1, f"Discover synergy ({d} so far)"))
    if "golden" in th:
        gd = ctx["goldens"]
        theme.append((3 if gd >= 3 else 2 if gd >= 1 else 1, f"golden synergy ({gd} triple(s) so far)"))
    for t_ in BOARD_THEMES:
        if t_ in th:
            n = ctx["themes"].get(t_, 0)
            theme.append((3 if n >= 3 else 2 if n >= 2 else 1, f"{t_.replace('_', ' ')} synergy ({n} on your board)"))
    best_theme = max(theme, key=lambda r: r[0]) if theme else None

    if all_tribe:
        return 3, "works with every tribe"
    if not trs:  # no tribe: as good as its best theme, otherwise a flexible card
        return best_theme if best_theme else (2, "no tribe: fits any board")

    # tribe card: the tribe decides, a strongly supported theme can lift it to "flexible" at most
    tribe_levels = []
    for tr in trs:
        n = ctx["tribes"].get(tr, 0)
        name = TRIBE_NAMES.get(tr, tr.title())
        if tr == ctx["main"]:
            tribe_levels.append((3, f"{name}, your main tribe ({n:g})"))
        elif n >= 2:
            main = TRIBE_NAMES.get(ctx["main"], "-")
            tribe_levels.append((1, f"{name}: a side tribe ({n:g}); your main is {main}"))
        else:
            tribe_levels.append((0, f"{name}: you play {n:g}"))
    level, why = max(tribe_levels, key=lambda r: r[0])
    if best_theme and best_theme[0] == 3 and level < 2:
        return 2, f"{why}, but {best_theme[1]}"
    return level, why


LEVEL_WORD = {3: "fits your build", 2: "neutral / flexible", 1: "side synergy", 0: "off your build"}


def best_option(options: list[str], values: dict, ctx: dict) -> tuple[str | None, dict]:
    """Best option = lowest average placement among the options that fit your build best."""
    fits = {o: fit(o, ctx) for o in options}
    known = [o for o in options if values.get(o) is not None]
    if not known:
        return None, fits
    top = max(fits[o][0] for o in known)
    best = min((o for o in known if fits[o][0] == top), key=lambda o: values[o])
    return best, fits
