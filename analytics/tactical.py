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




# -- what would raise it ------------------------------------------------------------------------------------------

PART_WEIGHTS = {"understanding": 0.5, "buy_in": 0.2, "ability": 0.15, "next_match": 0.15}
TIP_TARGET = 90          # "what if this factor were 90": a realistic good value, not perfection


def _with(raw: bytes, offsets, value: int) -> bytes:
    b = bytearray(raw)
    for o in offsets:
        b[o] = max(b[o], value)
    return bytes(b)


def tips(raw: bytes, c: dict | None = None, opponent: str | None = None) -> list[dict]:
    """What would raise this player's overall TE most: each fixable factor raised to TIP_TARGET, re-run through the
    game's formulas. [{part, factor, value, gain, text}] with gain >= 1 overall point, biggest first."""
    c = c or compute(raw)
    i = c["inputs"]
    weakest = min(c["areas"], key=lambda a: a["value"])
    fam = [0x11 + 3 * k for k in range(8)] + [0x12 + 3 * k for k in range(8)]
    opp = opponent or "the next opponent"
    cands = [
        ("understanding", "Tactical familiarity", weakest["value"], fam,
         f"Weakest area {weakest['label']} ({weakest['value']}): tactical training and matches in this tactic raise it."),
        ("ability", "Role suitability", i["role_suitability"], [0x37],
         f"Role suitability {i['role_suitability']}: the role doesn't suit him. Try a role he suits better, or a player who suits it."),
        ("ability", "Capability", i["capability"], [0x36],
         f"Capability {i['capability']}: he isn't at this level in this role yet; a stronger player in the slot lifts it."),
        ("buy_in", "Managerial support", i["managerial_support_ip"], [0x2f, 0x30],
         f"Managerial support {i['managerial_support_ip']}: he isn't fully behind you yet. Playing time, praise and keeping promises build it."),
        ("buy_in", "Relationships", c["relationships"], [0x34, 0x35],
         f"Relationships {c['relationships']} (teammates {i['teammates']}, staff {i['staff']}): give him time to settle; team bonding and mentoring help."),
        ("next_match", "Opposition report", i["opposition_report"], [0x38],
         f"Opposition report {i['opposition_report']}: have your analysts prepare a full report on {opp}."),
        ("next_match", "Readiness", i["next_match_factor"], [0x3a],
         f"Readiness {i['next_match_factor']} scales his whole next-match preparation."),
        ("understanding", "Tactical ability vs complexity", c["comprehension"], [0x10],
         f"Comprehension {c['comprehension']} (tactical ability {i['tactical_ability']}, complexity {c['complexity']}): "
         "this tactic is hard for him in this role; a simpler role or tactic caps him less."),
    ]
    out = []
    for part, factor, value, offs, text in cands:
        gain = compute(_with(raw, offs, TIP_TARGET))["overall"] - c["overall"]
        if gain >= 1:
            out.append({"part": part, "factor": factor, "value": value, "gain": gain, "text": text})
    return sorted(out, key=lambda t: -t["gain"])


def points_lost(t: dict) -> list[dict]:
    """Where the team overall loses points: weight x (100 - part), per part (team averages)."""
    return sorted(({"part": k, "lost": round(w * (100 - t[k]), 1)} for k, w in PART_WEIGHTS.items()),
                  key=lambda x: -x["lost"])


# -- stored readings (tables tactical_sets / tactical_players) -------------------------------------------------------

TACTIC_MIN = 8           # a set with at least this many players is a tactic's XI; smaller ones are single readings
                         # (a player's own TE screen), used for his page and for selection


def _tactic_key(raw: bytes) -> int:
    """The tactic's own complexity (+0x29): the same for every player in a set, different between tactics."""
    return raw[0x29]


def _names(con, uids) -> dict:
    uids = [u for u in uids if u is not None]
    if not uids:
        return {}
    q = ",".join("?" * len(uids))
    return {r[0]: r[1] for r in con.execute(f"SELECT unique_id, name FROM players WHERE unique_id IN ({q})", uids)}


def _positions(con, club_id) -> dict:
    if club_id is None:
        return {}
    from .players import all_players
    try:
        return {p["unique_id"]: p.get("primary") for p in all_players(con, club_id)["players"]}
    except Exception:
        return {}


def _club_name(con, cid):
    r = con.execute("SELECT name FROM clubs WHERE club_id = ?", (cid,)).fetchone()
    return r[0] if r else None


def _player_row(r, names: dict, pos: dict, opponent: str | None) -> dict:
    raw = bytes(r["raw"])
    c = compute(raw)
    return {"slot": r["slot"], "unique_id": r["unique_id"], "name": names.get(r["unique_id"]),
            "position": pos.get(r["unique_id"]), "tips": tips(raw, c, opponent), **c}


def _set(con, s, pos: dict) -> dict:
    rows = con.execute("SELECT * FROM tactical_players WHERE set_id = ? ORDER BY slot", (s["id"],)).fetchall()
    names = _names(con, [r["unique_id"] for r in rows])
    opponent = _club_name(con, s["opponent_club_id"])
    players = [_player_row(r, names, pos, opponent) for r in rows]
    t = team(players)
    if t:
        t["points_lost"] = points_lost(t)
    return {"id": s["id"], "first_seen": s["first_seen"], "last_seen": s["last_seen"], "taken_at": s["taken_at"],
            "opponent_club_id": s["opponent_club_id"], "opponent": opponent,
            "tactic_complexity": _tactic_key(bytes(rows[0]["raw"])) if rows else None,
            "team": t, "players": players}


