"""Bridge to the combat simulator (optional: needs Node.js and `npm install` in sim/).

`build_battle` turns one recorded fight into the simulator's input (BgsBattleInfo). `simulate`
runs `sim/run.js`, a thin wrapper around Firestone's simulator installed locally in
sim/node_modules (licence "All rights reserved": personal local use, never redistributed here).

Validated against Bob's Buddy's logged odds (`bgcoach sim-check`): close for rounds 1-10, so
`whatif.py` only uses it there, and only for fights it reproduces. Uses:
  - positioning check: same boards, other orders of your minions -> win % per order
  - buy what-if: your fight board with the bought card swapped for the alternative
Without the simulator everything else works; those checks are simply missing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[2] / "sim"
KW_FIELDS = {"TAUNT": "taunt", "DIVINE_SHIELD": "divineShield", "REBORN": "reborn", "WINDFURY": "windfury",
             "VENOMOUS": "venomous", "POISONOUS": "poisonous", "STEALTH": "stealth", "CLEAVE": "cleave"}


MECHANIC_KW = {"TAUNT", "DIVINE_SHIELD", "REBORN", "WINDFURY", "VENOMOUS", "POISONOUS", "STEALTH", "CLEAVE"}


def base_keywords(card_id: str) -> list[str]:
    """Printed keywords of a card (for fights recorded before keywords were captured)."""
    from . import version as V
    mech = V.card_db(V.current_bg_meta_build()).get(card_id).get("mechanics") or []
    return [k for k in mech if k in MECHANIC_KW]


def _entity(m: dict, eid: int, friendly: bool) -> dict:
    e = {"entityId": eid, "cardId": m["card_id"], "attack": m.get("atk") or 0,
         "health": max(1, m.get("hp") or 1), "friendly": friendly}
    kws = m["kw"] if "kw" in m else base_keywords(m["card_id"])
    for k in kws or []:
        if k in KW_FIELDS:
            e[KW_FIELDS[k]] = True
    return e


def build_battle(combat: dict, my_hero: str, tier: int, my_board: list[dict] | None = None,
                 sims: int = 1000) -> dict:
    """Simulator input for one recorded fight. `my_board` overrides your board (for what-ifs)."""
    mine = my_board if my_board is not None else combat.get("my_board") or []
    hp = (combat.get("hp_before") or 0) + (combat.get("armor_before") or 0)

    def player(hero, hp_left, friendly):
        return {"cardId": hero or "TB_BaconShop_HERO_01", "hpLeft": hp_left or 30, "tavernTier": tier,
                "heroPowers": [], "questEntities": [], "friendly": friendly}

    return {
        "playerBoard": {"player": player(my_hero, hp, True),
                        "board": [_entity(m, 1000 + i, True) for i, m in enumerate(mine)]},
        "opponentBoard": {"player": player(combat.get("opp_hero"), 30, False),
                          "board": [_entity(m, 2000 + i, False) for i, m in enumerate(combat.get("opp_board") or [])]},
        "options": {"numberOfSimulations": sims, "skipInfoLogs": True, "maxAcceptableDuration": 3000},
        "gameState": {"currentTurn": combat.get("round") or 1},
    }


def available() -> bool:
    return shutil.which("node") is not None and (SIM_DIR / "node_modules" / "@firestone-hs").exists()


def simulate(battles: dict[str, dict], timeout: int = 300) -> dict[str, dict]:
    """Run battles {id: BgsBattleInfo} -> {id: {win, tie, loss, ...}}."""
    if not available():
        raise RuntimeError("combat simulator not installed (sim/node_modules)")
    payload = "\n".join(json.dumps({"id": k, "battle": v}) for k, v in battles.items()) + "\n"
    r = subprocess.run(["node", str(SIM_DIR / "run.js")], input=payload, capture_output=True, text=True,
                       timeout=timeout, cwd=str(SIM_DIR))
    out = {}
    for line in r.stdout.splitlines():
        if line.startswith("{"):  # skip library chatter (e.g. "fetch with retries ...")
            d = json.loads(line)
            out[d.pop("id")] = d
    return out
