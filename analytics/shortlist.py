"""The "FM Analyst" shortlist: each shortlisted player's history and the signals for when to bid.

Signals are plain rules on contract, value, form of the history and fit in your squad:
- contract: under 6 months left (free agent soon / pre-contract), final year (selling clubs ask less), under 18 months;
- value: rising or falling since the player was first captured on the shortlist;
- injury: an injured player's value can dip;
- fit: where the player's current ability would rank among your first team at that best position.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from analytics.development import GROUPS, NEGATIVE
from analytics.players import position_string, primary_position
from analytics.squad import injury_status, latest_snapshot

SHORTLIST_NAME = "FM Analyst"
VALUE_MOVE = 0.10          # a 10% move in value counts as rising / falling


def _age(dob: str | None, on: str | None) -> int | None:
    if not dob or not on:
        return None
    b, d = dt.date.fromisoformat(dob), dt.date.fromisoformat(on)
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def months_between(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return round((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days / 30.44, 1)


def signals(p: dict) -> list[dict]:
    """[{kind: good / warn / info, text}] for one shortlisted player (see module doc)."""
    out = []
    m = p.get("contract_months")
    if m is not None:
        if m <= 6:
            out.append({"kind": "good", "text": "Under 6 months left on the contract: could leave for free, and "
                        "clubs abroad can agree a pre-contract now"})
        elif m <= 12:
            out.append({"kind": "good", "text": "Final year of the contract: the club risks losing the player for nothing, "
                        "so a bid now should cost less"})
        elif m <= 18:
            out.append({"kind": "info", "text": "Contract runs out within 18 months: the price should start to drop"})
    ch = p.get("value_change_pct")
    if ch is not None and p.get("history_days"):
        if ch <= -VALUE_MOVE * 100:
            out.append({"kind": "good", "text": f"Value down {abs(ch):.0f}% since you started tracking"})
        elif ch >= VALUE_MOVE * 100:
            out.append({"kind": "warn", "text": f"Value up {ch:.0f}% since you started tracking: "
                        "likely to get dearer"})
    if p.get("injury"):
        out.append({"kind": "info", "text": "Injured: the value may dip while out"})
    if p.get("on_loan_at"):
        out.append({"kind": "info", "text": f"On loan at {p['on_loan_at']}"})
    fit = p.get("fit")
    if fit and fit.get("rank") == 1:
        out.append({"kind": "good", "text": f"Better than all your first-team {fit['position']}s (by CA)"})
    if p.get("ca_change") and p["ca_change"] >= 5:
        out.append({"kind": "warn", "text": f"CA up {p['ca_change']} since you started tracking: "
                    "improving fast, and the price will follow"})
    return out


def go_now(p: dict) -> tuple[int, list[str]]:
    """(score, reasons) for "go for this player now": cheap now (contract running out, value falling) or about to get
    dearer (improving fast). A score of 2 or more is a recommendation; fit in your squad only adds to one."""
    score, why = 0, []
    m = p.get("contract_months")
    if m is not None and m <= 6:
        score += 3
        why.append("under 6 months left: free soon, or a pre-contract")
    elif m is not None and m <= 12:
        score += 2
        why.append("final year of the contract: should cost less")
    ch = p.get("value_change_pct")
    if ch is not None and p.get("history_days") and ch <= -VALUE_MOVE * 100:
        score += 2
        why.append(f"value down {abs(ch):.0f}%")
    if (p.get("ca_change") or 0) >= 5 and (p.get("pa") or 0) > (p.get("ca") or 0):
        score += 1
        why.append(f"CA up {p['ca_change']}: buy before the price follows")
    fit = p.get("fit")
    if fit and fit.get("rank") == 1 and score:
        score += 1
        why.append(f"would be your best {fit['position']}")
    return score, why


def _squad_by_position(con: sqlite3.Connection, club_id: int | None) -> tuple[dict[str, list[int]], str | None]:
    """Your first team's current abilities by primary position, best first; and the latest game date."""
    snap = latest_snapshot(con, club_id) if club_id else None
    if not snap:
        return {}, None
    by: dict[str, list[int]] = {}
    for r in con.execute("SELECT ca, positions FROM player_state WHERE snapshot_id = ? AND status IN "
                         "('first team', 'loaned in')", (snap["id"],)):
        pos = primary_position(json.loads(r["positions"]) if r["positions"] else {})
        if pos and r["ca"]:
            by.setdefault(pos, []).append(r["ca"])
    for v in by.values():
        v.sort(reverse=True)
    return by, snap["game_date"]


