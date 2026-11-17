"""Tactical Effectiveness (FM27): the game's own numbers, rebuilt from the raw per-player inputs it keeps in memory.

The game works TE out on request (Training > Tactical Effectiveness, a player's Development > Tactical
Effectiveness) from a 0x40-byte record per player; reader/tactical.py finds those records. The formulas below are the
game's, taken from its code (build a80b7a733c8d) and checked against both TE screens: float32 maths, rounding by
truncating x + 0.5, every dial on screen = floor(value / 10).
"""
from __future__ import annotations

import numpy as np

F = np.float32

AREAS = [  # (key, label, phase) in the order the record holds them
    ("passing_style", "Passing Style", "ip"),
    ("build_up", "Build Up", "ip"),
    ("chance_creation", "Chance Creation", "ip"),
    ("ip_shape", "In Possession Shape", "ip"),
    ("line_of_engagement", "Line of Engagement", "oop"),
    ("pressing_intensity", "Pressing Intensity", "oop"),
    ("pressing_trap", "Pressing Trap", "oop"),
    ("oop_shape", "Out Of Possession Shape", "oop"),
]

CATEGORIES = [  # (key, label, weight in the overall)
    ("understanding", "Tactical Understanding", 0.5),
    ("buy_in", "Buy-in", 0.2),
    ("ability", "Player Ability", 0.15),
    ("next_match", "Next Match", 0.15),
]


def _r(x) -> int:
    """The game's rounding: truncate x +/- 0.5 (float32)."""
    x = F(x)
    return int(np.trunc(x + F(0.5) if x >= 0 else x - F(0.5)))


def _r_overall(x) -> int:
    x = F(x)
    return int(np.trunc(x + np.copysign(F(0.49999997), x)))


def decode(raw: bytes) -> dict:
    """The named inputs of one 0x40-byte record (raw[0x10:0x3b] are the game's 0-100 bytes)."""
    b = raw
    return {
        "tactical_ability": b[0x10],
        "areas": [{"ip": b[0x11 + 3 * i], "oop": b[0x12 + 3 * i], "cap": b[0x13 + 3 * i]} for i in range(8)],
        "complexity_parts": [b[0x29], b[0x2a], b[0x2b]],
        "manager_tendencies": b[0x2c],
        "managerial_support_ip": b[0x2f],
        "managerial_support_oop": b[0x30],
        "teammates": b[0x34],
        "staff": b[0x35],
        "capability": b[0x36],
        "role_suitability": b[0x37],
        "opposition_report": b[0x38],
        "opposition_knowledge": b[0x39],
        "next_match_factor": b[0x3a],
    }


def complexity(parts: list[int]) -> int:
    a, b, c = (F(x) for x in parts)
    return _r(F(0.6) * a + F(0.3) * b + F(0.1) * c)


def compute(raw: bytes) -> dict:
    """Every TE value the game shows for one player, plus the inputs behind them."""
    d = decode(raw)
    ta = F(d["tactical_ability"])
    cx = complexity(d["complexity_parts"])
    inv = F(100 - cx)
    areas, v_ip, v_oop = [], [], []
    for (key, label, phase), a in zip(AREAS, d["areas"]):
        t = _r(F(a["cap"]) * F(0.5) * F(0.6) + ta * F(0.25) + F(0.25) * inv)
        vi = min(100, max(0, _r(F(0.6) * F(a["ip"])) + t))
        vo = min(100, max(0, _r(F(0.6) * F(a["oop"])) + t))
        v_ip.append(vi)
        v_oop.append(vo)
        areas.append({"key": key, "label": label, "phase": phase, "value": vi if phase == "ip" else vo,
                      "ip": vi, "oop": vo, **{f"raw_{k}": v for k, v in a.items()}})
    tu_ip = _r(F(sum(v_ip)) * F(0.125))
    tu_oop = _r(F(sum(v_oop)) * F(0.125))
    tu = tu_ip
    comprehension = _r((ta + inv) / F(2))
    ability = _r(F(d["capability"]) * F(d["role_suitability"]) / F(100))
    rel = _r(F(0.8) * F(d["teammates"]) + F(0.2) * F(d["staff"]))
    support = d["managerial_support_ip"]
    buy_in = _r(F(0.7) * F(support) + F(0.2) * F(rel) + F(0.1) * F(d["manager_tendencies"]))
    nm = _r(F(d["next_match_factor"]) / F(100) * (F(0.75) * F(d["opposition_report"])
                                                   + F(0.25) * F(d["opposition_knowledge"])))
    overall = _r_overall(F(0.5) * F(tu) + F(0.2) * F(buy_in) + F(0.15) * F(ability) + F(0.15) * F(nm))
    return {
        "overall": overall,
        "understanding": tu, "understanding_ip": tu_ip, "understanding_oop": tu_oop,
        "comprehension": comprehension, "complexity": cx,
        "ability": ability, "relationships": rel, "buy_in": buy_in, "next_match": nm,
        "areas": areas, "inputs": d,
    }


