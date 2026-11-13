"""Battlegrounds Power.log -> structured game record.

Design rules (lessons from the old project):
- Read ONLY the `GameState.*` stream (PowerTaskList repeats the same data later).
- Decisions come from the authoritative option protocol, never from zone heuristics:
  `DebugPrintOptions` (everything legal) + `SendOption` (what I chose),
  `DebugPrintEntityChoices` + `DebugPrintEntitiesChosen` (discovers / hero pick / trinkets).
- The second player slot is Bob during recruit and the combat opponent during combat.

The parser is incremental (`feed(line)`), so the same code drives replay and live tailing.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

LINE_RE = re.compile(r"^[DWIE] (\d\d):(\d\d):(\d\d)\.(\d+) GameState\.(\w+)\(\) - (.*)$")
REF_RE = re.compile(r"\[entityName=.*? id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\S*) player=(\d+)\]")
TAG_CHANGE_RE = re.compile(r"^TAG_CHANGE Entity=(.+?) tag=(\S+) value=(\S*)")
FULL_RE = re.compile(r"^FULL_ENTITY - (?:Creating|Updating) ID=(\d+) CardID=(\S*)")
SHOW_RE = re.compile(r"^(?:SHOW|CHANGE)_ENTITY - Updating Entity=(.+?) CardID=(\S*)\s*$")
HIDE_RE = re.compile(r"^HIDE_ENTITY - Entity=(.+?) tag=(\S+) value=(\S*)")
TAG_RE = re.compile(r"^tag=(\S+) value=(\S*)")
PLAYER_RE = re.compile(r"^Player EntityID=(\d+) PlayerID=(\d+) GameAccountId=\[hi=(\d+) lo=(\d+)\]")
GAME_ENTITY_RE = re.compile(r"^GameEntity EntityID=(\d+)")
BLOCK_RE = re.compile(r"^BLOCK_START BlockType=(\w+) Entity=(.+?) EffectCardId=")
OPTION_RE = re.compile(r"^option (\d+) type=(\w+) mainEntity=(.*?) error=(\S*) errorParam=")
SEND_OPTION_RE = re.compile(
    r"selectedOption=(-?\d+) selectedSubOption=(-?\d+) selectedTarget=(-?\d+) selectedPosition=(-?\d+)")
CHOICES_HDR_RE = re.compile(r"^id=(\d+) Player=(.+?) TaskList=\S* ChoiceType=(\w+)")
CHOSEN_HDR_RE = re.compile(r"^id=(\d+) Player=(.+?) EntitiesCount=")
ENTITIES_RE = re.compile(r"^Entities\[\d+\]=(.*)$")

BUTTONS = {
    "TB_BaconShop_DragBuy": "BUY",
    "TB_BaconShop_DragBuy_Spell": "BUY",
    "TB_BaconShop_DragSell": "SELL",
    "TB_BaconShop_8p_Reroll_Button": "REFRESH",
    "TB_BaconShopLockAll_Button": "FREEZE",
    "BG36_Button_DarkGift": "DARK_GIFT",
    "TB_BaconShopBob": "BOB",
}
# Bump when the game record gains or changes fields: `bgcoach import` (and the app) then re-parse
# every archived log once, so older games get them too. 2 = lobby, end-of-turn shop.
# 3 = locked hero offers; fights won in Duos (read from the enemy team's health).
# 4 = the damage cap of each fight (5 / 10 / 15 early in the game, then off).
PARSER_VERSION = 4
SHOP_TYPES = {"MINION", "BATTLEGROUND_SPELL", "SPELL"}
KEYWORD_TAGS = ("TAUNT", "DIVINE_SHIELD", "REBORN", "WINDFURY", "VENOMOUS", "POISONOUS", "STEALTH", "CLEAVE")


def norm_hero(card_id: str | None) -> str:
    return re.sub(r"_SKIN_\w+$", "", card_id or "")


@dataclass
class Entity:
    id: int
    card_id: str = ""
    tags: dict = field(default_factory=dict)

    def tag(self, name: str, default=None):
        return self.tags.get(name, default)

    def int(self, name: str, default: int = 0) -> int:
        v = self.tags.get(name)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default


@dataclass
class Game:
    start: dt.datetime | None = None
    build: int | None = None
    game_type: str | None = None
    me_player_id: int | None = None  # in-game player id (e.g. 7)
    me_entity: int | None = None
    other_entity: int | None = None
    me_name: str | None = None
    account: int | None = None      # Battle.net account (GameAccountId lo) of the log owner
    hero_offers: list = field(default_factory=list)
    hero_locked: list = field(default_factory=list)  # offers you couldn't pick (without the Tavern Pass:
    hero: str | None = None                           # the outer two of four)
    anomaly: str | None = None
    turns: list = field(default_factory=list)       # one dict per round
    combats: list = field(default_factory=list)
    choices: list = field(default_factory=list)
    final_board: list = field(default_factory=list)
    placement: int | None = None
    end: dt.datetime | None = None
    complete: bool = False
    errors: list = field(default_factory=list)   # parse errors inside this game
    checks_ok: int = 0                           # self-checks that passed (action had its effect)
    not_applied: int = 0                         # actions clicked too late (turn ended first)
    check_failures: list = field(default_factory=list)
    source: str | None = None                    # log file it came from

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["start"] = self.start.isoformat() if self.start else None
        d["end"] = self.end.isoformat() if self.end else None
        d.pop("me_name", None)  # private
        return d


class Replay:
    """Feed Power.log lines; completed games are passed to `on_game` (and kept in `.games`)."""

    def __init__(self, base_date: dt.date | None = None,
                 on_event: Callable[[str, dict], None] | None = None,
                 on_game: Callable[[Game], None] | None = None,
                 on_game_start: Callable[[Game], None] | None = None):
        """on_event(kind, data) for every event; on_game(game) when a game ends;
        on_game_start(game) as soon as a new game's build number is known."""
        self.base_date = base_date or dt.date.today()
        self.on_event = on_event or (lambda kind, data: None)
        self.on_game = on_game
        self.on_game_start = on_game_start
        self.games: list[Game] = []
        self.errors: list[dict] = []
        self.line_no = 0
        self._day_offset = 0
        self._last_secs = None
        self._reset()

    # ------------------------------------------------------------ state
    def _reset(self):
        self.g: Game | None = None
        self.ents: dict[int, Entity] = {}
        self.game_entity: int | None = None
        self.player_ids: dict[int, int] = {}      # player_id -> entity id
        self.player_names: dict[str, int] = {}    # name -> player_id
        self.ctx: Entity | None = None
        self.options: dict[int, dict] = {}
        self.pending_choice: dict | None = None
        self.choices: dict[int, dict] = {}
        self.chosen_id: int | None = None
        self.turn = 0
        self.cur_turn: dict | None = None
        self.cur_combat: dict | None = None
        self.last_shop: list | None = None
        self.now: dt.datetime | None = None
        self._complete_at: dt.datetime | None = None
        self.my_hero_ids: set[int] = set()
        self.placement_locked = False
        self.pending_checks: list[tuple[dict, str, Callable[[], bool]]] = []

    # ------------------------------------------------------------ helpers
    def _ent(self, eid: int) -> Entity:
        e = self.ents.get(eid)
        if e is None:
            e = self.ents[eid] = Entity(eid)
        return e

    def _ref(self, s: str) -> int | None:
        s = s.strip()
        if not s:
            return None
        if s.startswith("[entityName="):
            m = REF_RE.search(s)
            if m:
                eid = int(m.group(1))
                e = self._ent(eid)
                if m.group(4) and not e.card_id:
                    e.card_id = m.group(4)
                return eid
            return None
        if s.isdigit():
            return int(s)
        if s == "GameEntity":
            return self.game_entity
        # bare player name
        pid = self.player_names.get(s)
        if pid is not None and pid in self.player_ids:
            return self.player_ids[pid]
        if self.g and s != self.g.me_name:
            return self.g.other_entity
        return self.g.me_entity if self.g else None

    def _me(self) -> Entity | None:
        return self.ents.get(self.g.me_entity) if self.g and self.g.me_entity else None

    def _my_hero(self) -> Entity | None:
        me = self._me()
        if me is None:
            return None
        hid = me.int("HERO_ENTITY", 0)
        return self.ents.get(hid) if hid else None

    def _hero_of(self, player_ent: int | None) -> Entity | None:
        p = self.ents.get(player_ent) if player_ent else None
        if not p:
            return None
        return self.ents.get(p.int("HERO_ENTITY", 0))

    def _gold(self) -> int:
        me = self._me()
        if not me:
            return 0
        return me.int("RESOURCES") + me.int("TEMP_RESOURCES") - me.int("RESOURCES_USED")

    def _hp(self, hero: Entity | None) -> int | None:
        if not hero:
            return None
        return hero.int("HEALTH") - hero.int("DAMAGE")

    def _ehp(self, hero: Entity | None) -> int | None:
        """Effective HP = health + armor."""
        hp = self._hp(hero)
        return None if hp is None else hp + hero.int("ARMOR")

    def _zone(self, controller_pid: int | None, zone: str, types=("MINION",)) -> list[dict]:
        if controller_pid is None:
            return []
        out = []
        for e in self.ents.values():
            if e.int("CONTROLLER", -1) == controller_pid and e.tag("ZONE") == zone \
                    and e.tag("CARDTYPE") in types:
                out.append(e)
        out.sort(key=lambda e: e.int("ZONE_POSITION"))
        return [self._card(e) for e in out]

    def _card(self, e: Entity) -> dict:
        d = {"id": e.id, "card_id": e.card_id, "atk": e.int("ATK"), "hp": e.int("HEALTH") - e.int("DAMAGE"),
             "pos": e.int("ZONE_POSITION")}
        if e.tag("CARDTYPE") != "MINION":
            d["type"] = e.tag("CARDTYPE")
        if e.int("PREMIUM") or e.int("BACON_TRIPLED_BASE_MINION_ID"):
            d["golden"] = True
        kw = [k for k in KEYWORD_TAGS if e.int(k)]
        if e.int("WINDFURY") >= 3:  # mega-windfury
            kw.append("MEGA_WINDFURY")
        if kw:
            d["kw"] = kw  # keywords at this moment (incl. gained ones): needed to simulate combats
        return d

    def _other_pid(self) -> int | None:
        p = self.ents.get(self.g.other_entity) if self.g and self.g.other_entity else None
        return p.int("PLAYER_ID", -1) if p else None

    def board(self):
        return self._zone(self.g.me_player_id, "PLAY") if self.g else []

    def hand(self):
        return self._zone(self.g.me_player_id, "HAND", types=("MINION", "SPELL", "BATTLEGROUND_SPELL")) if self.g else []

    def shop(self):
        return self._zone(self._other_pid(), "PLAY", types=tuple(SHOP_TYPES)) if self.g else []

    def tier(self) -> int:
        h = self._my_hero()
        return h.int("PLAYER_TECH_LEVEL", 1) if h else 1

    def lobby(self) -> dict[str, dict]:
        """The leaderboard right now (what the game shows you): lobby slot → hero, health + armor,
        tier, triples, place. Keys are strings so the record survives a JSON round trip."""
        best: dict[int, Entity] = {}
        for e in self.ents.values():
            if e.tag("CARDTYPE") != "HERO" or not e.int("PLAYER_ID") or not e.int("PLAYER_LEADERBOARD_PLACE"):
                continue
            pid = e.int("PLAYER_ID")
            if pid not in best or e.id > best[pid].id:  # the newest entity is the current one
                best[pid] = e
        return {str(pid): {"hero": e.card_id, "hp": self._ehp(e), "tier": e.int("PLAYER_TECH_LEVEL", 1),
                           "triples": e.int("PLAYER_TRIPLES"), "place": e.int("PLAYER_LEADERBOARD_PLACE")}
                for pid, e in sorted(best.items())}

    def my_lobby_id(self) -> int | None:
        h = self._my_hero()
        return h.int("PLAYER_ID") or None if h else None

    def _emit(self, kind: str, data: dict):
        self.on_event(kind, data)

    # ------------------------------------------------------------ time
    def _time(self, h, m, s, frac) -> dt.datetime:
        secs = int(h) * 3600 + int(m) * 60 + int(s)
        if self._last_secs is not None and secs < self._last_secs - 3600:
            self._day_offset += 1  # crossed midnight
        self._last_secs = secs
        base = dt.datetime.combine(self.base_date, dt.time()) + dt.timedelta(days=self._day_offset)
        return base + dt.timedelta(seconds=secs, microseconds=int(frac[:6].ljust(6, "0")))

    # ------------------------------------------------------------ main entry
    def feed(self, line: str) -> None:
        """Process one log line. Never raises: a failure is recorded in `.errors` (with the line
        number and text) and parsing continues, so one odd line can't lose a whole session."""
        self.line_no += 1
        if "GameState." not in line:
            return
        try:
            self._feed(line)
        except Exception as e:
            import traceback
            err = {"line_no": self.line_no, "line": line.rstrip()[:400], "error": repr(e),
                   "traceback": traceback.format_exc(limit=4),
                   "round": (self.turn + 1) // 2 if self.g else None}
            self.errors.append(err)
            if self.g is not None:
                self.g.errors.append({k: err[k] for k in ("line_no", "error", "round")})
            self.on_event("parse_error", err)

    def _feed(self, line: str) -> None:
        m = LINE_RE.match(line.rstrip("\r\n"))
        if not m:
            return
        self.now = self._time(*m.group(1, 2, 3, 4))
        # Final leaderboard tags arrive just AFTER STATE=COMPLETE; close the game a moment later.
        if self._complete_at is not None and (self.now - self._complete_at).total_seconds() > 3:
            self._end_game(complete=True)
        method, body = m.group(5), m.group(6).strip()
        if method == "DebugPrintPower":
            self._power(body)
        elif method == "DebugPrintGame":
            self._game_hdr(body)
        elif method == "DebugPrintOptions":
            self._options(body)
        elif method == "SendOption":
            self._send_option(body)
        elif method == "DebugPrintEntityChoices":
            self._choices(body)
        elif method == "DebugPrintEntitiesChosen":
            self._chosen(body)

    def feed_all(self, lines: Iterable[str]) -> list[Game]:
        for line in lines:
            self.feed(line)
        self.finish()
        return self.games

    def flush_if_idle(self):
        """Live mode: close a completed game when the log goes quiet (the caller decides when)."""
        if self._complete_at is not None and self.g is not None:
            self._end_game(complete=True)

    def finish(self):
        if self.g:
            self._end_game(complete=self.g.complete)

    # ------------------------------------------------------------ header
    def _game_hdr(self, body: str):
        if not self.g:
            return
        if body.startswith("BuildNumber="):
            self.g.build = int(body.split("=", 1)[1])
            if self.on_game_start:
                self.on_game_start(self.g)
        elif body.startswith("GameType="):
            self.g.game_type = body.split("=", 1)[1]
        elif body.startswith("PlayerID="):
            m = re.match(r"PlayerID=(\d+), PlayerName=(.*)$", body)
            if m:
                pid, name = int(m.group(1)), m.group(2).strip()
                self.player_names[name] = pid
                if pid == self.g.me_player_id:
                    self.g.me_name = name

    # ------------------------------------------------------------ power
    def _power(self, body: str):
        if body.startswith("tag="):
            m = TAG_RE.match(body)
            if m and self.ctx is not None:
                self.ctx.tags[m.group(1)] = m.group(2)
            return
        self.ctx = None
        if body.startswith("TAG_CHANGE"):
            m = TAG_CHANGE_RE.match(body)
            if m:
                eid = self._ref(m.group(1))
                if eid is not None:
                    self._tag_change(self._ent(eid), m.group(2), m.group(3))
            return
        if body.startswith("FULL_ENTITY"):
            m = FULL_RE.match(body)
            if m:
                e = self._ent(int(m.group(1)))
                if m.group(2):
                    e.card_id = m.group(2)
                    if "_Anomaly_" in e.card_id and self.g and not self.g.anomaly:
                        self.g.anomaly = e.card_id
                self.ctx = e
            return
        if body.startswith(("SHOW_ENTITY", "CHANGE_ENTITY")):
            m = SHOW_RE.match(body)
            if m:
                eid = self._ref(m.group(1))
                if eid is not None:
                    e = self._ent(eid)
                    e.card_id = m.group(2) or e.card_id
                    self.ctx = e
            return
        if body.startswith("HIDE_ENTITY"):
            m = HIDE_RE.match(body)
            if m:
                eid = self._ref(m.group(1))
                if eid is not None:
                    self._ent(eid).tags[m.group(2)] = m.group(3)
            return
        if body.startswith("BLOCK_START"):
            m = BLOCK_RE.match(body)
            if m and m.group(1) == "ATTACK":
                self._combat_snapshot()
            return
        if body == "CREATE_GAME":
            self._new_game()
            return
        if body.startswith("GameEntity"):
            m = GAME_ENTITY_RE.match(body)
            if m:
                self.game_entity = int(m.group(1))
                self.ctx = self._ent(self.game_entity)
            return
        if body.startswith("Player EntityID"):
            m = PLAYER_RE.match(body)
            if m and self.g:
                eid, pid, lo = int(m.group(1)), int(m.group(2)), int(m.group(4))
                self.player_ids[pid] = eid
                e = self._ent(eid)
                e.tags["PLAYER_ID"] = str(pid)
                if lo != 0 and self.g.me_entity is None:
                    self.g.me_entity, self.g.me_player_id, self.g.account = eid, pid, lo
                else:
                    self.g.other_entity = eid
                self.ctx = e

    def _new_game(self):
        now = self.now
        if self.g:
            self._end_game(complete=self.g.complete)
        self._reset()
        self.now = now
        self.g = Game(start=now)

    # ------------------------------------------------------------ tag effects
    def _tag_change(self, e: Entity, tag: str, value: str):
        old = e.tags.get(tag)
        e.tags[tag] = value
        g = self.g
        if g is None:
            return
        if e.id == self.game_entity:
            if tag == "TURN":
                self._on_turn(int(value))
            elif tag == "STATE" and value == "COMPLETE":
                g.complete = True
                self._complete_at = self.now
                self.placement_locked = True  # later leaderboard changes are a cosmetic re-sort
            return
        hero = self._my_hero()
        if e.id == g.me_entity and tag == "HERO_ENTITY" and value.isdigit():
            self.my_hero_ids.add(int(value))
        # Placement: last leaderboard value on my hero (or the hero copy created when I die)
        # before STATE=COMPLETE. After COMPLETE the client re-sorts the board cosmetically.
        if tag == "PLAYER_LEADERBOARD_PLACE" and value.isdigit() and int(value) > 0                 and not self.placement_locked and (
                    e.id in self.my_hero_ids or (hero is not None and e.id == hero.id)
                    or (e.tag("CARDTYPE") == "HERO" and e.int("CONTROLLER", -1) == g.me_player_id
                        and g.hero and norm_hero(e.card_id) == norm_hero(g.hero))):
            g.placement = int(value)
        if hero is not None and e.id == hero.id:
            if tag == "BACON_WON_LAST_COMBAT" and self.cur_combat is not None:
                self.cur_combat["won_flag"] = value == "1"
            elif tag == "PLAYER_TECH_LEVEL" and old is not None and value != old:
                self._emit("tier", {"round": self._round(), "tier": int(value)})
            elif tag == "NEXT_OPPONENT_PLAYER_ID" and value.isdigit() and int(value) and value != old \
                    and self.turn % 2 == 1:  # announced during the shop phase, as the game shows it
                self._emit("next_opponent", {"round": self._round(), "lobby_id": int(value)})
        c = self.cur_combat
        if c is not None and e.id == c.get("_opp_hero_ent") and tag == "PREDAMAGE" and value.isdigit():
            c["_pre"] = max(c.get("_pre", 0), int(value))
        if e.id == g.me_entity and tag == "PLAYSTATE" and value in ("WON", "LOST", "CONCEDED"):
            g.end = self.now

    def _round(self) -> int:
        return (self.turn + 1) // 2

    def _on_turn(self, turn: int):
        self._run_checks(turn_ended=True)
        g = self.g
        self.turn = turn
        if turn % 2 == 0:  # recruit -> combat
            board = self.board()
            if board or not g.final_board:
                g.final_board = board
            if self.cur_turn is not None:
                self.cur_turn["end_board"] = board
                self.cur_turn["gold_end"] = self._gold()  # unspent gold when the shop phase ended
                self.cur_turn["end_shop"] = self.shop()   # what you could still have bought
            hero = self._my_hero()
            self.cur_combat = {"round": self._round(), "line": self.line_no, "t": self.now.isoformat(timespec="seconds"), "hp_before": self._hp(hero),
                               "armor_before": hero.int("ARMOR") if hero else 0,
                               "my_board": None, "opp_board": None, "opp_hero": None,
                               "_lobby": self.lobby()}  # health before the fight, to see who was hit
            if hero is not None:
                opp_pid = hero.int("NEXT_OPPONENT_PLAYER_ID", 0)
                self.cur_combat["opp_lobby_id"] = opp_pid or None
        else:  # combat -> recruit (new round)
            self._close_combat()
            hero = self._my_hero()
            self.cur_turn = {"round": self._round(), "line": self.line_no, "start": self.now.isoformat(timespec="seconds"),
                             "tier": self.tier(), "hp": self._hp(hero), "armor": hero.int("ARMOR") if hero else 0,
                             "gold": None, "shop": None, "actions": [], "end_board": None,
                             "lobby": self.lobby(), "me_lobby": self.my_lobby_id()}
            g.turns.append(self.cur_turn)
            self.last_shop = None
            self._emit("round", self.cur_turn)

    def _combat_snapshot(self):
        c = self.cur_combat
        if c is None or c["my_board"] is not None or self.turn % 2:
            return
        c["my_board"] = self.board()
        c["opp_board"] = self._zone(self._other_pid(), "PLAY")
        oh = self._hero_of(self.g.other_entity)
        if oh:
            c["opp_hero"] = oh.card_id
            c["_opp_hero_ent"] = oh.id
            c["opp_hp_before"] = self._ehp(oh)

    def _close_combat(self):
        c = self.cur_combat
        if c is None:
            return
        hero = self._my_hero()
        hp_after, armor_after = self._hp(hero), hero.int("ARMOR") if hero else 0
        taken = None
        if c["hp_before"] is not None and hp_after is not None:
            taken = (c["hp_before"] + c["armor_before"]) - (hp_after + armor_after)
        c.pop("_opp_hero_ent", None)
        dealt = c.pop("_pre", 0)  # hero hit is logged as PREDAMAGE on the opponent's combat hero
        before, opp = c.pop("_lobby", None) or {}, str(c.get("opp_lobby_id"))
        if not dealt and opp in before:
            # Duos: the hit lands on whichever enemy hero fought last, so read it from their team's
            # health on the leaderboard instead (both teammates show the shared total)
            was, now = before[opp].get("hp"), (self.lobby().get(opp) or {}).get("hp")
            if isinstance(was, int) and isinstance(now, int) and was > now:
                dealt = was - now
        c["hp_after"], c["armor_after"], c["damage_taken"], c["damage_dealt"] = hp_after, armor_after, taken, dealt
        c["line_end"] = self.line_no
        ge = self.ents.get(self.game_entity) if self.game_entity is not None else None
        cap = ge.int("BACON_COMBAT_DAMAGE_CAP") if ge else 0
        c["damage_cap"] = cap if cap and ge.int("BACON_COMBAT_DAMAGE_CAP_ENABLED", 1) else None
        if taken and taken > 0:
            c["result"] = "LOSS"
        elif c.get("won_flag") or (dealt and dealt > 0):
            c["result"] = "WIN"
        else:
            c["result"] = "TIE"
        self.g.combats.append(c)
        self.cur_combat = None
        self._emit("combat", c)

    def _end_game(self, complete: bool):
        g = self.g
        if g is None:
            return
        self._run_checks(turn_ended=True)
        if self.cur_combat is not None:
            self._close_combat()
        g.complete = complete
        g.end = g.end or self.now
        hero = self._my_hero()
        if hero is not None and not g.hero:
            g.hero = hero.card_id
        if g.game_type and "BATTLEGROUNDS" in g.game_type and g.turns:
            self.games.append(g)
            self._emit("game_end", g.to_dict())
            if self.on_game:
                self.on_game(g)
        now = self.now
        self._reset()
        self.now = now

    # ------------------------------------------------------------ options
    def _options(self, body: str):
        if body.startswith("id="):
            self._run_checks()
            self.options = {}
            self._ensure_turn_snapshot()
            return
        m = OPTION_RE.match(body)
        if m:
            idx = int(m.group(1))
            self.options[idx] = {"type": m.group(2), "entity": self._ref(m.group(3)),
                                 "legal": m.group(4) in ("NONE", "")}

    def _ensure_turn_snapshot(self):
        t = self.cur_turn
        if t is None or self.turn % 2 == 0:
            return
        if t["gold"] is None:
            t["gold"] = self._gold()
            t["tier"] = self.tier()
            t["shop"] = self.shop()
            t["board"] = self.board()
            t["hand"] = self.hand()
            self.last_shop = [c["card_id"] for c in t["shop"]]
            self._emit("turn_start", t)

    def _send_option(self, body: str):
        m = SEND_OPTION_RE.search(body)
        if not m or self.g is None:
            return
        sel, _sub, target, pos = (int(x) for x in m.groups())
        opt = self.options.get(sel)
        if opt is None:
            return
        action = self._classify(opt, target, pos)
        if action is None:
            return
        action.update({"t": self.now.isoformat(timespec="seconds"), "round": self._round(), "line": self.line_no,
                       "gold": self._gold(), "tier": self.tier()})
        if action["type"] in ("BUY", "REFRESH", "FREEZE", "LEVEL", "END_TURN"):
            shop_now = [c["card_id"] for c in self.shop()]
            if shop_now != self.last_shop:
                action["shop"] = shop_now
                self.last_shop = shop_now
        self._add_check(action, opt, target)
        if self.cur_turn is not None:
            self.cur_turn["actions"].append(action)
        self._emit("action", action)

    # ------------------------------------------------------------ self-checks
    def _add_check(self, a: dict, opt: dict, target: int):
        """Each recorded action predicts something the log must show next. Verified when the game
        offers the next set of options (the action has resolved by then)."""
        me = self.g.me_player_id
        t = a["type"]
        e = self.ents.get(target) if target > 0 else None
        src = self.ents.get(opt["entity"]) if opt.get("entity") else None
        if t == "BUY" and e is not None:
            self.pending_checks.append((a, "bought card came to you",
                lambda e=e: e.int("CONTROLLER", -1) == me))
        elif t == "SELL" and e is not None:
            self.pending_checks.append((a, "sold minion left your board",
                lambda e=e: not (e.tag("ZONE") == "PLAY" and e.int("CONTROLLER", -1) == me)))
        elif t == "LEVEL":
            before = self.tier()
            self.pending_checks.append((a, "tavern tier went up", lambda b=before: self.tier() > b))
        elif t in ("PLAY", "CAST") and src is not None:
            self.pending_checks.append((a, "card left your hand", lambda s=src: s.tag("ZONE") != "HAND"))
        elif t == "REFRESH":
            before = sorted(c["id"] for c in self.shop())
            if before:
                self.pending_checks.append((a, "shop changed", lambda b=before: sorted(c["id"] for c in self.shop()) != b))

    def _run_checks(self, turn_ended: bool = False):
        if not self.pending_checks or self.g is None:
            return
        for a, what, fn in self.pending_checks:
            try:
                ok = bool(fn())
            except Exception:
                ok = False
            if ok:
                self.g.checks_ok += 1
            elif turn_ended:
                # Clicked as the timer ran out: the game ended the turn before resolving it.
                # A real event (verified 11-09 00:48 R9), not a parser error.
                a["applied"] = False
                a["note"] = "not applied: the turn ended before it resolved"
                self.g.not_applied += 1
                self._emit("not_applied", {"round": a.get("round"), "action": a["type"], "line_no": a.get("line"),
                                           "card": a.get("target") or a.get("card_id")})
            else:
                fail = {"line_no": a.get("line"), "round": a.get("round"), "action": a["type"],
                        "card": a.get("target") or a.get("card_id"), "expected": what}
                self.g.check_failures.append(fail)
                self._emit("check_failed", fail)
        self.pending_checks = []
        self._emit("checks", {"ok": self.g.checks_ok, "failed": len(self.g.check_failures)})

    def _classify(self, opt: dict, target: int, pos: int) -> dict | None:
        if opt["type"] == "END_TURN":
            return {"type": "END_TURN"}
        e = self.ents.get(opt["entity"]) if opt["entity"] else None
        if e is None:
            return {"type": "UNKNOWN", "option_type": opt["type"]}
        cid = e.card_id
        tgt = self.ents.get(target) if target > 0 else None
        a: dict
        if cid in BUTTONS:
            a = {"type": BUTTONS[cid]}
        elif cid.startswith("TB_BaconShopTechUp"):
            a = {"type": "LEVEL", "to_tier": self.tier() + 1}
        elif e.tag("CARDTYPE") == "HERO_POWER":
            a = {"type": "HERO_POWER", "card_id": cid}
        elif e.tag("ZONE") == "HAND":
            a = {"type": "PLAY" if e.tag("CARDTYPE") == "MINION" else "CAST", "card_id": cid}
            if pos > 0:
                a["position"] = pos
        elif e.tag("ZONE") == "PLAY" and e.tag("CARDTYPE") == "MINION" \
                and e.int("CONTROLLER", -1) == self.g.me_player_id:
            if pos > 0:
                a = {"type": "MOVE", "card_id": cid, "from": e.int("ZONE_POSITION"), "to": pos}
            else:
                a = {"type": "ACTIVATE", "card_id": cid}
        elif e.tag("ZONE") == "PLAY" and e.int("CONTROLLER", -1) == self._other_pid()                 and e.tag("CARDTYPE") in SHOP_TYPES:
            # Clicking a shop card only selects it. Verified on all archived logs (2026-11-10):
            # 0/147 such clicks bought the card; every purchase was a separate DragBuy option.
            return None
        elif e.tag("CARDTYPE") == "HERO":
            a = {"type": "HERO_CLICK", "card_id": cid}
        else:
            a = {"type": "OTHER", "card_id": cid, "cardtype": e.tag("CARDTYPE"), "zone": e.tag("ZONE")}
        if tgt is not None:
            a["target"] = tgt.card_id
            a["target_atk_hp"] = [tgt.int("ATK"), tgt.int("HEALTH") - tgt.int("DAMAGE")]
        return a

    # ------------------------------------------------------------ choices
    def _choices(self, body: str):
        m = CHOICES_HDR_RE.match(body)
        if m:
            name = m.group(2)
            mine = self.g is not None and (self.g.me_name is None or name == self.g.me_name)
            self.pending_choice = {"id": int(m.group(1)), "kind": m.group(3), "source": None,
                                   "options": []} if mine else None
            if self.pending_choice:
                self.choices[self.pending_choice["id"]] = self.pending_choice
            return
        if self.pending_choice is None:
            return
        if body.startswith("Source="):
            eid = self._ref(body[len("Source="):])
            e = self.ents.get(eid) if eid else None
            self.pending_choice["source"] = e.card_id if e else body[len("Source="):]
            return
        m = ENTITIES_RE.match(body)
        if m:
            eid = self._ref(m.group(1))
            e = self.ents.get(eid) if eid else None
            self.pending_choice["options"].append(e.card_id if e else None)
            if e and e.int("BACON_LOCKED_MULLIGAN_HERO") == 1:  # shown, but only the Tavern Pass unlocks it
                self.pending_choice.setdefault("locked", []).append(e.card_id)
            ch = self.pending_choice  # announce while you are still choosing (live advice)
            self._emit("offers", {"id": ch["id"], "kind": self._choice_kind(ch), "round": self._round(),
                                  "source": ch["source"], "options": list(ch["options"]),
                                  "locked": list(ch.get("locked") or []),
                                  "duos": "DUO" in (self.g.game_type or "") if self.g else False})

    def _chosen(self, body: str):
        m = CHOSEN_HDR_RE.match(body)
        if m:
            self.chosen_id = int(m.group(1))
            return
        m = ENTITIES_RE.match(body)
        if not m or self.chosen_id is None or self.g is None:
            return
        ch = self.choices.get(self.chosen_id)
        if ch is None:
            return
        eid = self._ref(m.group(1))
        e = self.ents.get(eid) if eid else None
        picked = e.card_id if e else None
        rec = {"t": self.now.isoformat(timespec="seconds"), "round": self._round(), "line": self.line_no,
               "kind": self._choice_kind(ch), "source": ch["source"],
               "options": ch["options"], "picked": picked}
        if ch.get("_done"):
            return
        ch["_done"] = True
        if rec["kind"] == "HERO_PICK":
            self.g.hero_offers = ch["options"]
            self.g.hero_locked = list(ch.get("locked") or [])
            self.g.hero = picked
        self.g.choices.append(rec)
        if self.cur_turn is not None and rec["kind"] != "HERO_PICK":
            self.cur_turn["actions"].append({"type": "CHOICE", **rec})
        self._emit("choice", rec)

    @staticmethod
    def _choice_kind(ch: dict) -> str:
        src = ch["source"] or ""
        if ch["kind"] == "MULLIGAN":
            return "HERO_PICK"
        if "Triples" in src:
            return "TRIPLE_DISCOVER"
        if "Trinket" in src:
            return "TRINKET_PICK"
        if "DarkGift" in src:
            return "DARK_GIFT_PICK"
        if src.startswith("TB_BaconShop_HP") or "_HERO_" in src:
            return "HERO_POWER_PICK"
        return "DISCOVER"
