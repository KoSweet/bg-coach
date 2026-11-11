"""Errors + data-health checks, and the compact "report for Claude" text.

Two kinds of problems:
- errors: something crashed (app error) or a log line failed to parse (parse error).
  Stored in data/errors.jsonl with full context.
- issues: a parsed game looks wrong (no placement, unknown actions, HDT disagreement...).

`report_text()` turns either into a short markdown block to paste into Claude Code or a GitHub
issue: line numbers, the exact failing log line and traceback — everything needed to fix it
without a back-and-forth. It is safe to post publicly: folder names are shortened (`~`, `<data>`)
and BattleTags / player names in log lines are replaced (see `anonymise.py`).
"""
from __future__ import annotations

import datetime as dt
import json
import platform
import re
import subprocess
import traceback
from pathlib import Path

from .paths import DATA

ERRORS = DATA / "errors.jsonl"
REPO = Path(__file__).resolve().parents[2]


def record_error(kind: str, exc: BaseException | None = None, **context) -> dict:
    err = {
        "id": dt.datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "error": repr(exc) if exc else context.pop("error", ""),
        "traceback": "".join(traceback.format_exception(exc, limit=6)) if exc else context.pop("traceback", ""),
        "context": context,
    }
    ERRORS.parent.mkdir(parents=True, exist_ok=True)
    with open(ERRORS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(err, default=str) + "\n")
    return err


