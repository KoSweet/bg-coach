"""Readable game timeline in the terminal (`bgcoach log`, `bgcoach log --live`)."""
from __future__ import annotations

import collections

from . import version as V
from .replay import Game

LABELS = {"HERO_POWER": "HERO PWR"}


class Printer:
    """Turns parser events into one readable line each."""

    def __init__(self, live: bool = False):
        self.db: V.CardDB | None = None
        self.live = live

    def n(self, cid) -> str:
        return self.db.name(cid) if self.db else (cid or "?")

    def cards(self, lst) -> str:
        return ", ".join(self.n(c["card_id"] if isinstance(c, dict) else c) for c in lst) or "-"

    def board(self, lst) -> str:
        return "  ".join(f"{self.n(c['card_id'])}{'*' if c.get('golden') else ''} {c['atk']}/{c['hp']}"
                         for c in lst) or "(empty)"

    def game_start(self, g: Game) -> None:
        self.db = V.card_db(g.build)
        p = V.patch_for_build(g.build)
        when = f"{g.start:%Y-%m-%d %H:%M}" if g.start else "?"
        print(f"\n▶ Game {when} · build {g.build} = patch {p.get('version')} ({p.get('name')})")

    def __call__(self, kind: str, d: dict) -> None:
        if kind == "round":
            print(f"\n── Round {d['round']} ".ljust(70, "─"))
        elif kind == "turn_start":
            arm = f"+{d['armor']}" if d.get("armor") else ""
            print(f"   {d['hp']}{arm} HP | Tier {d['tier']} | {d['gold']} gold")
            print(f"   board: {self.board(d.get('board') or [])}")
            if d.get("hand"):
                print(f"   hand:  {self.cards(d['hand'])}")
            print(f"   shop:  {self.cards(d.get('shop') or [])}")
        elif kind == "action":
            self.action(d)
        elif kind == "choice" and d["kind"] != "HERO_PICK":
            opts = " | ".join(self.n(c) for c in d["options"])
            print(f"   {d['kind']:<15} [{opts}] → {self.n(d['picked'])}")
        elif kind == "combat":
            res = d["result"]
            dmg = (f"took {d['damage_taken']}" if res == "LOSS" else
                   f"dealt {d['damage_dealt']}" if res == "WIN" else "no damage")
            a0 = f"+{d['armor_before']}" if d.get("armor_before") else ""
            a1 = f"+{d['armor_after']}" if d.get("armor_after") else ""
            print(f"   ⚔ vs {self.n(d.get('opp_hero'))}: {res} ({dmg}), HP {d['hp_before']}{a0} → {d['hp_after']}{a1}")
            if d.get("opp_board"):
                print(f"     their board: {self.board(d['opp_board'])}")
        elif kind == "tier" and self.live:
            print(f"   ▲ now Tier {d['tier']}")
        elif kind == "check_failed":
            print(f"   ✗ self-check failed: {d.get('action')} {self.n(d.get('card'))} — {d.get('expected')}")

    def action(self, a: dict) -> None:
        t = a["type"]
        if t == "CHOICE":
            return  # printed via the choice event
        if "shop" in a and t != "END_TURN":
            print(f"   shop: {self.cards(a['shop'])}")
        if t in ("BUY", "SELL"):
            stats = a.get("target_atk_hp") if t == "SELL" else None
            txt = self.n(a.get("target")) + (f" {stats}" if stats else "")
        elif t == "PLAY":
            txt = f"{self.n(a.get('card_id'))} → slot {a.get('position', '?')}"
        elif t == "MOVE":
            txt = f"{self.n(a.get('card_id'))} {a['from']}→{a['to']}"
        elif t == "LEVEL":
            txt = f"→ Tier {a['to_tier']}"
        elif t in ("CAST", "HERO_POWER", "ACTIVATE"):
            txt = self.n(a.get("card_id")) + (f" → {self.n(a['target'])}" if a.get("target") else "")
        else:
            txt = ""
        late = "  (not applied: turn ended)" if a.get("applied") is False else ""
        print(f"   [{a['gold']:>2}g T{a['tier']}] {LABELS.get(t, t.replace('_', ' ')):<9}{txt}{late}")

    def summary(self, g: Game) -> None:
        print("\n" + "═" * 70)
        when = f"{g.start:%Y-%m-%d %H:%M}" if g.start else "?"
        print(f" {when}  {g.game_type}  build {g.build}")
        if g.hero_offers:
            print(f" Heroes offered: {', '.join(self.n(h) for h in g.hero_offers)}")
        print(f" Hero: {self.n(g.hero)}   Anomaly: {self.n(g.anomaly) if g.anomaly else '-'}")
        print(f" PLACEMENT: {g.placement}   rounds: {len(g.turns)}   complete: {g.complete}")
        print(f" Final board: {self.board(g.final_board)}")
        c = collections.Counter(a["type"] for t in g.turns for a in t["actions"])
        print(" Actions: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
        print(f" Self-checks: {g.checks_ok} passed, {len(g.check_failures)} failed, {g.not_applied} not applied")
        print("═" * 70)