def shortlist(con: sqlite3.Connection, club_id: int | None) -> dict:
    found = con.execute("SELECT value FROM meta WHERE key = 'shortlist_found'").fetchone()
    names = {r["club_id"]: r["name"] for r in con.execute("SELECT club_id, name FROM clubs")}
    squad, today = _squad_by_position(con, club_id)
    members = con.execute("""SELECT s.unique_id, s.added, p.name, p.dob FROM shortlist s
                             JOIN players p USING (unique_id)""").fetchall()
    players = []
    for m in members:
        hist = [dict(r) for r in con.execute(
            """SELECT sn.game_date, sn.id AS snapshot_id, st.* FROM shortlist_state st
               JOIN snapshots sn ON sn.id = st.snapshot_id WHERE st.unique_id = ? ORDER BY sn.game_date, sn.id""",
            (m["unique_id"],))]
        if not hist:
            continue
        now, first = hist[-1], hist[0]
        date = now["game_date"]
        pos = json.loads(now["positions"]) if now["positions"] else {}
        primary = primary_position(pos)
        months = months_between(date, now["contract_expires"])
        owner, at = now["contract_club_id"], now["at_club_id"]
        p = {
            "unique_id": m["unique_id"], "name": m["name"], "added": m["added"], "age": _age(m["dob"], date),
            "dob": m["dob"], "game_date": date, "position": position_string(pos) or primary, "primary": primary,
            "positions": pos,
            "club_id": owner, "club": names.get(owner) if owner else "No club",
            "on_loan_at": names.get(at) if at and owner and at != owner and names.get(at) else None,
            "ca": now["ca"], "pa": now["pa"], "value": now["value"], "wage_per_week": now["wage_per_week"],
            "contract_start": now["contract_start"], "contract_expires": now["contract_expires"],
            "contract_months": months, "rep_world": now["rep_world"], "caps": now["caps"],
            "intl_goals": now["intl_goals"], "condition": now["condition"],
            "injury": injury_status(now["injuries"], date),
            "ca_change": (now["ca"] - first["ca"]) if now["ca"] is not None and first["ca"] is not None else None,
            "value_change": (now["value"] - first["value"]) if now["value"] is not None and first["value"] is not None else None,
            "value_change_pct": round(100 * (now["value"] - first["value"]) / first["value"], 1)
            if now["value"] and first["value"] else None,
            "history_days": (dt.date.fromisoformat(date) - dt.date.fromisoformat(first["game_date"])).days,
            "tracked_since": first["game_date"],
            "history": [{"date": h["game_date"], "ca": h["ca"], "pa": h["pa"], "value": h["value"],
                         "wage_per_week": h["wage_per_week"], "contract_expires": h["contract_expires"],
                         "contract_months": months_between(h["game_date"], h["contract_expires"]),
                         "club": names.get(h["contract_club_id"])} for h in hist],
        }
        ours = squad.get(primary or "", [])
        if primary and ours and p["ca"]:
            p["fit"] = {"position": primary, "rank": 1 + sum(c > p["ca"] for c in ours), "of": len(ours) + 1,
                        "best": ours[0]}
        p["signals"] = signals(p)
        p["go_score"], p["go_reasons"] = go_now(p)
        players.append(p)
    players.sort(key=lambda x: (x["contract_months"] if x["contract_months"] is not None else 999, -(x["ca"] or 0)))
    go = sorted((x for x in players if x["go_score"] >= 2), key=lambda x: (-x["go_score"], -(x["ca"] or 0)))
    return {"name": SHORTLIST_NAME, "found": None if found is None else found["value"] == "1",
            "game_date": today, "players": players, "go_now": [x["unique_id"] for x in go]}


def shortlist_player(con: sqlite3.Connection, club_id: int | None, unique_id: int) -> dict | None:
    """One shortlisted player: everything in shortlist() plus attribute history and change by group."""
    p = next((x for x in shortlist(con, club_id)["players"] if x["unique_id"] == unique_id), None)
    if not p:
        return None
    rows = con.execute("""SELECT sn.game_date, a.attr, a.raw FROM shortlist_attributes a
                          JOIN snapshots sn ON sn.id = a.snapshot_id WHERE a.unique_id = ?
                          ORDER BY sn.game_date, sn.id""", (unique_id,)).fetchall()
    hist: dict[str, list] = {}
    for r in rows:
        hist.setdefault(r["attr"], []).append({"date": r["game_date"], "raw": r["raw"]})
    latest = {a: v[-1]["raw"] for a, v in hist.items()}
    first = {a: v[0]["raw"] for a, v in hist.items()}
    p["attributes"] = {g: {a: latest[a] for a in attrs if a in latest} for g, attrs in GROUPS.items()}
    p["attribute_history"] = hist
    p["group_change"] = {g: sum((latest[a] - first[a]) * (-1 if a in NEGATIVE else 1) for a in attrs if a in latest)
                         for g, attrs in GROUPS.items()}
    p["moved"] = sorted(({"attr": a, "before": first[a], "after": latest[a], "raw_delta": latest[a] - first[a],
                          "shown_before": round(first[a] / 5), "shown_after": round(latest[a] / 5)}
                         for a in latest if latest[a] != first[a]), key=lambda c: -abs(c["raw_delta"]))
    return p
