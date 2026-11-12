"""Always-on-top live panel to glance at while playing (HDT-style).

  ● green  = recording; every action so far verified against the log
  ● red    = a self-check failed: press Print Screen in Hearthstone, report after the game
  ● grey   = no game running        ● amber = bg-coach app not running

Shows round · tier · gold · HP as the app sees them, then a live feed of your last actions with the
card art, so you can compare with the game at a glance.
Starts as a small icon (ring colour = status, number = round): click it for the full live feed,
"–" shrinks it back. Drag to move (remembered) · double-click: open the full app · ✕ close.
Needs Hearthstone in windowed / "Fullscreen Windowed" (borderless) mode, like HDT's overlay.
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser

from .paths import DATA, FONT, MONO

POS_FILE = DATA / "overlay_pos.json"
GREEN, RED, GREY, AMBER = "#45c07a", "#e5534b", "#7a8090", "#e0a23a"
BG, BG2, FG, MUTED = "#111318", "#1b1f27", "#e6e8ee", "#9097a6"
TYPE_COLOR = {"BUY": "#5aa2f0", "SELL": "#e5534b", "LEVEL": "#e0a23a", "REFRESH": MUTED, "FREEZE": MUTED,
              "PLAY": FG, "CAST": "#c39bff", "HERO_POWER": "#c39bff", "MOVE": MUTED, "PICK": "#e0a23a",
              "DARK_GIFT": "#c39bff", "ACTIVATE": "#c39bff"}
FEED_ROWS = 10


ORPHAN_AFTER_S = 60  # app gone this long → close (an overlay started by an app that has quit or crashed)


def _stream(url: str, out: queue.Queue, app_pid: int | None = None):
    """Read the app's server-sent events forever (reconnects).

    With `app_pid` (the app that started this overlay), stop with `_orphan` when that app is gone:
    another app instance answering on the port, or nobody answering for ORPHAN_AFTER_S seconds.
    Without it (`bgcoach overlay`), keep reconnecting forever.
    """
    last_seen = time.monotonic()
    while True:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                pid = r.headers.get("X-BGCoach-PID")
                if app_pid and pid and pid != str(app_pid):
                    out.put(("_orphan", {}))
                    return
                last_seen = time.monotonic()
                out.put(("_connected", {}))
                kind = None
                for raw in r:
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if line.startswith("event: "):
                        kind = line[7:].strip()
                    elif line.startswith("data: ") and kind:
                        try:
                            out.put((kind, json.loads(line[6:])))
                        except ValueError:
                            pass
        except Exception:
            out.put(("_disconnected", {}))
        if app_pid and time.monotonic() - last_seen > ORPHAN_AFTER_S:
            out.put(("_orphan", {}))
            return
        time.sleep(3)


class Overlay:
    def __init__(self, port: int = 8765, app_pid: int | None = None):
        self.app_pid = app_pid
        self.base = f"http://127.0.0.1:{port}/"
        self.q: queue.Queue = queue.Queue()
        self.ok = self.failed = 0
        self.in_game = self.connected = False
        self.names: dict[str, str] = {}
        self.images: dict[str, tk.PhotoImage | None] = {}
        self.waiting: dict[str, list[tk.Label]] = {}
        self.feed_visible = True
        self.compact = self._load_compact()

        root = self.root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        root.configure(bg=BG)
        x, y = self._load_pos()
        root.geometry(f"+{x}+{y}")

        # small icon (default): status-coloured ring with the round number; click = open the panel
        self.mini = tk.Canvas(root, width=30, height=30, bg=BG, highlightthickness=0, cursor="hand2")
        self.mini_ring = self.mini.create_oval(3, 3, 27, 27, outline=GREY, width=4)
        self.mini_txt = self.mini.create_text(15, 15, text="", fill=FG, font=(FONT, 9, "bold"))
        self._bind_window(self.mini, click=self._expand)

        outer = self.outer = tk.Frame(root, bg=BG, padx=8, pady=6)
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(0, 6))
        self.title = tk.Label(top, text="bg-coach · connecting…", fg=FG, bg=BG, font=(FONT, 10, "bold"))
        self.title.pack(side="left")
        close = tk.Label(top, text=" ✕", fg=MUTED, bg=BG, font=(FONT, 10), cursor="hand2")
        close.pack(side="right")
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Open bg-coach", command=lambda: webbrowser.open(self.base))
        menu.add_command(label="Hide this overlay", command=root.destroy)
        menu.add_separator()
        menu.add_command(label="Quit bg-coach (stop recording)", command=self._quit_app)
        close.bind("<Button-1>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        shrink = tk.Label(top, text=" –", fg=MUTED, bg=BG, font=(FONT, 11, "bold"), cursor="hand2")
        shrink.pack(side="right")
        shrink.bind("<Button-1>", lambda e: self._shrink())
        self.toggle = tk.Label(top, text=" ▾", fg=MUTED, bg=BG, font=(FONT, 10), cursor="hand2")
        self.toggle.pack(side="right")
        self.toggle.bind("<Button-1>", lambda e: self._toggle_feed())

        self.stats = tk.Label(outer, text="", fg=FG, bg=BG, font=(FONT, 11, "bold"))
        self.stats.pack(anchor="w", pady=(2, 0))
        self.checks = tk.Label(outer, text="", fg=MUTED, bg=BG, font=(FONT, 9), wraplength=300, justify="left")
        self.checks.pack(anchor="w")
        self.strength = tk.Label(outer, text="", fg=MUTED, bg=BG, font=(FONT, 10, "bold"))
        self.strength.pack(anchor="w")
        # who you fight next (as the game announces it) + the last board you saw them with
        self.nextopp = tk.Label(outer, text="", fg=FG, bg=BG, font=(FONT, 9), wraplength=300, justify="left")
        self.nextopp.pack(anchor="w")
        # after a game: the one thing to take into the next game (packed when the summary arrives)
        self.lesson = tk.Label(outer, text="", fg=FG, bg="#1f1a10", font=(FONT, 9), wraplength=300,
                               justify="left", anchor="w", padx=6, pady=4)
        self.advice = tk.Frame(outer, bg="#1f1a10", padx=4, pady=3)  # shown only while you choose
        self.advice_rows: list[tk.Widget] = []
        self.offers: dict | None = None
        self.auto_expanded = False
        self.feed = tk.Frame(outer, bg=BG)
        self.feed.pack(fill="x", pady=(4, 0))
        self.rows: list[tk.Frame] = []

        for w in (root, outer, top, self.title, self.stats, self.checks, self.dot):
            self._bind_window(w)
        self._apply_mode()
        threading.Thread(target=_stream, args=(self.base + "api/live/events", self.q, self.app_pid),
                         daemon=True).start()
        root.after(150, self._pump)
        root.after(2000, self._keep_on_top)

    def _quit_app(self):
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + "api/quit", data=b"{}", method="POST"), timeout=3)
        except Exception:
            pass
        self.root.destroy()

    # -------------------------------------------------------------- window
    def _bind_window(self, w, click=None):
        w.bind("<ButtonPress-1>", self._start_drag)
        w.bind("<B1-Motion>", self._drag)
        w.bind("<ButtonRelease-1>", lambda e: self._release(e, click))
        w.bind("<Double-Button-1>", lambda e: webbrowser.open(self.base))

    def _release(self, e, click):
        moved = abs(e.x_root - self._press[0]) + abs(e.y_root - self._press[1]) > 4
        self._save_pos()
        if click and not moved:
            click()

    def _apply_mode(self):
        if self.compact:
            self.outer.pack_forget()
            self.mini.pack()
        else:
            self.mini.pack_forget()
            self.outer.pack(fill="both")
        self._save_pos()

    def _expand(self):
        self.compact = False
        self._apply_mode()

    def _shrink(self):
        self.compact = True
        self._apply_mode()

    def _load_compact(self) -> bool:
        try:
            return bool(json.loads(POS_FILE.read_text(encoding="utf-8")).get("compact", True))
        except Exception:
            return True

    def _load_pos(self):
        import os
        if os.environ.get("BGCOACH_OVERLAY_POS"):  # testing
            x, y = os.environ["BGCOACH_OVERLAY_POS"].split(",")
            return int(x), int(y)
        try:
            p = json.loads(POS_FILE.read_text(encoding="utf-8"))
            return int(p["x"]), int(p["y"])
        except Exception:
            return 20, 200

    def _save_pos(self):
        try:
            POS_FILE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                                            "compact": getattr(self, "compact", True)}), encoding="utf-8")
        except Exception:
            pass

    def _start_drag(self, e):
        self._press = (e.x_root, e.y_root)
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _keep_on_top(self):
        self.root.attributes("-topmost", True)
        self.root.after(2000, self._keep_on_top)

    def _toggle_feed(self):
        self.feed_visible = not self.feed_visible
        if self.feed_visible:
            self.feed.pack(fill="x", pady=(4, 0))
            self.toggle.config(text=" ▾")
        else:
            self.feed.pack_forget()
            self.toggle.config(text=" ▸")

    # -------------------------------------------------------------- card art
    def _image(self, card_id: str | None, label: tk.Label):
        if not card_id:
            return
        if card_id in self.images:
            if self.images[card_id] is not None:
                label.config(image=self.images[card_id])
            return
        self.waiting.setdefault(card_id, []).append(label)
        if len(self.waiting[card_id]) == 1:
            threading.Thread(target=self._fetch, args=(card_id,), daemon=True).start()

    def _fetch(self, card_id: str):
        try:
            with urllib.request.urlopen(f"{self.base}api/card/circle32/{card_id}", timeout=20) as r:
                self.q.put(("_img", {"id": card_id, "data": base64.b64encode(r.read()).decode()}))
        except Exception:
            self.q.put(("_img", {"id": card_id, "data": None}))

    def _got_image(self, card_id: str, data: str | None):
        img = None
        if data:
            try:
                img = tk.PhotoImage(data=data)  # 32x32 round thumbnail
            except tk.TclError:
                img = None
        self.images[card_id] = img
        for lbl in self.waiting.pop(card_id, []):
            if img is not None and lbl.winfo_exists():
                lbl.config(image=img)

    # -------------------------------------------------------------- feed
    def _add_row(self, label: str, color: str, text: str, card_id: str | None = None,
                 strike: bool = False, bg: str = BG2):
        row = tk.Frame(self.feed, bg=bg)
        tag = tk.Label(row, text=label, fg=color, bg=bg, font=(MONO, 9, "bold"), width=6, anchor="w")
        tag.pack(side="left", padx=(4, 2))
        art = tk.Label(row, bg=bg, bd=0)
        art.pack(side="left")
        font = (FONT, 9, "overstrike") if strike else (FONT, 9)
        txt = tk.Label(row, text=text if len(text) <= 30 else text[:29] + "…", fg=MUTED if strike else FG, bg=bg, font=font, anchor="w")
        txt.pack(side="left", padx=4)
        for w in (row, tag, art, txt):
            self._bind_window(w)
        self._image(card_id, art)
        row.pack(fill="x", pady=1)
        self.rows.append(row)
        while len(self.rows) > FEED_ROWS:
            self.rows.pop(0).destroy()

    # -------------------------------------------------------------- live advice
    def _show_offers(self, d: dict):
        for w in self.advice_rows:
            w.destroy()
        self.advice_rows = []
        vals, best = d.get("values") or {}, d.get("best")
        if not any(v is not None for v in vals.values()):
            return
        title = "Hero: avg place at your MMR" if d.get("kind") == "HERO_PICK" else \
            f"Pick (R{d.get('round')}): avg place, ★ = best that fits"
        t = tk.Label(self.advice, text=title, fg=AMBER, bg="#1f1a10", font=(FONT, 9, "bold"))
        t.pack(anchor="w")
        self.advice_rows.append(t)
        for opt in d.get("options") or []:
            v = vals.get(opt)
            row = tk.Frame(self.advice, bg="#1f1a10")
            art = tk.Label(row, bg="#1f1a10", bd=0)
            art.pack(side="left")
            is_best = opt == best
            fit = (d.get("fit") or {}).get(opt)
            mark = {3: " ✓", 2: "", 1: " ~side", 0: " ✗off"}.get(fit[0], "") if fit else ""
            txt = f"{'★ ' if is_best else ''}{self.n(opt)}{mark}"
            tk.Label(row, text=txt if len(txt) <= 26 else txt[:25] + "…", fg=GREEN if is_best else FG, bg="#1f1a10",
                     font=(FONT, 9, "bold" if is_best else "normal")).pack(side="left", padx=4)
            tk.Label(row, text=f"{v:.2f}" if v is not None else "?", fg=GREEN if is_best else MUTED, bg="#1f1a10",
                     font=(MONO, 10, "bold")).pack(side="right", padx=4)
            row.pack(fill="x")
            self._image(opt, art)
            self.advice_rows.append(row)
        notes = []
        if d.get("close"):
            notes.append(f"≈ {self.n(best)} vs {self.n(d['close'])}: too close to call, pick for your board")
        if d.get("tempo"):
            tp = d["tempo"]
            notes.append(f"♥ {tp['hp']} HP: {self.n(tp['card'])} adds more now (+{tp['more']} stats)")
        for txt in notes:
            lbl = tk.Label(self.advice, text=txt, fg=MUTED, bg="#1f1a10", font=(FONT, 8), wraplength=250, justify="left")
            lbl.pack(anchor="w")
            self.advice_rows.append(lbl)
        if not self.advice.winfo_ismapped():
            self.advice.pack(fill="x", pady=(4, 0), before=self.feed)
        if self.compact:  # pop open while you choose, shrink back after
            self.auto_expanded = True
            self._expand()

    def _hide_offers(self):
        if self.advice.winfo_ismapped():
            self.advice.pack_forget()
        if self.auto_expanded:
            self.auto_expanded = False
            self._shrink()

    def _show_strength(self, d: dict):
        r, rnd = d.get("strength"), d.get("round")
        if r is None:
            return
        color = GREEN if r >= 1 else AMBER if r >= 0.8 else RED
        focus = "FOCUS · " if rnd and 6 <= rnd <= 9 else ""
        when = "at the fight" if d.get("_fight") else "now"
        self.strength.config(text=f"{focus}Board {r:.0%} of same-hero avg {when} (R{rnd})", fg=color)

    def _clear_feed(self):
        for r in self.rows:
            r.destroy()
        self.rows = []

    # -------------------------------------------------------------- state
    def _set_dot(self):
        if not self.connected:
            color = AMBER
        elif not self.in_game:
            color = GREY
        else:
            color = RED if self.failed else GREEN
        self.dot.itemconfig(self.dot_id, fill=color)
        self.mini.itemconfig(self.mini_ring, outline=color)
        if self.failed:
            self.checks.config(text=f"✗ {self.failed} check failed: press Print Screen, report after the game", fg=RED)
        elif self.in_game:
            self.checks.config(text=f"✓ {self.ok} actions verified against the game log", fg=MUTED)
        else:
            self.checks.config(text="")

    def _pump(self):
        try:
            for _ in range(500):
                kind, d = self.q.get_nowait()
                self._handle(kind, d)
        except queue.Empty:
            pass
        self._set_dot()
        self.root.after(150, self._pump)

    def n(self, cid):
        return self.names.get(cid, cid) if cid else ""

    def _handle(self, kind: str, d: dict):
        self.names.update(d.get("names") or {})
        n = self.n
        if kind == "_img":
            self._got_image(d["id"], d["data"])
        elif kind == "_connected":
            self.connected = True
            self.title.config(text="bg-coach · waiting for a game")
        elif kind == "_disconnected":
            self.connected = False
            self.title.config(text="bg-coach · app not running")
        elif kind == "_orphan":  # the app that opened this overlay has quit or crashed
            self.root.after(0, self.root.destroy)  # after this pump pass, so nothing touches a dead window
        elif kind == "status":
            self.in_game = bool(d.get("in_game"))
            snap = d.get("snapshot") or {}
            if snap.get("round"):
                self._show(snap.get("round"), snap.get("tier"), snap.get("gold"), snap.get("hp"), None)
            if not self.in_game:
                self.title.config(text="bg-coach · no game running")
        elif kind == "game_start":
            self.in_game, self.ok, self.failed = True, 0, 0
            self._clear_feed()
            if self.lesson.winfo_ismapped():  # last game's lesson: gone once the new game starts
                self.lesson.pack_forget()
                if self.auto_expanded:
                    self.auto_expanded = False
                    self._shrink()
            self.title.config(text=f"bg-coach · recording · patch {d.get('patch')}")
            self.stats.config(text="Hero selection")
        elif kind == "round":
            self.in_game = True
            self.title.config(text="bg-coach · recording")
            self.nextopp.config(text="")
            self._add_row(f"R{d.get('round')}", MUTED, "──────── new round ────────", bg=BG)
        elif kind == "next_opponent":
            self.nextopp.config(text=self._next_text(d), fg=RED if (d.get("last_seen") or {}).get("highroll") else FG)
        elif kind == "next_opponent_odds":
            base = self.nextopp.cget("text").split("\n⚔")[0]
            self.nextopp.config(text=f"{base}\n⚔ your board vs that: {d['win']:.0f}% win · {d['tie']:.0f}% tie · "
                                     f"{d['loss']:.0f}% loss (they've grown since)")
        elif kind == "turn_start":
            self._show(d.get("round"), d.get("tier"), d.get("gold"), d.get("hp"), d.get("armor"))
            self._show_strength(d)
        elif kind == "offers":
            self.offers = d
            self._show_offers(d)
        elif kind == "summary":  # between games: the one thing to take into the next game
            les = d.get("lesson")
            if d.get("good_game"):  # a top-2 game without a turning point: no "mistake" headline
                won = "You won!" if d.get("placement") == 1 else "Good game: no turning point to fix."
                text = f"#{d.get('placement')} · {won}" + (
                    f"\nSmall thing: {les['headline']}" if les else "")
            elif les:
                text = f"#{d.get('placement')} · THE ONE THING\n{les['headline']}\nNext game: {les.get('habit') or ''}"
            else:
                text = f"#{d.get('placement')} · nothing big to fix this game"
            self.lesson.config(text=text.strip())
            if not self.lesson.winfo_ismapped():
                self.lesson.pack(fill="x", pady=(4, 0), before=self.feed)
            if self.compact:
                self.auto_expanded = True
                self._expand()
        elif kind == "action":
            self._show_strength(d)
            t = d["type"]
            if t == "LEVEL":
                self._add_row("LEVEL", TYPE_COLOR["LEVEL"], f"→ Tier {d.get('to_tier')}   ({d.get('gold')}g)")
            elif t in ("REFRESH", "FREEZE", "DARK_GIFT", "END_TURN"):
                self._add_row(t.replace("_", " ")[:6], TYPE_COLOR.get(t, MUTED), f"({d.get('gold')}g)")
            else:
                cid = d.get("target") if t in ("BUY", "SELL") else d.get("card_id")
                extra = f" → {n(d['target'])}" if t in ("CAST", "HERO_POWER") and d.get("target") else ""
                self._add_row(t.replace("HERO_POWER", "POWER")[:6], TYPE_COLOR.get(t, FG),
                              f"{n(cid)}{extra}  ({d.get('gold')}g)", card_id=cid)
        elif kind == "choice":
            off = self.offers or {}
            best = off.get("best") if off.get("kind") == d.get("kind") else None
            note = "" if not best else "  ✓ best" if best == d.get("picked") else f"  (best: {n(best)})"
            label = "HERO" if d.get("kind") == "HERO_PICK" else "PICK"
            self._add_row(label, GREEN if note.strip().startswith("✓") else TYPE_COLOR["PICK"],
                          f"{n(d.get('picked'))}{note}", card_id=d.get("picked"))
            self.offers = None
            self._hide_offers()
        elif kind == "combat":
            self._show_strength({**d, "_fight": True})
            res = d.get("result", "")
            color = GREEN if res == "WIN" else RED if res == "LOSS" else MUTED
            dmg = f"-{d['damage_taken']}" if res == "LOSS" else f"+{d.get('damage_dealt') or 0}" if res == "WIN" else "0"
            arm = f"+{d['armor_after']}" if d.get("armor_after") else ""
            word = {"WIN": "won", "LOSS": "lost", "TIE": "tie"}.get(res, res.lower())
            self._add_row("FIGHT", color, f"{word} {dmg} · {d.get('hp_after')}{arm} HP · {n(d.get('opp_hero'))}",
                          card_id=d.get("opp_hero"))
        elif kind == "checks":
            self.ok, self.failed = d.get("ok", 0), d.get("failed", 0)
        elif kind == "check_failed":
            self.failed += 1
            self._add_row("✗ CHECK", RED, f"{d.get('action')} {n(d.get('card'))}: {d.get('expected')}?",
                          card_id=d.get("card"), bg="#3a1c1c")
        elif kind == "not_applied":
            self._add_row("LATE", MUTED, f"{d.get('action')} {n(d.get('card'))}: turn ended first",
                          card_id=d.get("card"), strike=True)
        elif kind == "game_end":
            self.in_game = False
            self.title.config(text=f"bg-coach · game saved · place {d.get('placement')}")
        elif kind in ("parse_error", "error"):
            self.failed += 1
            self._add_row("✗ ERROR", RED, str(d.get("error", ""))[:40], bg="#3a1c1c")

    def _show(self, rnd, tier, gold, hp, armor):
        self.mini.itemconfig(self.mini_txt, text=str(rnd or ""))
        arm = f"+{armor}" if armor else ""
        self.stats.config(text=f"Round {rnd} · Tier {tier} · {gold if gold is not None else '?'}g · {hp}{arm} HP")

    def _next_text(self, d: dict) -> str:
        who = f"Next: {self.n(d.get('opp_hero'))} · T{d.get('opp_tier')} · {d.get('opp_hp')} HP"
        if d.get("opp_triples"):
            who += f" · {d['opp_triples']} triples"
        last = d.get("last_seen")
        if not last:
            return who + "\n(you haven't fought them yet)"
        hr = " HIGHROLL" if last.get("highroll") else ""
        ratio = f", {last['ratio']:.1f}× their hero's avg{hr}" if last.get("ratio") else ""
        ago = (d.get("round") or 0) - last["round"]
        old = f" ({ago} rounds ago: too old to compare)" if ago > 3 else ""
        proj = f"\n≈ {last['projected']} stats now if they grew like an average player" if last.get("projected") else ""
        return (f"{who}\nLast seen R{last['round']}{old}: {last['stats']} stats{ratio} · {last.get('kw_text', '')}"
                f" · yours now {d.get('my_stats')}{proj}")

    def run(self):
        self.root.mainloop()


def main(port: int = 8765, app_pid: int | None = None):
    Overlay(port, app_pid).run()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8765, int(sys.argv[2]) if len(sys.argv) > 2 else None)