def team(players: list[dict]) -> dict:
    """Team averages from compute() results (the game's team figure is the mean over the XI)."""
    if not players:
        return {}
    keys = ["overall", "understanding", "understanding_ip", "understanding_oop", "comprehension",
            "ability", "buy_in", "next_match"]
    out = {k: round(sum(p[k] for p in players) / len(players), 1) for k in keys}
    out["areas"] = [{"key": a[0], "label": a[1], "phase": a[2],
                     "value": round(sum(p["areas"][i]["value"] for p in players) / len(players), 1)}
                    for i, a in enumerate(AREAS)]
    return out


def dial(value: float) -> int:
    """The 0-10 dial the game draws for a 0-100 value."""
    return int(value // 10)


# -- stored readings (tables tactical_sets / tactical_players) -------------------------------------------------------

def _tactic_key(raw: bytes) -> int:
    """The tactic's own complexity (+0x29): the same for every player in a set, different between tactics."""
    return raw[0x29]


def _player_row(r, names: dict) -> dict:
    c = compute(bytes(r["raw"]))
    return {"slot": r["slot"], "unique_id": r["unique_id"], "name": names.get(r["unique_id"]), **c}


def _names(con, uids) -> dict:
    uids = [u for u in uids if u is not None]
    if not uids:
        return {}
    q = ",".join("?" * len(uids))
    return {r[0]: r[1] for r in con.execute(f"SELECT unique_id, name FROM players WHERE unique_id IN ({q})", uids)}


def _club_name(con, cid):
    r = con.execute("SELECT name FROM clubs WHERE club_id = ?", (cid,)).fetchone()
    return r[0] if r else None


def _set(con, s, names=None) -> dict:
    rows = con.execute("SELECT * FROM tactical_players WHERE set_id = ? ORDER BY slot", (s["id"],)).fetchall()
    names = names if names is not None else _names(con, [r["unique_id"] for r in rows])
    players = [_player_row(r, names) for r in rows]
    return {"id": s["id"], "first_seen": s["first_seen"], "last_seen": s["last_seen"], "taken_at": s["taken_at"],
            "opponent_club_id": s["opponent_club_id"], "opponent": _club_name(con, s["opponent_club_id"]),
            "tactic_complexity": _tactic_key(bytes(rows[0]["raw"])) if rows else None,
            "team": team(players), "players": players}


def latest(con) -> dict:
    """The most recent reading (one set per tactic) and each tactic's team overall over time."""
    last = con.execute("SELECT MAX(taken_at) FROM tactical_sets").fetchone()[0]
    if not last:
        return {"sets": [], "history": []}
    sets = [_set(con, s) for s in con.execute(
        "SELECT * FROM tactical_sets WHERE taken_at = ? ORDER BY n_players DESC, id", (last,))]
    history = []
    for s in con.execute("SELECT s.id, s.first_seen, s.last_seen, s.overall, "
                         "(SELECT raw FROM tactical_players p WHERE p.set_id = s.id LIMIT 1) AS raw "
                         "FROM tactical_sets s ORDER BY s.first_seen, s.id"):
        history.append({"set_id": s["id"], "first_seen": s["first_seen"], "last_seen": s["last_seen"],
                        "overall": s["overall"], "tactic_complexity": _tactic_key(bytes(s["raw"])) if s["raw"] else None})
    return {"sets": sets, "history": history, "taken_at": last}


def player(con, unique_id: int) -> dict | None:
    """One player's TE in the latest reading (per tactic) and every stored reading of it."""
    rows = con.execute("""SELECT p.*, s.first_seen, s.last_seen, s.taken_at, s.opponent_club_id
                          FROM tactical_players p JOIN tactical_sets s ON s.id = p.set_id
                          WHERE p.unique_id = ? ORDER BY s.first_seen, s.id""", (unique_id,)).fetchall()
    if not rows:
        return None
    names = _names(con, [unique_id])
    last = max(r["taken_at"] for r in rows)
    readings = []
    for r in rows:
        d = _player_row(r, names)
        d.update(set_id=r["set_id"], first_seen=r["first_seen"], last_seen=r["last_seen"],
                 opponent=_club_name(con, r["opponent_club_id"]), tactic_complexity=_tactic_key(bytes(r["raw"])),
                 latest=r["taken_at"] == last)
        readings.append(d)
    return {"unique_id": unique_id, "name": names.get(unique_id), "taken_at": last,
            "current": [d for d in readings if d["latest"]], "history": readings}