def latest(con, club_id: int | None = None) -> dict:
    """The most recent reading (one set per tactic) and each tactic's team overall over time."""
    last = con.execute("SELECT MAX(taken_at) FROM tactical_sets WHERE n_players >= ?", (TACTIC_MIN,)).fetchone()[0]
    if not last:
        return {"sets": [], "history": []}
    pos = _positions(con, club_id)
    sets = [_set(con, s, pos) for s in con.execute(
        "SELECT * FROM tactical_sets WHERE taken_at = ? AND n_players >= ? ORDER BY id", (last, TACTIC_MIN))]
    history = []
    for s in con.execute("SELECT s.id, s.first_seen, s.last_seen, s.overall, "
                         "(SELECT raw FROM tactical_players p WHERE p.set_id = s.id LIMIT 1) AS raw "
                         "FROM tactical_sets s WHERE s.n_players >= ? ORDER BY s.first_seen, s.id", (TACTIC_MIN,)):
        history.append({"set_id": s["id"], "first_seen": s["first_seen"], "last_seen": s["last_seen"],
                        "overall": s["overall"], "tactic_complexity": _tactic_key(bytes(s["raw"])) if s["raw"] else None})
    return {"sets": sets, "history": history, "taken_at": last}


def by_player(con) -> dict[int, dict]:
    """Each player's most recent TE for the main tactic (Tactic A of the latest reading): from that XI, or from a
    later single reading of the same tactic. {uid: {overall, parts..., weakest, tip, in_xi, read}}."""
    last = con.execute("SELECT MAX(taken_at) FROM tactical_sets WHERE n_players >= ?", (TACTIC_MIN,)).fetchone()[0]
    if not last:
        return {}
    main = con.execute("SELECT id FROM tactical_sets WHERE taken_at = ? AND n_players >= ? ORDER BY id LIMIT 1",
                       (last, TACTIC_MIN)).fetchone()[0]
    xi = {r["unique_id"]: r for r in con.execute("SELECT * FROM tactical_players WHERE set_id = ?", (main,))}
    key = _tactic_key(bytes(next(iter(xi.values()))["raw"])) if xi else None
    out = {}
    rows = con.execute("""SELECT p.*, s.last_seen, s.taken_at, s.id AS sid FROM tactical_players p
                          JOIN tactical_sets s ON s.id = p.set_id WHERE p.unique_id IS NOT NULL
                          ORDER BY s.taken_at, s.id""").fetchall()
    for r in rows:
        raw = bytes(r["raw"])
        if _tactic_key(raw) != key or (r["unique_id"] in xi and r["sid"] != main and r["taken_at"] < last):
            continue
        c = compute(raw)
        tp = tips(raw, c)
        out[r["unique_id"]] = {
            "overall": c["overall"], "understanding": c["understanding"], "buy_in": c["buy_in"],
            "ability": c["ability"], "next_match": c["next_match"], "comprehension": c["comprehension"],
            "weakest": min(PART_WEIGHTS, key=lambda k: c[k]), "tip": tp[0]["text"] if tp else None,
            "in_xi": r["unique_id"] in xi, "read": r["last_seen"]}
    return out


def player(con, unique_id: int, club_id: int | None = None) -> dict | None:
    """One player's TE in the latest reading (per tactic), every stored reading of it, and the team's averages."""
    rows = con.execute("""SELECT p.*, s.first_seen, s.last_seen, s.taken_at, s.opponent_club_id, s.n_players
                          FROM tactical_players p JOIN tactical_sets s ON s.id = p.set_id
                          WHERE p.unique_id = ? ORDER BY s.first_seen, s.id""", (unique_id,)).fetchall()
    if not rows:
        return None
    names = _names(con, [unique_id])
    pos = _positions(con, club_id)
    lat = latest(con, club_id)
    teams = {s["tactic_complexity"]: s["team"] for s in lat["sets"]}
    last = max(r["taken_at"] for r in rows)
    readings, seen = [], set()
    for r in rows:
        opp = _club_name(con, r["opponent_club_id"])
        d = _player_row(r, names, pos, opp)
        key = _tactic_key(bytes(r["raw"]))
        d.update(set_id=r["set_id"], first_seen=r["first_seen"], last_seen=r["last_seen"], opponent=opp,
                 tactic_complexity=key, latest=r["taken_at"] == last, in_xi=r["n_players"] >= TACTIC_MIN,
                 team=teams.get(key))
        readings.append(d)
    current = []
    for d in reversed(readings):             # newest per tactic, in the order of the latest reading's tabs
        if d["tactic_complexity"] not in seen:
            seen.add(d["tactic_complexity"])
            current.append(d)
    order = [s["tactic_complexity"] for s in lat["sets"]]
    current.sort(key=lambda d: order.index(d["tactic_complexity"]) if d["tactic_complexity"] in order else 99)
    return {"unique_id": unique_id, "name": names.get(unique_id), "position": pos.get(unique_id), "taken_at": last,
            "current": current, "history": readings, "tactics": order}


def summary(con, club_id: int | None = None) -> dict | None:
    """The main tactic's latest reading in brief, for the Overview: team values, where points go, the weakest three."""
    d = latest(con, club_id)
    if not d["sets"]:
        return None
    s = d["sets"][0]
    t = s["team"]
    weak = sorted(s["players"], key=lambda p: p["overall"])[:3]
    return {"overall": t["overall"], "parts": {k: t[k] for k in PART_WEIGHTS}, "comprehension": t["comprehension"],
            "points_lost": t["points_lost"], "opponent": s["opponent"], "read": s["last_seen"],
            "tactics": [{"overall": x["team"]["overall"]} for x in d["sets"]],
            "weakest": [{"unique_id": p["unique_id"], "name": p["name"], "position": p["position"], "overall": p["overall"],
                         "tip": p["tips"][0] if p["tips"] else None} for p in weak]}
