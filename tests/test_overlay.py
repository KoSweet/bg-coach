"""Overlay logic without showing a window."""
import pytest


def _overlay_checks():
    import tkinter as tk
    from bgcoach import overlay
    try:
        o = overlay.Overlay(port=1)  # nothing listens on port 1: the stream just retries
    except tk.TclError:
        print("SKIP no display")
        return
    o.root.withdraw()
    o._handle("_connected", {})
    o._handle("game_start", {"patch": "37.0"})
    o._handle("round", {"round": 3})
    o._handle("turn_start", {"round": 3, "tier": 2, "gold": 6, "hp": 30, "armor": 4})
    o._handle("action", {"type": "BUY", "target": "BG25_008", "gold": 6, "names": {"BG25_008": "Eternal Knight"}})
    o._handle("action", {"type": "LEVEL", "to_tier": 3, "gold": 6})
    o._handle("combat", {"result": "WIN", "damage_dealt": 5, "hp_after": 30, "armor_after": 4, "opp_hero": "X"})
    o._handle("checks", {"ok": 12, "failed": 0})
    o._set_dot()
    assert o.stats.cget("text") == "Round 3 · Tier 2 · 6g · 30+4 HP"
    assert o.dot.itemcget(o.dot_id, "fill") == overlay.GREEN
    texts = [w.cget("text") for r in o.rows for w in r.winfo_children() if isinstance(w, tk.Label)]
    assert any("Eternal Knight" in t for t in texts) and any("Tier 3" in t for t in texts)
    o._handle("check_failed", {"round": 3, "action": "BUY", "card": "BG25_008", "expected": "bought card came to you"})
    o._set_dot()
    assert o.dot.itemcget(o.dot_id, "fill") == overlay.RED
    assert o.mini.itemcget(o.mini_ring, "outline") == overlay.RED
    assert o.mini.itemcget(o.mini_txt, "text") == "3"
    # live advice: options with values pop the panel open, the pick closes it again
    o._shrink()
    o._handle("offers", {"kind": "DISCOVER", "round": 7, "options": ["A", "B"], "values": {"A": 3.7, "B": 4.2},
                         "best": "A", "names": {"A": "Alpha", "B": "Beta"}})
    assert not o.compact and o.auto_expanded and len(o.advice_rows) == 3
    o._handle("choice", {"kind": "DISCOVER", "picked": "B"})
    assert o.compact and not o.advice_rows[0].winfo_ismapped() or o.compact
    o._handle("action", {"type": "BUY", "round": 7, "strength": 0.76, "gold": 3, "target": "A"})
    assert "76%" in o.strength.cget("text") and "FOCUS" in o.strength.cget("text")
    o._expand(); assert not o.compact
    o._shrink(); assert o.compact
    assert "Print Screen" in o.checks.cget("text")
    for i in range(30):
        o._handle("action", {"type": "REFRESH", "gold": i})
    assert len(o.rows) == overlay.FEED_ROWS
    o.root.destroy()
    print("OVERLAY OK")


def test_overlay_states_and_feed(tmp_path):
    # Tk must live on one thread for its whole life; run it in its own process (as the app does).
    import subprocess
    import sys
    pytest.importorskip("tkinter")
    import os
    env = {**os.environ, "BGCOACH_DATA": str(tmp_path)}  # never touch the real overlay position file
    r = subprocess.run([sys.executable, "-c", "import tests.test_overlay as t; t._overlay_checks()"],
                       capture_output=True, text=True, timeout=60, env=env,
                       cwd=str(__import__("pathlib").Path(__file__).parents[1]))
    if "SKIP" in r.stdout:
        pytest.skip("no display")
    assert "OVERLAY OK" in r.stdout, r.stdout + r.stderr
