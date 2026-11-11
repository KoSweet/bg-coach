"""Make a Power.log safe to share (bug reports, test fixtures).

Keeps only the `GameState.` lines the parser reads, and replaces
  * your BattleTag                         → You#0001
  * other players' names                   → Opponent1, Opponent2, … (consistent through the file)
  * Battle.net account ids (GameAccountId) → hi=1 lo=1 for you, hi=0 lo=0 stays as is
Card names, hero names and the innkeeper ("Bartender") are kept: they are game data, not people.

    bgcoach anonymise Power.log                  → Power.anon.log.gz next to it
    bgcoach anonymise Power.log --game 2 -o x.log.gz
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from .pipeline import open_log

NAME_RE = re.compile(r"\b(PlayerName|Entity|Player)=([^\s\[\]=]+)")
CARD_NAME_RE = re.compile(r"\bentityName=(.+?) id=")
ACCOUNT_RE = re.compile(r"GameAccountId=\[hi=(\d+) lo=(\d+)\]")
OWNER_RE = re.compile(r"PlayerID=(\d+), PlayerName=(\S+)")
PLAYER_RE = re.compile(r"Player EntityID=\d+ PlayerID=(\d+) GameAccountId=\[hi=\d+ lo=(\d+)\]")
TAG_RE = re.compile(r"[^\s=\[\]]+#\d{3,6}\b")  # BattleTag-like: Name#12345
MULTI_WORD_RE = re.compile(r" [^\s=]+(?:\s|$)")  # `Entity=Bartender Bob tag=…`: next word has no "="
KEEP = {"GameEntity"}


def select_games(lines: Iterable[str], game: int | None = None) -> list[str]:
    """GameState lines only; with `game`, only that game (1 = first CREATE_GAME in the file)."""
    out, n = [], 0
    for line in lines:
        if "GameState." not in line:
            continue
        if "CREATE_GAME" in line:
            n += 1
        if game is None or n == game:
            out.append(line if line.endswith("\n") else line + "\n")
        elif game is not None and n > game:
            break
    return out


class _Cards:
    """Card / entity names seen in the log (`entityName=…`). Player names never contain spaces,
    but card names do ("Bartender Bob"), so `Entity=Bartender Bob` must not be read as a player."""

    def __init__(self, lines: list[str]):
        self.names = {m.group(1) for ln in lines for m in CARD_NAME_RE.finditer(ln)}
        self.multi: dict[str, list[str]] = {}
        for n in self.names:
            if " " in n:
                self.multi.setdefault(n.split(" ", 1)[0], []).append(n)

    def at(self, m: re.Match) -> bool:
        """Is the name in this match (really) a card name?"""
        v = m.group(2)
        if v in self.names or MULTI_WORD_RE.match(m.string, m.end(2)):
            return True
        return any(m.string.startswith(full, m.start(2)) for full in self.multi.get(v, ()))


def find_names(lines: list[str]) -> tuple[dict[str, str], _Cards]:
    """Map every player name to a placeholder: the log owner → You#0001, others → OpponentN."""
    cards = _Cards(lines)
    owner_ids = set()  # PlayerIDs with a real Battle.net account = the log owner
    for ln in lines:
        m = PLAYER_RE.search(ln)
        if m and m.group(2) != "0":
            owner_ids.add(m.group(1))
    mapping: dict[str, str] = {}
    n_opp = 0
    for ln in lines:
        m = OWNER_RE.search(ln)
        if m and m.group(1) in owner_ids and m.group(2) not in mapping:
            mapping[m.group(2)] = "You#0001"
        for m in NAME_RE.finditer(ln):
            v = m.group(2)
            if v.isdigit() or v in KEEP or v in mapping or cards.at(m):
                continue
            if "#" in v and "You#0001" not in mapping.values():
                mapping[v] = "You#0001"
            else:
                n_opp += 1
                mapping[v] = f"Opponent{n_opp}"
    return mapping, cards


def anonymise_lines(lines: list[str]) -> tuple[list[str], dict]:
    mapping, cards = find_names(lines)

    def name(m: re.Match) -> str:
        v = m.group(2)
        return m.group(0) if v not in mapping or cards.at(m) else f"{m.group(1)}={mapping[v]}"

    def account(m: re.Match) -> str:
        return "GameAccountId=[hi=0 lo=0]" if m.group(2) == "0" else "GameAccountId=[hi=1 lo=1]"

    out = [ACCOUNT_RE.sub(account, NAME_RE.sub(name, ln)) for ln in lines]
    tags = {m.group(0) for ln in out for m in TAG_RE.finditer(ln)}
    return out, {"players": len(mapping), "lines": len(out), "leftover_tags": sorted(tags - {"You#0001"})}


def anonymise_file(src: Path, dst: Path | None = None, game: int | None = None) -> tuple[Path, dict]:
    with open_log(src) as fh:
        lines = select_games(fh, game)
    out, info = anonymise_lines(lines)
    if dst is None:
        stem = src.name.removesuffix(".gz").removesuffix(".log")
        dst = src.with_name(f"{stem}.anon.log.gz")
    data = "".join(out).encode("utf-8")
    if dst.suffix == ".gz":
        dst.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    else:
        dst.write_bytes(data)
    return dst, info


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="bgcoach anonymise", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="Power.log or .log.gz")
    ap.add_argument("-o", "--out", type=Path, help="output file (.gz = compressed)")
    ap.add_argument("--game", type=int, help="only the Nth game in the file (1 = first)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dst, info = anonymise_file(a.log, a.out, a.game)
    print(f"{dst}: {info['lines']} lines, {info['players']} player name(s) replaced")
    if info["leftover_tags"]:
        print(f"⚠ still looks like BattleTags: {', '.join(info['leftover_tags'])}. Check before sharing.")


if __name__ == "__main__":
    main()
