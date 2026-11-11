"""Local web UI: `bgcoach ui` -> http://127.0.0.1:8765

Standard library only. Binds to localhost so nothing is exposed to the network.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import analysis, archive, health, pipeline, screenshots
from . import version as V
from .live import LiveWatcher

STATIC = Path(__file__).parent / "static"
PORT = 8765


# ------------------------------------------------------------------ live broadcast
class Hub:
    def __init__(self):
        self.subs: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.last_status: dict = {}
        self.recent: list[tuple[str, dict]] = []  # events of the current game (for late joiners)
        self.watcher: LiveWatcher | None = None

    def _advise(self, data: dict, bracket: int) -> None:
        """Live pick advice with the same rules as the post-game review (advice.py):
        best = lowest average among the options that fit your build best; `close` names the runner-up
        when the difference is within chance; at low HP, `tempo` names an option that adds more
        to your board right now than the statistical favourite."""
        from . import advice, meta, synergy
        opts = data.get("options") or []
        if data.get("kind") == "HERO_PICK":
            hm = meta.heroes(bracket)
            stats = {o: advice.Stat(h["avg"], h["n"]) if (h := hm.get(o)) else None for o in opts}
        else:
            cm = meta.cards(bracket)
            stats = {o: cm.stat(o, data.get("round") or 1) for o in opts}
        vals = {o: s.avg if s else None for o, s in stats.items()}
        known = [o for o in opts if stats[o]]
        data["values"] = {o: (round(v, 2) if v is not None else None) for o, v in vals.items()}
        data["bracket"] = bracket
        best, top = (min(known, key=vals.get) if known else None), known
        if data.get("kind") != "HERO_PICK" and data.get("board_ids") is not None:
            ctx = synergy.context(data["board_ids"], data.get("history"))
            best, fits = synergy.best_option(opts, vals, ctx)
            data["fit"] = {k: [lv, why, synergy.LEVEL_WORD[lv]] for k, (lv, why) in fits.items()}
            top = [o for o in known if best and fits[o][0] == fits[best][0]]
        data["best"] = best
        if not best:
            return
        others = [o for o in top if o != best]
        runner = min(others, key=vals.get) if others else None
        if runner and not advice.clearly_better(stats[runner], stats[best]):
            data["close"] = runner  # too close to call on the numbers: pick for your board
        hp = data.get("my_hp")
        if advice.low_hp(hp) and data.get("kind") != "HERO_PICK":
            db = self.watcher.db if self.watcher and self.watcher.db else V.card_db(V.current_bg_meta_build())
            now = {o: advice.printed_stats(o, db) for o in top}
            strongest = max((o for o in top if now[o] is not None), key=lambda o: now[o], default=None)
            if strongest and strongest != best and (now.get(best) is None or now[strongest] > now[best]):
                data["tempo"] = {"card": strongest, "hp": hp, "more": now[strongest] - (now.get(best) or 0)}

    def coach(self, kind: str, data: dict) -> dict:
        """Add meta numbers to live events: option values, board strength vs same hero."""
        try:
            from . import meta
            b = live_bracket()
            if kind == "offers":
                self._advise(data, b)
            if kind in ("turn_start", "action", "combat") and data.get("hero"):
                h = meta.heroes(b).get(data["hero"])
                rnd = data.get("round")
                ref = h["warband"].get(rnd) if h and rnd else None
                mine = data.get("board_stats")
                if kind == "combat":
                    mine = sum((c.get("atk") or 0) + max(0, c.get("hp") or 0) for c in data.get("my_board") or [])
                if ref and mine is not None:
                    data["strength"] = round(mine / ref, 2)
                    data["strength_ref"] = ref
        except Exception:  # advice must never break the live feed
            pass
        return data

    def emit(self, kind: str, data: dict):
        # Snapshot now: the parser keeps mutating its dicts (a round's action list grows), and
        # replaying a mutated dict to a late-joining page would duplicate actions.
        data = json.loads(json.dumps(data, default=str))
        data = self.coach(kind, data)
        if kind == "game_end":
            threading.Thread(target=self._summary, args=(data.get("file"),), daemon=True).start()
        try:
            if self.watcher and self.watcher.db and kind != "error":  # incl. status snapshots
                data = {**data, "names": pipeline.card_names(data, self.watcher.db)}
        except Exception:
            pass
        if kind == "status":
            self.last_status = data
        if kind == "game_start":
            self.recent = []
        self.recent.append((kind, data))
        self.recent = self.recent[-600:]
        with self.lock:
            for q in list(self.subs):
                q.put((kind, data))

    def _summary(self, file: str | None):
        """Short coach verdict right after a game ends (test mode: the unsaved game)."""
        try:
            if file:
                g = next((g for g in pipeline.load_games() if g["file"] == file), None)
            else:
                g = getattr(self.watcher, "last_test_game", None)
            if g is None:
                return
            try:  # simulate this game's fights in the background (cached for the game page)
                from . import whatif
                threading.Thread(target=whatif.run, args=([g], live_bracket()),
                                 kwargs={"progress": lambda m: None}, daemon=True).start()
            except Exception:
                pass
            a = analysis.game_analysis(g, live_bracket())
            hp = a.get("hero_pick") or {}
            bad = [p for p in a.get("picks") or [] if p["loss"] >= 0.25]
            self.emit("summary", {
                "file": file, "placement": g.get("placement"), "hero": g.get("hero"),
                "mmr": (g.get("hdt") or {}).get("rating_after"), "mmr_before": (g.get("hdt") or {}).get("rating"),
                "strength": a["strength_phase"], "hero_loss": hp.get("loss"), "hero_best": hp.get("best"),
                "weak_picks": len(bad), "picks": len(a.get("picks") or []),
                "tier_round": a.get("tier_round"), "bracket": a.get("bracket")})
        except Exception as e:
            health.record_error("summary", e, file=file)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)


HUB = Hub()


# ------------------------------------------------------------------ background jobs
JOBS: dict[str, dict] = {}


def start_job(name: str, fn) -> str:
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "name": name, "status": "running", "log": [], "result": None, "error": None}
    JOBS[jid] = job

    def progress(msg):
        job["log"].append(str(msg))

    def run():
        try:
            job["result"] = fn(progress)
            job["status"] = "done"
        except Exception as e:
            err = health.record_error(f"job_{name}", e)
            job["status"], job["error"] = "failed", err
    threading.Thread(target=run, daemon=True).start()
    return jid


def job_archive(progress):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = archive.main([])
    for line in buf.getvalue().splitlines():
        progress(line)
    if code:
        raise RuntimeError("archiver reported errors:\n" + buf.getvalue())
    return {"ok": True}


def job_import(progress, force=False):
    return pipeline.import_all(force=force, progress=progress)


# ------------------------------------------------------------------ user problem reports
def problem(body: dict) -> dict:
    note = body.get("note", "")
    shot = body.get("screenshot") if body.get("screenshot") and screenshots.is_screenshot(body["screenshot"]) else None
    if body.get("live"):
        w = HUB.watcher
        rp = w.rp if w else None
        if rp is None or rp.g is None or not rp.g.turns:
            return {"error": "No live game round to report yet."}
        t = rp.g.turns[-1]
        names = pipeline.card_names(t, V.card_db(rp.g.build or V.current_bg_meta_build()))
        return health.problem_report(note, str(w.path), t["round"], t.get("line", 1), rp.line_no, t, names=names,
                                     screenshot=shot)
    g = next((g for g in pipeline.load_games() if g["file"] == body.get("game")), None)
    if g is None:
        return {"error": "game not found"}
    turns = g.get("turns") or []
    rnd = int(body.get("round") or 0)
    idx = next((i for i, t in enumerate(turns) if t["round"] == rnd), None)
    if idx is None or not g.get("source"):
        return {"error": "round not found (re-import games so rounds have log positions)"}
    t = turns[idx]
    if not t.get("line"):
        return {"error": "this game was imported before log positions existed: click Import games once"}
    end = turns[idx + 1]["line"] - 1 if idx + 1 < len(turns) else t["line"] + 400000
    names = pipeline.card_names(t, V.card_db(g.get("build") or V.current_bg_meta_build()))
    return health.problem_report(note, g["source"], rnd, t["line"], end, t, g["file"], names=names, screenshot=shot)


def replay_feeder(src: Path, dst: Path, lines_per_sec: int = 8000):
    """Test mode: write an archived log into dst bit by bit, like Hearthstone does while you play."""
    import time
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("", encoding="utf-8")
    chunk = max(1, lines_per_sec // 20)
    with pipeline.open_log(src) as fi, open(dst, "a", encoding="utf-8") as fo:
        buf = []
        for line in fi:
            buf.append(line)
            if len(buf) >= chunk:
                fo.write("".join(buf))
                fo.flush()
                buf = []
                time.sleep(0.05)
        fo.write("".join(buf))


# ------------------------------------------------------------------ coaching
def my_solo_games() -> list[dict]:
    return [g for g in pipeline.load_games() if g["mine"] and "DUO" not in (g.get("game_type") or "")]


_BRACKET = {"value": None, "at": 0.0}


def live_bracket() -> int:
    """Your MMR bracket, cached 10 minutes (cheap enough for every live event)."""
    import time
    if _BRACKET["value"] is None or time.time() - _BRACKET["at"] > 600:
        _BRACKET["value"], _BRACKET["at"] = my_bracket(), time.time()
    return _BRACKET["value"]


def my_bracket() -> int:
    from . import meta
    return meta.bracket_for(analysis.player_mmr(sorted(my_solo_games(), key=lambda g: g.get("start") or "")))


# ------------------------------------------------------------------ card images
IMG_CACHE = pipeline.DATA / "cache" / "img"
IMG_URL = {"tile": "https://art.hearthstonejson.com/v1/tiles/{id}.png",
           "art": "https://art.hearthstonejson.com/v1/256x/{id}.jpg"}
_IMG_MISSING: set = set()


CIRCLE_SIZES = {"circle32": 32, "circle64": 64}


def card_circle(card_id: str, kind: str) -> tuple[bytes, str] | None:
    """Small round thumbnail of the card art (whole art scaled down, not a cropped strip)."""
    import io
    path = IMG_CACHE / kind / f"{card_id}.png"
    if path.exists():
        return path.read_bytes(), "image/png"
    art = card_image(card_id, "art")
    if art is None:
        return None
    from PIL import Image, ImageDraw
    size, scale = CIRCLE_SIZES[kind], 4  # draw 4x then shrink = smooth edges
    big = size * scale
    img = Image.open(io.BytesIO(art[0])).convert("RGB")
    w, h = img.size
    side = int(min(w, h) * 0.86)  # the art's centre (portrait), lightly zoomed
    left, top = (w - side) // 2, int((h - side) * 0.35)
    img = img.crop((left, top, left + side, top + side)).resize((big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    ring = (217, 165, 58, 255) if card_id.endswith("_G") or "BaconUps" in card_id else (70, 76, 90, 255)
    ImageDraw.Draw(out).ellipse((scale, scale, big - scale - 1, big - scale - 1), outline=ring, width=3 * scale)
    out = out.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return buf.getvalue(), "image/png"


def card_image(card_id: str, kind: str) -> tuple[bytes, str] | None:
    """Card art from HearthstoneJSON, downloaded once and cached on disk."""
    import re
    import urllib.request
    if kind in CIRCLE_SIZES:
        return card_circle(card_id, kind) if re.fullmatch(r"[A-Za-z0-9_]{2,60}", card_id) else None
    if kind not in IMG_URL or not re.fullmatch(r"[A-Za-z0-9_]{2,60}", card_id):
        return None
    ext = "png" if kind == "tile" else "jpg"
    ctype = "image/png" if ext == "png" else "image/jpeg"
    candidates = [card_id, re.sub(r"_SKIN_\w+$", "", card_id), re.sub(r"_G$", "", card_id)]
    for cid in dict.fromkeys(candidates):
        path = IMG_CACHE / kind / f"{cid}.{ext}"
        if path.exists():
            return path.read_bytes(), ctype
        if (kind, cid) in _IMG_MISSING:
            continue
        try:
            req = urllib.request.Request(IMG_URL[kind].format(id=cid), headers=V.UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return data, ctype
        except Exception:
            _IMG_MISSING.add((kind, cid))
    return None


# ------------------------------------------------------------------ cached version info
_version_cache: dict = {}


def version_info() -> dict:
    if _version_cache:
        return _version_cache
    build, session = V.latest_client_build()
    meta = V.current_bg_meta_build()
    p, mp = V.patch_for_build(build) if build else {}, V.patch_for_build(meta)
    pool = V.blizzard_bg_pool()
    _version_cache.update({
        "client_build": build, "session": session,
        "patch": p.get("version"), "patch_name": p.get("name"), "patch_date": str(p.get("date"))[:10],
        "latest_build": meta, "latest_patch": mp.get("version"),
        "outdated": bool(build and build < meta),
        "pool": {k: len(v) for k, v in pool.items()},
    })
    return _version_cache


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "bgcoach"

    def log_message(self, *args):  # keep the console quiet
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, e: Exception):
        err = health.record_error("ui_api", e, path=self.path)
        self._json({"error": err["error"], "error_id": err["id"]}, 500)

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # browser closed the tab / navigated away: not an error
        except Exception as e:
            self._fail(e)

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            self._fail(e)

    def _get(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        if path in ("/", "/index.html"):
            body = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ("/favicon.ico", "/icon.png"):
            ico = STATIC / "icon.png"
            if not ico.exists():
                return self._json({"error": "no icon"}, 404)
            body = ico.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/version":
            self._json(version_info())
        elif path == "/api/games":
            games = pipeline.load_games()
            shots = screenshots.list_screenshots()
            rows = [pipeline.summary(g) | {"shots": len(screenshots.for_game(g, shots))} for g in reversed(games)]
            db = V.card_db(V.current_bg_meta_build())
            self._json({"games": rows, "names": pipeline.card_names([r["hero"] for r in rows], db)})
        elif path.startswith("/api/games/"):
            name = unquote(path.rsplit("/", 1)[1])
            g = next((g for g in pipeline.load_games() if g["file"] == name), None)
            if g is None:
                return self._json({"error": "not found"}, 404)
            db = V.card_db(g.get("build") or V.current_bg_meta_build())
            g["names"] = pipeline.card_names(g, db)
            g["screenshots"] = screenshots.for_game(g)
            try:
                from .decisions import all_decisions
                b = my_bracket()
                g["coach"] = analysis.game_analysis(g, b)
                g["coach"]["decisions"] = all_decisions(g, b, g["coach"]["strength"])
                g["names"].update(pipeline.card_names(g["coach"], db))
            except Exception as e:  # meta offline etc. must not break the page
                g["coach_error"] = health.record_error("coach", e, game=name)["error"]
            self._json(g)
        elif path == "/api/improve":
            rep = analysis.coach_report(my_solo_games())
            rep["names"] = pipeline.card_names(rep, V.card_db(V.current_bg_meta_build()))
            self._json(rep)
        elif path == "/api/health":
            games = pipeline.load_games()
            bad = [pipeline.summary(g) | {"issues": g["issues"]} for g in reversed(games)
                   if g["issues"] and g["mine"]]
            mine = [g for g in games if g["mine"] and g.get("hdt")]
            agree = {
                "matched": len(mine),
                "placement": sum(g["hdt"]["placement"] == g.get("placement") for g in mine),
                "board": sum(sorted(c["card_id"] for c in g.get("final_board", [])) == g["hdt"]["board"]
                             for g in mine),
            }
            self._json({"errors": health.list_errors(), "games": bad, "hdt_agreement": agree,
                        "total_games": len(games)})
        elif path == "/api/report":
            if "error" in qs:
                item = next((e for e in health.list_errors(1000) if e["id"] == qs["error"][0]), None)
                text = health.report_text(item, "error") if item else "error not found"
            else:
                g = next((g for g in pipeline.load_games() if g["file"] == qs.get("game", [""])[0]), None)
                text = health.report_text(g, "game") if g else "game not found"
            self._json({"text": text})
        elif path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[1])
            self._json(job or {"error": "no such job"}, 200 if job else 404)
        elif path.startswith("/api/card/"):  # /api/card/<tile|art>/<card_id>
            parts = path.split("/")
            img = card_image(parts[-1], parts[-2]) if len(parts) >= 5 else None
            if img is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data, ctype = img
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=604800")
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/screenshot":
            sp = qs.get("path", [""])[0]
            if not screenshots.is_screenshot(sp):
                return self._json({"error": "not a Hearthstone screenshot"}, 404)
            body = Path(sp).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/live/events":
            self._sse()
        else:
            self._json({"error": "not found"}, 404)

    def _post(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        if path == "/api/jobs/archive":
            self._json({"id": start_job("archive", job_archive)})
        elif path == "/api/jobs/import":
            self._json({"id": start_job("import", lambda p: job_import(p, force=bool(body.get("force"))))})
        elif path == "/api/quit":  # Quit button / overlay menu: stop everything
            self._json({"ok": True})
            threading.Thread(target=_quit, daemon=True).start()
        elif path == "/api/problem":
            self._json(problem(body))
        elif path == "/api/errors/clear":
            health.clear_errors()
            self._json({"ok": True})
        elif path == "/api/errors/client":  # JS errors from the page itself
            err = health.record_error("ui_page", None, error=body.get("message", ""),
                                      traceback=body.get("stack", ""), where=body.get("where"))
            self._json({"error_id": err["id"]})
        else:
            self._json({"error": "not found"}, 404)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-BGCoach-PID", str(os.getpid()))  # an overlay checks it is talking to its own app
        self.end_headers()
        q = HUB.subscribe()
        try:
            if HUB.last_status:
                q.put(("status", HUB.last_status))
            for kind, data in list(HUB.recent):
                q.put((kind, data))
            while True:
                try:
                    kind, data = q.get(timeout=15)
                    msg = f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
                except queue.Empty:
                    msg = ": keepalive\n\n"
                self.wfile.write(msg.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            HUB.unsubscribe(q)


def _auto_archive(every_min: int = 30):
    """While the app is open: archive new logs + import new games now and every 30 minutes."""
    import time
    while True:
        try:
            job_archive(lambda m: None)
            pipeline.import_all(progress=lambda m: None)
            from . import whatif  # simulate new games' fights (cached; skips games already done)
            recent = sorted(my_solo_games(), key=lambda g: g.get("start") or "")[-10:]
            whatif.run(recent, live_bracket(), progress=lambda m: None)
        except Exception as e:
            HUB.emit("error", health.record_error("auto_archive", e))
        time.sleep(every_min * 60)


_SERVER: dict = {}


def _quit():
    import time
    time.sleep(0.3)  # let the HTTP reply go out
    httpd = _SERVER.get("httpd")
    if httpd is not None:
        httpd.shutdown()


def _start_overlay(port: int):
    import subprocess
    import sys
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen([sys.executable, "-m", "bgcoach.overlay", str(port), str(os.getpid())],
                                creationflags=flags)
    except Exception as e:
        health.record_error("overlay_start", e)
        return None


def serve(port: int = PORT, open_browser: bool = True, follow: Path | None = None, auto_archive: bool = True,
          test_log: Path | None = None, speed: int = 8000, overlay: bool = True):
    url = f"http://127.0.0.1:{port}/"
    ThreadingHTTPServer.allow_reuse_address = False  # Windows would otherwise let two copies share the port
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"bg-coach is already running, opening {url}")
        print("(to load new code: close the other bg-coach window first, then start it again)")
        if open_browser:
            webbrowser.open(url)
        return
    httpd.daemon_threads = True
    _SERVER["httpd"] = httpd
    if test_log is not None:  # test mode: pretend an archived game is being played right now
        follow = pipeline.DATA / "test_replay" / "Power.log"
        follow.parent.mkdir(parents=True, exist_ok=True)
        follow.write_text("", encoding="utf-8")
        threading.Timer(3.0, replay_feeder, args=(test_log, follow, speed)).start()
        auto_archive = False
        print(f"TEST MODE: replaying {test_log} into the Live tab ({speed} lines/s)")
    HUB.watcher = LiveWatcher(HUB.emit, follow=follow)
    HUB.watcher.start()
    if auto_archive:
        threading.Thread(target=_auto_archive, daemon=True, name="bgcoach-archive").start()
    overlay_proc = _start_overlay(port) if overlay else None
    print(f"bg-coach UI running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if overlay_proc:
            overlay_proc.terminate()
        HUB.watcher.stop()
        httpd.server_close()