def list_errors(limit: int = 200) -> list[dict]:
    if not ERRORS.exists():
        return []
    rows = [json.loads(ln) for ln in ERRORS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return list(reversed(rows))[:limit]


def clear_errors() -> None:
    if ERRORS.exists():
        ERRORS.rename(ERRORS.with_suffix(f".{dt.datetime.now():%Y%m%d%H%M%S}.cleared"))


# ------------------------------------------------------------------ game health
def game_issues(g: dict) -> list[dict]:
    """Sanity checks on a parsed game dict. Severity: error (data is wrong) / warn (suspicious)."""
    out = []

    def add(sev, code, msg, **ctx):
        out.append({"severity": sev, "code": code, "message": msg, **ctx})

    if not g.get("placement"):
        add("error", "no_placement", "No final placement found")
    if not g.get("hero"):
        add("error", "no_hero", "Hero not identified")
    if not g.get("complete"):
        add("warn", "incomplete", "Game did not finish in the log (closed early / log cut)")
    turns = g.get("turns") or []
    if not turns:
        add("error", "no_turns", "No rounds parsed")
    for t in turns:
        for a in t.get("actions", []):
            if a["type"] in ("OTHER", "UNKNOWN"):
                add("error", "unknown_action", f"Unclassified action in round {t['round']}", round=t["round"],
                    action=a)
            if isinstance(a.get("gold"), int) and a["gold"] < 0:
                add("error", "negative_gold", f"Negative gold ({a['gold']}) in round {t['round']}",
                    round=t["round"], action=a)
        if t.get("gold") is None:
            add("warn", "no_turn_snapshot", f"Round {t['round']}: no shop/gold snapshot", round=t["round"])
    if len(g.get("combats") or []) + 1 < len(turns):
        add("warn", "missing_combats", f"{len(g.get('combats') or [])} combats for {len(turns)} rounds")
    for f in g.get("check_failures") or []:
        add("error", "self_check_failed",
            f"Round {f.get('round')}: {f.get('action')} recorded but '{f.get('expected')}' did not happen",
            line_no=f.get("line_no"), round=f.get("round"))
    for e in g.get("errors") or []:
        add("error", "parse_error", f"Parse error at log line {e['line_no']} (round {e.get('round')}): {e['error']}",
            line_no=e["line_no"])
    hdt = g.get("hdt")
    if hdt:
        if hdt.get("placement") and g.get("placement") and hdt["placement"] != g["placement"]:
            add("error", "hdt_placement", f"Placement {g['placement']} but HDT says {hdt['placement']}")
        if hdt.get("board") is not None and sorted(c["card_id"] for c in g.get("final_board", [])) != hdt["board"]:
            add("error", "hdt_board", "Final board differs from HDT")
    return out


# ------------------------------------------------------------------ user-reported problems
REPORTS = DATA / "reports"
_KEY = ("SendOption", "DebugPrintEntityChoices() - id=", "DebugPrintEntitiesChosen() - id=",
        "BLOCK_START BlockType=PLAY", "BLOCK_START BlockType=POWER", "tag=TURN ", "tag=STEP ",
        "tag=PLAYER_TECH_LEVEL", "tag=RESOURCES_USED", "BLOCK_START BlockType=MOVE_MINION")


def _read_range(source: str, start: int, end: int) -> list[tuple[int, str]]:
    import gzip
    p = Path(source)
    opener = gzip.open if p.suffix == ".gz" else open
    out = []
    with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if i < start:
                continue
            if i > end:
                break
            if "GameState." in line:
                out.append((i, line.rstrip()))
    return out


def problem_report(note: str, source: str, round_no: int | None, start_line: int, end_line: int,
                   recorded: dict | None = None, game_file: str | None = None,
                   names: dict | None = None, screenshot: str | None = None) -> dict:
    """User saw something in the game that the app missed / got wrong. Bundle: note + what we
    recorded for that round + key raw log lines; the full raw slice is saved to a file."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = _read_range(source, start_line, end_line)
    slice_path = REPORTS / f"{stamp}_round{round_no}.log"
    slice_path.write_text("\n".join(f"{i}: {ln}" for i, ln in lines), encoding="utf-8")

    # key lines, with each SendOption annotated by the option it picked
    key, last_opts = [], {}
    for i, ln in lines:
        if "DebugPrintOptions() - id=" in ln:
            last_opts = {}
        elif "DebugPrintOptions() -   option " in ln:
            m = re.search(r"option (\d+) type=(\w+) mainEntity=(.*?) error=", ln)
            if m:
                last_opts[m.group(1)] = (i, f"{m.group(2)} {m.group(3)[:120]}")
        if any(k in ln for k in _KEY):
            txt = ln.split(" - ", 1)[-1].strip()
            if "SendOption" in ln:
                m = re.search(r"selectedOption=(\d+)", ln)
                if m and m.group(1) in last_opts:
                    txt += f"   ⇒ option {m.group(1)} = {last_opts[m.group(1)][1]}"
                key.append(f"{i}: {txt[:420]}")
            else:
                key.append(f"{i}: {txt[:220]}")
    rec_lines = []
    if recorded:
        rec_lines.append(f"- round {recorded.get('round')}: tier {recorded.get('tier')}, gold {recorded.get('gold')}, "
                         f"hp {recorded.get('hp')}")
        for a in recorded.get("actions", []):
            nm = lambda c: f"{names[c]} ({c})" if names and c in names else c
            if a["type"] == "CHOICE":
                what = f"{a.get('kind')}: picked {nm(a.get('picked'))} from {[nm(o) for o in a.get('options', [])]}"
            elif a["type"] in ("BUY", "SELL"):
                what = nm(a.get("target"))
            elif a["type"] == "LEVEL":
                what = f"-> tier {a.get('to_tier')}"
            else:
                what = nm(a.get("card_id")) or ""
                if a.get("target"):
                    what += f" -> {nm(a['target'])}"
                if a.get("position"):
                    what += f" (slot {a['position']})"
            rec_lines.append(f"  - line {a.get('line')}: {a['type']} {what}".rstrip())
    text = "\n".join([
        "## bg-coach problem report (from the user)",
        f"- repo: `{REPO}` @ `{_git_rev()}`",
        f"- what the user saw: **{note.strip() or '(no description)'}**",
        f"- game: `{game_file or 'live game'}` · round {round_no}",
        f"- raw log: `{source}` lines {start_line}–{end_line}",
        f"- full raw slice of this round (GameState lines): `{slice_path}`",
        *([f"- screenshot the user took in-game at that moment (open it to see what the game showed): `{screenshot}`"]
          if screenshot else []),
        "", "What the app recorded for this round:", *(rec_lines or ["- (nothing)"]),
        "", f"Key raw log lines ({len(key)}; ⇒ = the option the player clicked):", "```", *key[:150],
        *(["... (truncated, see slice file)"] if len(key) > 150 else []), "```", "",
        "Compare the user's description with the raw log, find what the parser missed or got wrong in "
        "`replay.py`, fix it, and add a regression test using this log.",
    ])
    (REPORTS / f"{stamp}_round{round_no}.md").write_text(text, encoding="utf-8")
    return {"text": private(text), "slice": str(slice_path)}  # the local .md/.log keep everything


# ------------------------------------------------------------------ report for Claude
def _git_rev() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return "?"


def _log_excerpt(source: str | None, line_no: int | None, radius: int = 6) -> str:
    """The failing log line with a few lines of context (works for .gz archives)."""
    if not source or not line_no:
        return ""
    import gzip
    p = Path(source)
    if not p.exists():
        return ""
    opener = gzip.open if p.suffix == ".gz" else open
    lo, hi = max(1, line_no - radius), line_no + radius
    out = []
    with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if i > hi:
                break
            if i >= lo:
                out.append(f"{'>>' if i == line_no else '  '} {i}: {line.rstrip()[:300]}")
    return "\n".join(out)


def private(text: str) -> str:
    """Remove personal data: player names / BattleTags in log lines, and your folder names."""
    from .anonymise import anonymise_lines
    lines, _ = anonymise_lines(text.splitlines(keepends=True))
    text = "".join(lines)
    for path, label in ((DATA, "<data>"), (REPO, "<bg-coach>"), (Path.home(), "~")):
        for form in {str(path), path.as_posix(), json.dumps(str(path))[1:-1]}:
            text = text.replace(form, label)
    return text


def report_text(item: dict, kind: str = "error") -> str:
    """Compact markdown for Claude Code or a GitHub issue (personal data removed)."""
    return private(_report_text(item, kind))


def _report_text(item: dict, kind: str) -> str:
    from . import __version__
    head = [f"## bg-coach {kind} report",
            f"- bg-coach {__version__} @ `{_git_rev()}` · python {platform.python_version()} · "
            f"{platform.system()} {platform.release()}"]
    if kind == "error":
        ctx = item.get("context", {})
        head += [f"- time: {item.get('time')} · kind: **{item.get('kind')}**",
                 f"- error: `{item.get('error')}`"]
        for k, v in ctx.items():
            if k not in ("line", "excerpt"):
                head.append(f"- {k}: `{v}`")
        body = []
        if item.get("traceback"):
            body += ["", "Traceback:", "```", item["traceback"].strip()[-2500:], "```"]
        excerpt = ctx.get("excerpt") or _log_excerpt(ctx.get("source"), ctx.get("line_no"))
        if excerpt:
            body += ["", "Log lines (>> = failing line):", "```", excerpt, "```"]
        return "\n".join(head + body + ["", "Please find the cause and fix it (add a regression test)."])
    # game issues
    g = item
    head += [f"- game: `{g.get('file')}` · log: `{g.get('source')}`",
             f"- hero `{g.get('hero')}` · placement {g.get('placement')} · build {g.get('build')} · "
             f"started {g.get('start')}"]
    lines = ["", "Issues:"]
    for i in g.get("issues", []):
        extra = f" (log line {i['line_no']})" if i.get("line_no") else ""
        lines.append(f"- [{i['severity']}] {i['code']}: {i['message']}{extra}")
        if i.get("action"):
            lines.append(f"  - action: `{json.dumps(i['action'], default=str)[:300]}`")
    for i in g.get("issues", []):
        if i.get("line_no"):
            ex = _log_excerpt(g.get("source"), i["line_no"])
            if ex:
                lines += ["", f"Log around line {i['line_no']}:", "```", ex, "```"]
            break
    return "\n".join(head + lines + ["", "Please check the parser against this log and fix it (add a regression test)."])
