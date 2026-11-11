"""bg-coach command line.  Run `bgcoach --help` or `bgcoach <command> --help`.

  ui          open the app (live game, coaching, games, health) + overlay
  setup       check locations, turn on Hearthstone logging (+ --shortcut on Windows)
  log         replay a Power.log as a readable timeline (or --live)
  import      parse archived logs into games          archive   copy new logs into the archive
  check       compare parsed games with HDT           facts     session facts for /review-session
  whatif      simulate fights / what-ifs              sim-check simulator vs Bob's Buddy
  version     game build, patch, card pool            share     clean zip for someone else
  anonymise   strip names/account ids from a log (for bug reports)
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from . import __version__, pipeline
from . import version as V
from .install import run_setup, windowless_logging
from .live import LiveWatcher, latest_power_log
from .replay import Replay, norm_hero
from .terminal import Printer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ commands
def cmd_version(_a) -> None:
    build, session = V.latest_client_build()
    meta = V.current_bg_meta_build()
    print(f"bg-coach {__version__}")
    if build:
        p = V.patch_for_build(build)
        exact = "" if p.get("exact") else "  [nearest known patch]"
        print(f"  Your client build : {build}  (from {session})")
        print(f"  Patch             : {p.get('version')} — {p.get('name')} (released {str(p.get('date'))[:10]}){exact}")
    else:
        print("  Your client build : unknown (no Hearthstone log found)")
    mp = V.patch_for_build(meta)
    print(f"  Latest BG patch   : {meta} — {mp.get('version')} {mp.get('name')}")
    if build and build < meta:
        print("  ⚠ A newer build exists than your last logged session.")
    db = V.card_db(build or meta)
    print(f"  Card DB           : build {db.build if db.build > 0 else 'latest'} ({len(db.by_id)} cards)")
    pool = V.blizzard_bg_pool()
    tiers = collections.Counter(c.get("battlegrounds", {}).get("tier") for c in pool["minion"])
    by_tier = ", ".join(f"T{t}:{n}" for t, n in sorted((k, v) for k, v in tiers.items() if k))
    print(f"  Live BG pool      : {len(pool['hero'])} heroes, {len(pool['minion'])} minions ({by_tier}), "
          f"{len(pool['spell'])} spells, {len(pool['trinket'])} trinkets, {len(pool['anomaly'])} anomalies")


def cmd_log(a) -> None:
    if a.live:
        return _log_live(Path(a.file) if a.file not in (None, "latest") else None)
    path = latest_power_log() if a.file in (None, "latest") else Path(a.file)
    if path is None or not path.exists():
        sys.exit("No Power.log found.")
    print(f"Replaying {path}")
    pr = Printer()
    rp = Replay(base_date=pipeline.base_date_for(path), on_event=(lambda k, d: None) if a.quiet else pr,
                on_game_start=pr.game_start)
    with pipeline.open_log(path) as fh:
        games = rp.feed_all(fh)
    for g in games:
        g.source = str(path)
        if not a.quiet:
            pr.summary(g)
        print(f"saved → {pipeline.save_game(g, pipeline.hdt_games())}")


def _log_live(follow: Path | None) -> None:
    import time
    pr = Printer(live=True)

    def on_event(kind: str, d: dict) -> None:
        if kind == "game_start":
            print(f"\n▶ Game started · build {d['build']}, patch {d.get('patch')} ({d.get('patch_name')})")
            pr.db = V.card_db(d["build"])
        elif kind == "game_end":
            print(f"\n■ Game over: place {d.get('placement')} · saved {d.get('file')}")
        elif kind == "status" and d.get("message"):
            print(d["message"])
        else:
            pr(kind, d)

    w = LiveWatcher(on_event, follow=follow)
    w.start()
    print("Watching Hearthstone… (Ctrl+C to stop)")
    try:
        while w.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        w.stop()


def cmd_check(a) -> None:
    res = pipeline.verify_against_hdt(limit=a.limit)
    for r in res["rows"]:
        g, m, ok = r["game"], r["hdt"], r["ok"]
        if not r["mine"]:
            note = "other account (not your game)"
        elif "DUO" in (g.game_type or ""):
            note = "duos"
        elif m is None:
            note = "no HDT record"
        else:
            mine = {"hero": norm_hero(g.hero), "placement": g.placement}
            bad = [k if k == "board" else f"{k} {mine[k]} vs HDT {m[k]}" for k, v in ok.items() if not v]
            note = "OK" if not bad else "mismatch: " + ", ".join(bad)
        mmr = f"{m['rating']}→{m['rating_after']}" if m and m.get("rating") else ""
        print(f"  {g.start:%m-%d %H:%M}  {norm_hero(g.hero):<22} place {g.placement}  {mmr:<11} {note}")
    a = res["agreement"]
    n = a.get("matched") or 1
    print(f"\nYour games also recorded by HDT: {a.get('matched', 0)} → hero {a.get('hero', 0)}/{n}, "
          f"placement {a.get('placement', 0)}/{n}, final board {a.get('board', 0)}/{n}")
    if res["solo_games"]:
        print(f"Your solo games: {res['solo_games']}, average placement {res['avg_place']}")


def cmd_ui(a) -> None:
    from . import web
    test = None
    if a.test:
        test = Path(a.test) if a.test != "newest" else next(
            (p for p in reversed(pipeline.archived_logs()) if p.parent.parent.name == "hs"), None)
        if test is None or not test.exists():
            sys.exit("No archived log to test with. Run: bgcoach import")
    web.serve(a.port, not a.no_browser, Path(a.follow) if a.follow else None, not a.no_auto_archive,
              test_log=test, speed=a.speed, overlay=not a.no_overlay)


def _run(module: str, argv: list[str] | None = None):
    """Commands implemented in their own module (each has a main(argv))."""
    import importlib
    return lambda a: importlib.import_module(f"bgcoach.{module}").main(argv(a) if callable(argv) else argv)


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bgcoach", description="Personal Hearthstone Battlegrounds coach.")
    ap.add_argument("--version", action="version", version=f"bg-coach {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("ui", help="open the app (live game, coaching, games, health) + overlay")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.add_argument("--no-overlay", action="store_true", help="don't open the always-on-top overlay")
    p.add_argument("--no-auto-archive", action="store_true", help="don't archive/import every 30 minutes")
    p.add_argument("--follow", metavar="LOG", help="watch this log file instead of Hearthstone's (testing)")
    p.add_argument("--test", nargs="?", const="newest", metavar="LOG",
                   help="test mode: replay an archived game into the Live tab (default: newest)")
    p.add_argument("--speed", type=int, default=8000, help="test mode: log lines per second")
    p.set_defaults(fn=cmd_ui)

    p = sub.add_parser("setup", help="check locations, turn on Hearthstone logging")
    p.add_argument("--shortcut", action="store_true", help="Windows: create Desktop/Start-menu shortcuts")
    p.set_defaults(fn=lambda a: run_setup(a.shortcut))

    p = sub.add_parser("log", help="replay a Power.log as a readable timeline")
    p.add_argument("file", nargs="?", help="Power.log or .gz (default: newest)")
    p.add_argument("--live", action="store_true", help="follow the running game instead")
    p.add_argument("--quiet", action="store_true", help="only save, don't print the timeline")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("import", help="parse archived logs into games")
    p.add_argument("--force", action="store_true", help="re-parse logs that were already imported")
    p.set_defaults(fn=lambda a: pipeline.import_all(force=a.force))

    p = sub.add_parser("archive", help="copy new Hearthstone/HDT logs into the archive")
    p.add_argument("--import-legacy", action="store_true", help="also import BGCOACH_LEGACY_REPO logs")
    p.set_defaults(fn=_run("archive", lambda a: ["--import-legacy"] if a.import_legacy else []))

    p = sub.add_parser("check", help="re-parse archived logs and compare with HDT's records")
    p.add_argument("--limit", type=int, default=0, help="only the newest N logs")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("facts", help="verified facts about your last session (for /review-session)")
    p.add_argument("--last", type=int, default=0, help="last N games instead of the last session")
    p.set_defaults(fn=_run("facts", lambda a: ["--last", str(a.last)] if a.last else []))

    p = sub.add_parser("whatif", help="simulate fights, buy what-ifs and minion orders (needs Node.js)")
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_run("whatif", lambda a: ["--last", str(a.last)] + (["--force"] if a.force else [])))

    p = sub.add_parser("sim-check", help="compare the combat simulator with Bob's Buddy on real fights")
    p.add_argument("--logs", type=int, default=3)
    p.add_argument("--sims", type=int, default=1000)
    p.set_defaults(fn=_run("simcheck", lambda a: ["--logs", str(a.logs), "--sims", str(a.sims)]))

    p = sub.add_parser("anonymise", help="make a Power.log safe to attach to a bug report")
    p.add_argument("log", help="Power.log or .log.gz")
    p.add_argument("-o", "--out", help="output file (.gz = compressed)")
    p.add_argument("--game", type=int, help="only the Nth game in the file (1 = first)")
    p.set_defaults(fn=_run("anonymise", lambda a: [a.log] + (["-o", a.out] if a.out else [])
                           + (["--game", str(a.game)] if a.game else [])))

    sub.add_parser("version", help="game build, patch and card pool").set_defaults(fn=cmd_version)
    sub.add_parser("share", help="build a clean zip (no personal data)").set_defaults(fn=_run("share"))

    p = sub.add_parser("overlay", help="only the overlay window (the app must be running)")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=lambda a: __import__("bgcoach.overlay", fromlist=["main"]).main(a.port))
    return ap


def main(argv: list[str] | None = None) -> None:
    windowless_logging()
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
