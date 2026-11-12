"""From moments to lessons: which one matters most, said in one plain sentence, plus a habit to
take into the next game. Used by the game page, the after-game card, the overlay and Improve, so
they all agree on "the one thing".

Ranking is by kind first, then by size within the kind, never by a made-up common score: win-chance
points, places and HP are different currencies. A concrete better line you could have played comes
before an order change, before a risky level-up, before the hero pick, before a general habit, and
a fight you lost (a diagnosis, not an action) comes last.
"""
from __future__ import annotations

PRIORITY = {"counter": 0, "position": 1, "level": 2, "hero": 3, "rule": 4, "fight": 5}

HABITS = {
    "counter:skip_level": "Before you level, look at the shop once more: is there a minion that wins your next fight?",
    "counter:instead": "Before each buy, ask which minion in this shop helps your next fight most, not only which is best.",
    "counter:spare": "Don't end a turn with gold that could have bought a minion for the next fight.",
    "position": "Give positioning five seconds before the turn ends: big attackers first early, a lone taunt last, "
                "your biggest minion away from venom.",
    "level": "Before levelling, ask: will I drop below 15 HP if I lose this fight? If yes, stabilize first.",
    "hero": "At hero pick, compare top-4 rate, starting health and this lobby's tribes, not only the hero you like.",
    "fight:highroll": "Watch the next-opponent card while you shop: against a highroller at low HP, buy fighting "
                      "power instead of levelling.",
    "fight": "When your board falls behind the average for your hero, stabilize (buy stats) before you level.",
}


def size(d: dict) -> float:
    k = d["kind"]
    if k in ("counter", "position"):
        return d.get("gain") or 0
    if k in ("fight", "level"):
        return d.get("damage") or 0
    return (d.get("diff") or 0) * 100


def impact(d: dict) -> str:
    """What it cost, in its own unit (no +/- signs: everything here is a cost)."""
    k = d["kind"]
    if k in ("counter", "position"):
        return f"{size(d):.0f} pts"  # win % + half the ties
    if k in ("fight", "level"):
        return f"{d.get('damage') or 0} HP"
    if k in ("hero", "buy", "pick"):
        return f"{d.get('diff') or 0:.2f} places"
    return "habit"


def habit(d: dict) -> str | None:
    k = d["kind"]
    if k == "counter":
        return HABITS.get(f"counter:{d.get('line_kind')}")
    if k == "rule":
        from .playbook import RULES
        return RULES.get(d.get("rule"), (None, None, None))[2]
    if k == "fight":
        return HABITS["fight:highroll"] if d.get("highroll") else HABITS["fight"]
    return HABITS.get(k)


def odds(x: dict) -> str:
    """'37% win, 5% loss' (the rest are ties): both ends, so a sure loss turned into a tie reads right."""
    return f"{x['win']:.0f}% win, {x['loss']:.0f}% loss"


def headline(d: dict, name) -> str:
    """One plain sentence (no markup), for the after-game card and the overlay."""
    k, r = d["kind"], d.get("round")
    if k == "counter":
        return f"Round {r}: {d['what']}: that fight goes from {odds(d['base'])} to {odds(d['new'])} (simulated)."
    if k == "position":
        return (f"Round {r}: the same minions in another order win {d['best_win']:.0f}% instead of "
                f"{d['base_win']:.0f}% (simulated).")
    if k == "level":
        return f"Round {r}: {d.get('calc', '')}"
    if k == "hero":
        why = (d.get("why") or [""])[0]
        return f"Hero: {name(d.get('better'))} was the better pick. {why}".strip()
    if k == "rule":
        return f"Round {r}: {d.get('title')}. {d.get('what')}"
    if k == "fight":
        s = f"Round {r}: lost {d.get('damage')} HP to {name(d.get('opp'))}"
        if d.get("highroll") and d.get("opp_ratio"):
            s += f", a highroll ({d['opp_ratio']:.1f}× the average for their hero)"
        if d.get("no_counter"):
            s += ". Nothing in your shop that turn would have won it"
        return s + "."
    return d.get("calc") or ""


def annotate(moments: list[dict], name) -> list[dict]:
    """Rank moments and add headline / impact / habit / rank to each (in place, returns the ranked list)."""
    ranked = sorted(moments, key=lambda d: (PRIORITY.get(d["kind"], 9), -size(d)))
    for i, d in enumerate(ranked):
        d["rank"] = i
        d["impact"] = impact(d)
        d["habit"] = habit(d)
        d["headline"] = headline(d, name)
    return ranked


def hero_moment(a: dict, hero: str | None) -> dict | None:
    """The hero pick as a moment (only when another hero was clearly better)."""
    hp = a.get("hero_pick") or {}
    if not hp.get("clear"):
        return None
    return {"kind": "hero", "round": 0, "you": hero, "you_val": hp["picked_avg"], "better": hp["best"],
            "better_val": hp["best_avg"], "diff": hp["loss"], "why": hp.get("why") or [],
            "calc": f"Average placement at your MMR: {hp['picked_avg']} for your hero, {hp['best_avg']} for the best "
                    f"one offered. Chance alone could explain up to {hp['noise']} places."}


def for_game(g: dict, a: dict, bracket: int, db) -> list[dict]:
    """Every moment of one game, ranked and annotated (the hero pick included)."""
    from .decisions import all_decisions
    ms = all_decisions(g, bracket, a["strength"], a.get("lobby"))
    hm = hero_moment(a, g.get("hero"))
    if hm:
        ms.append(hm)
    return annotate(ms, db.name)
