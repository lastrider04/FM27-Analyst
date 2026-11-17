"""Compact, factual data context for the coach: the squad picture plus detail on the dashboard page in view."""
from __future__ import annotations

import sqlite3

from analytics.development import development, leaderboard, snapshot_pair
from analytics.form import in_form, team_form
from analytics.metrics import PER90_MIN_MINUTES, aggregate, last_match, match_detail, match_lines
from analytics.players import _attributes, all_players, compare, similar_players
from analytics.selection import recommend
from analytics.squad import alerts, injury_text

SENIOR = ("first team", "loaned in")
DEV_AGE = 21


def _f(v, d=0):
    return "-" if v is None else f"{v:.{d}f}" if isinstance(v, float) else str(v)


def _money(v) -> str:
    return "-" if v is None else f"£{v / 1e6:.1f}m" if v >= 1e6 else f"£{round(v / 1e3)}k" if v >= 1e3 else f"£{v}"


def _table(head: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(_f(c) if not isinstance(c, str) else c for c in r) + " |" for r in rows])


def build_context(con: sqlite3.Connection, club_id: int, page: str = "overview") -> str:
    data = all_players(con, club_id)
    if not data["players"]:
        return "NO DATA: nothing has been captured yet. Ask the user to press Capture in the dashboard while FM27 runs."
    club = (con.execute("SELECT name FROM clubs WHERE club_id = ?", (club_id,)).fetchone() or ["Club"])[0]
    lines = match_lines(con, club_id)
    aggs = aggregate(lines)
    fixtures = sorted({(l.date, l.fixture_id) for l in lines})
    recent_ids = {f for _, f in fixtures[-5:]}
    recent: dict[int, list] = {}
    for l in sorted(lines, key=lambda l: l.date):
        if l.fixture_id in recent_ids:
            recent.setdefault(l.unique_id, []).append(l)
    rec = recommend(con, club_id)
    out = [f"CLUB: {club}. GAME DATE (latest capture): {data['game_date']}. "
           f"Player stats are from {len(fixtures)} captured matches (FM keeps only recent ones in memory)."]

    sq = [p for p in data["players"] if p["status"] in SENIOR]
    rows = []
    for p in sq:
        a, r = aggs.get(p["unique_id"]), recent.get(p["unique_id"], [])
        rows.append([p["name"], p["position"] or "-", p["age"], f"{p['ca']}/{p['pa']}", f"{p['condition']:.0f}%",
                     f"{p['sharpness']:.0f}%", p["jadedness"],
                     injury_text(p["injury"]).replace("injured, ", "INJURED ") if p.get("injury") else "fit", p["status"],
                     len(r), sum(1 for l in r if l.started), " ".join(f"{l.rating:.1f}" for l in r) or "-",
                     a.apps if a else 0, a.minutes if a else 0, _f(a.avg_rating, 2) if a else "-",
                     a.goals if a else 0, a.assists if a else 0, _money(p.get("value")), _money(p.get("wage_per_week")),
                     "loan" if p["status"] == "loaned in" else p.get("contract_expires") or "-"])
    out.append("SENIOR SQUAD (condition/sharpness %, jadedness: >300 needs rest, >200 tiring; injury from the medical "
               "record; recent = last 5 captured matches, ratings oldest->newest)\n" + _table(
        ["player", "positions", "age", "CA/PA", "cond", "sharp", "jaded", "injury", "status", "recent apps", "recent starts",
         "recent ratings", "apps", "mins", "avg rating", "G", "A", "value", "wage/wk", "contract to"], rows))

    from analytics.roles import squad_metrics
    sm = squad_metrics(con, club_id)
    senior_ids = {p["unique_id"] for p in sq}
    gks = [g for g in sm["goalkeepers"].values() if g["unique_id"] in senior_ids]
    if gks:
        out.append("GOALKEEPERS (captured matches; save % = saves / shots on target faced; xG prevented not available)\n"
                   + _table(["keeper", "apps", "mins", "avg rating", "save %", "saves", "on target faced", "conceded",
                             "clean sheets", "conceded/90"],
                            [[g["name"], g["apps"], g["minutes"], _f(g["avg_rating"], 2), _f(g["save_pct"], 1), g["saves"],
                              g["shots_on_target_faced"], g["goals_conceded"], g["clean_sheets"], _f(g["conceded_per90"], 2)]
                             for g in sorted(gks, key=lambda g: -g["minutes"])]))
    names = {p["unique_id"]: p["name"] for p in sq}
    roles = [(names[u], s) for u, s in sm["roles"].items() if u in names]
    if roles:
        keys = list(sm["labels"])
        out.append("ROLE SCORES (outfield, 0-100 vs your own players with 180+ captured minutes; " + "; ".join(
            f"{sm['labels'][k]}" for k in keys) + ")\n" + _table(
            ["player"] + [sm["labels"][k] for k in keys],
            [[n] + [s[k] if s[k] is not None else "-" for k in keys] for n, s in sorted(roles)]))

    out.append(_per90_block(aggs, sm, senior_ids))

    mine = [p for p in data["players"] if p["status"] != "no contract"]
    top = sorted(mine, key=lambda p: -(p["ca"] or 0))[:5]
    prom = sorted((p for p in mine if p["age"] is not None and p["age"] <= DEV_AGE and (p["pa"] or 0) > 0),
                  key=lambda p: (-(p["pa"] or 0), -((p["pa"] or 0) - (p["ca"] or 0))))[:5]
    out.append("BEST NOW (top 5 CA at the club, the app's star badge): " + ", ".join(f"{p['name']} {p['ca']}" for p in top)
               + f"\nMOST PROMISING (age <= {DEV_AGE}, highest PA, the app's sprout badge): "
               + ", ".join(f"{p['name']} ({p['age']}, {p['ca']}/{p['pa']})" for p in prom))

    others = [p for p in data["players"] if p["status"] in ("youth team", "loaned out")]
    others.sort(key=lambda p: (p["status"], -((p["pa"] or 0) - (p["ca"] or 0))))
    out.append(f"YOUTH TEAMS AND OUT ON LOAN (headroom = PA-CA; age <= {DEV_AGE} with headroom >= 10 are development candidates)\n"
               + _table(["player", "positions", "age", "CA/PA", "headroom", "status", "where", "captured apps", "mins",
                         "sharp", "contract to"],
                        [[p["name"], p["position"] or "-", p["age"], f"{p['ca']}/{p['pa']}", (p["pa"] or 0) - (p["ca"] or 0),
                          p["status"], p["where"], aggs[p["unique_id"]].apps if p["unique_id"] in aggs else 0,
                          aggs[p["unique_id"]].minutes if p["unique_id"] in aggs else 0, f"{p['sharpness']:.0f}%",
                          p.get("contract_expires") or "-"] for p in others]))

    out.append(_development_block(con, club_id))

    up = con.execute("""SELECT f.date, f.kickoff, f.home_id, h.name AS home, a.name AS away, f.competition FROM fixtures f
                        LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                        WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NULL AND f.date >= ?
                        ORDER BY f.date, f.kickoff LIMIT 5""", (club_id, club_id, data["game_date"])).fetchall()
    out.append("NEXT FIXTURES\n" + "\n".join(
        f"- {r['date']} {r['kickoff'] or ''} {'vs' if r['home_id'] == club_id else 'at'} "
        f"{r['away'] if r['home_id'] == club_id else r['home']} ({r['competition']})" for r in up) or "NEXT FIXTURES: none stored")

    tf = team_form(con, club_id)
    out.append(f"TEAM FORM (last {len(tf.results)} competitive, oldest->newest): {tf.string}, {tf.points} pts, "
               f"goals {tf.goals_for}-{tf.goals_against}")
    out.append("IN FORM (app's score: last-3 average + trend + goal involvements)\n" + "\n".join(
        f"- {p['name']}: {p['why']} (score {p['score']})" for p in in_form(lines)))
    out.append("APP'S NEXT-MATCH RECOMMENDATION (rule-based: form, trend, goal threat, ability, condition, sharpness, jadedness, recent minutes)\n"
               + "\n".join(f"- swap: {w['out']['name']} -> {w['in']['name']} [{w['group']}] ({w['reason']})" for w in rec["swaps"])
               + "\n" + "\n".join(f"- best placed: {p['name']} ({p['position']}): {p['why']}" for p in rec["recommended"]))
    al = alerts(con, club_id)
    out.append("ALERTS\n" + ("\n".join(f"- {a.kind}: {a.name} ({a.detail})" for a in al) or "none"))

    out.append(_shortlist_block(con, club_id))
    out.append(_tactical_block(con))

    summary, ml = last_match(con, club_id)
    if summary:
        out.append(_match_block("LAST MATCH", summary, ml))
    out.append(_focus(con, club_id, page, data))
    return "\n\n".join(x for x in out if x)


def _per90_block(aggs: dict, sm: dict, ids: set[int]) -> str:
    rows = [a for a in aggs.values() if a.unique_id in ids and a.unique_id not in sm["goalkeepers"]
            and a.minutes >= PER90_MIN_MINUTES]
    if not rows:
        return ""
    rows.sort(key=lambda a: -a.minutes)
    head = ["player", "mins", "G+A/90", "xG/90", "xA/90", "shots/90", "key passes/90", "progressive/90", "dribbles/90",
            "tackles won/90", "interceptions/90", "headers won/90", "pass %", "G-xG"]
    body = []
    for a in rows:
        q = a.per90s()
        body.append([a.name, a.minutes] + [_f(q[k], 2) for k in ("goal_involvements", "xg", "xa", "shots", "key_passes",
                     "progressive_passes", "dribbles", "tackles_won", "interceptions", "headers_won")]
                    + [_f(a.pass_pct, 1), _f(a.goals - a.xg, 2)])
    return f"PER 90 (senior outfield players with {PER90_MIN_MINUTES}+ captured minutes)\n" + _table(head, body)


def _changes(d, n: int = 4) -> str:
    moved = [c for c in d.changes if c.shown_delta][:n]
    return ", ".join(f"{c.attr} {c.shown_before}->{c.shown_after}" for c in moved) or "small raw changes only"


def _development_block(con, club_id: int, days: int = 90, n: int = 8) -> str:
    pair = snapshot_pair(con, club_id, days)
    if not pair:
        return ""
    devs = development(con, *pair)
    if not devs or not devs[0].days:
        return ""
    up, down = leaderboard(devs, n=n, statuses=("first team", "loaned in", "youth team", "loaned out"))
    fmt = lambda d: f"- {d.name} ({d.age}, {d.status}): CA {d.ca_before}->{d.ca_after}; {_changes(d)}"
    return (f"DEVELOPMENT over the last {devs[0].days} game days (CA change, then the attributes that moved on the 1-20 scale)\n"
            "Improving:\n" + ("\n".join(map(fmt, up)) or "none") + "\nDeclining:\n" + ("\n".join(map(fmt, down)) or "none"))


SL_HEAD = ["player", "positions", "age", "club", "CA/PA (change)", "value", "value change", "wage/wk", "contract to",
           "left", "fit", "injury", "go-now reasons"]


def _sl_row(p: dict) -> list:
    club = (p["club"] or "-") + (f" (on loan at {p['on_loan_at']})" if p.get("on_loan_at") else "")
    vchg = f"{p['value_change_pct']:+.0f}%" if p.get("value_change_pct") is not None and p.get("history_days") else "-"
    left = "-" if p.get("contract_months") is None else f"{p['contract_months']:.0f} mo"
    fit = f"#{p['fit']['rank']} of {p['fit']['of']} at {p['fit']['position']}" if p.get("fit") else "-"
    ca = f"{p['ca']}/{p['pa']}" + (f" ({p['ca_change']:+d})" if p.get("ca_change") else "")
    return [p["name"], p["position"] or "-", p["age"], club, ca, _money(p["value"]), vchg, _money(p["wage_per_week"]),
            p.get("contract_expires") or "-", left, fit,
            injury_text(p["injury"]) if p.get("injury") else "fit", "; ".join(p["go_reasons"]) or "-"]


def _shortlist_block(con, club_id: int) -> str:
    from analytics.shortlist import shortlist
    d = shortlist(con, club_id)
    if d["found"] is not True or not d["players"]:
        why = ("no capture has looked for it yet" if d["found"] is None else "there's no shortlist with that name in the game"
               if d["found"] is False else "it's empty")
        return f"SHORTLIST ('{d['name']}' in FM27, the user's transfer targets): none, {why}."
    byid = {p["unique_id"]: p for p in d["players"]}
    go = [byid[u]["name"] for u in d["go_now"] if u in byid]
    return (f"SHORTLIST (transfer targets on the user's '{d['name']}' shortlist in FM27; not at the club; value change "
            "is since tracking began; fit = where their CA would rank among your first team at their best position; "
            "go-now reasons are the app's rules)\n" + _table(SL_HEAD, [_sl_row(p) for p in d["players"]])
            + "\nGO FOR THEM NOW (the app's list): " + (", ".join(go) or "nobody right now"))


def _tactical_block(con) -> str:
    """FM27's Tactical Effectiveness for each tactic at the last reading (the game's own 0-100 values)."""
    from analytics.tactical import latest
    try:
        d = latest(con)
    except sqlite3.Error:
        return ""
    if not d["sets"]:
        return ""
    parts = []
    for n, s in enumerate(d["sets"]):
        t = s["team"]
        parts.append(
            f"Tactic {chr(65 + n)} (tactic complexity {s['tactic_complexity']}, read {s['last_seen']}, next opponent "
            f"{s['opponent'] or '?'}): team overall {_f(t['overall'])}, understanding {_f(t['understanding'])}, buy-in "
            f"{_f(t['buy_in'])}, ability {_f(t['ability'])}, next match {_f(t['next_match'])}, comprehension "
            f"{_f(t['comprehension'])}; weakest areas: "
            + ", ".join(f"{a['label']} {_f(a['value'])}" for a in sorted(t["areas"], key=lambda a: a["value"])[:3]) + "\n"
            + _table(["Player", "Overall", "Underst.", "Compreh.", "Ability", "Buy-in", "Next", "Weakest area"],
                     [[p["name"] or "?", p["overall"], p["understanding"], p["comprehension"], p["ability"], p["buy_in"],
                       p["next_match"], min(p["areas"], key=lambda a: a["value"])["label"]
                       + f" {min(a['value'] for a in p['areas'])}"] for p in s["players"]]))
    return ("TACTICAL EFFECTIVENESS (FM27's own values 0-100, read from the game; overall = 50% tactical understanding "
            "+ 20% buy-in + 15% player ability + 15% next-match preparation; comprehension = tactical ability vs the "
            "tactic's complexity for his role)\n" + "\n".join(parts))


def _shortlist_focus(con, club_id: int, uid: int) -> str:
    from analytics.shortlist import shortlist_player
    p = shortlist_player(con, club_id, uid)
    if not p:
        return ""
    attrs = {a: v for g in p["attributes"].values() for a, v in g.items()}
    return (f"SHORTLISTED PLAYER {p['name']} (transfer target, not at the club) - treat 'he', 'him', 'this player' as {p['name']}.\n"
            + _table(SL_HEAD, [_sl_row(p)]) + "\n"
            f"Tracked since {p['tracked_since']}; world reputation {p.get('rep_world')}; caps {p.get('caps')} ({p.get('intl_goals')} goals)\n"
            "When-to-bid signals: " + ("; ".join(x["text"] for x in p["signals"]) or "none") + "\n"
            "History (date CA/PA value wage contract-to club): " + "; ".join(
                f"{h['date']} {h['ca']}/{h['pa']} {_money(h['value'])} {_money(h['wage_per_week'])} {h['contract_expires']} {h['club']}"
                for h in p["history"]) + "\n"
            "Attributes (1-20): " + ", ".join(f"{k} {round(v / 5)}" for k, v in sorted(attrs.items())) + "\n"
            "Changed since tracking (1-20 before->after, raw change): " + (", ".join(
                f"{c['attr']} {c['shown_before']}->{c['shown_after']} ({c['raw_delta']:+d} raw)" for c in p["moved"][:10]) or "none yet"))


def _match_block(title: str, s: dict, lines) -> str:
    head = (f"{title}: {s['date']} {'vs' if s['venue'] != 'A' else 'at'} {s['opponent']} {s['score']} ({s['result'] or 'not played'}), "
            f"{s['competition']}, team xG {s['xg']}, avg rating {s['avg_rating']}")
    if not lines:
        return head + " - no player stats captured"
    return head + "\n" + _table(
        ["player", "start", "mins", "rating", "G", "A", "xG", "xA", "pass %", "shots", "key passes", "tackles won",
         "interceptions", "km"],
        [[l.name, "Y" if l.started else "sub", l.minutes, f"{l.rating:.2f}", l.goals, l.assists, f"{l.xg:.2f}",
          f"{l.xa:.2f}", _f(l.pass_pct), l.counters.get("shots", 0), l.counters.get("key_passes", 0),
          l.counters.get("tackles_won", 0), l.counters.get("interceptions", 0), f"{l.distance_km:.1f}"] for l in lines])


def _player_extras(con, club_id: int, uid: int) -> str:
    """Role scores (or keeper stats), per 90s and recent attribute changes for one club player."""
    from analytics.roles import squad_metrics
    sm = squad_metrics(con, club_id)
    out = []
    a = aggregate(match_lines(con, club_id)).get(uid)
    if uid in sm["goalkeepers"]:
        g = sm["goalkeepers"][uid]
        out.append(f"Keeper stats: save % {_f(g['save_pct'], 1)}, clean sheets {g['clean_sheets']}, conceded/90 {_f(g['conceded_per90'], 2)}")
    elif sm["roles"].get(uid):
        out.append("Role scores (0-100 vs the squad): " + ", ".join(
            f"{sm['labels'][k]} {v}" for k, v in sm["roles"][uid].items() if v is not None))
    if a and a.minutes and uid not in sm["goalkeepers"]:
        q = a.per90s()
        out.append(f"Per 90 over {a.minutes} captured minutes" + (" (few minutes: noisy)" if a.minutes < PER90_MIN_MINUTES else "")
                   + ": " + ", ".join(f"{k.replace('_', ' ')} {_f(v, 2)}" for k, v in q.items() if v is not None)
                   + f", pass % {_f(a.pass_pct, 1)}")
    pair = snapshot_pair(con, club_id)
    if pair:
        d = next((x for x in development(con, *pair) if x.unique_id == uid), None)
        if d and d.days:
            out.append(f"Development over {d.days} game days: CA {d.ca_before}->{d.ca_after}; " + ", ".join(
                f"{c.attr} {c.shown_before}->{c.shown_after} ({c.raw_delta:+d} raw)" for c in d.changes[:8] if c.raw_delta))
    return "".join(x + "\n" for x in out)


def _focus(con, club_id: int, page: str, data: dict) -> str:
    """Extra detail for the dashboard page the user is looking at."""
    name, *args = (page or "overview").split("?")[0].split("/")
    try:
        if name == "player" and args:
            uid = int(args[0])
            p = next((x for x in data["players"] if x["unique_id"] == uid), None)
            if not p:
                return ""
            snap = con.execute("SELECT id FROM snapshots WHERE club_id = ? ORDER BY game_date DESC, id DESC LIMIT 1",
                               (club_id,)).fetchone()
            attrs = _attributes(con, snap[0]).get(uid, {}) if snap else {}
            ml = sorted(match_lines(con, club_id, unique_id=uid), key=lambda l: l.date)
            ca = []
            for r in con.execute("""SELECT s.game_date, ps.ca FROM player_state ps JOIN snapshots s ON s.id = ps.snapshot_id
                                    WHERE ps.unique_id = ? ORDER BY s.game_date, s.id""", (uid,)):
                if not ca or ca[-1]["ca"] != r["ca"]:   # only changes
                    ca.append(r)
            sim = similar_players(con, club_id, uid)
            return (f"PAGE IN VIEW: player page of {p['name']} - treat 'he', 'him', 'this player' as {p['name']}.\n"
                    f"{p['name']}: {p['position']}, age {p['age']}, CA {p['ca']} / PA {p['pa']}, {p['status']} at {p['where']}, "
                    f"condition {p['condition']:.0f}%, sharpness {p['sharpness']:.0f}%, jadedness {p['jadedness']}, "
                    f"contract to {p['contract_expires']}, value {_money(p.get('value'))}, wage {_money(p.get('wage_per_week'))}/wk, "
                    f"{injury_text(p['injury']) if p.get('injury') else 'fit'}\n" + _player_extras(con, club_id, uid) +
                    "Attributes (1-20): " + ", ".join(f"{k} {round(v / 5)}" for k, v in sorted(attrs.items())) + "\n"
                    "CA history: " + ", ".join(f"{r['game_date']} {r['ca']}" for r in ca) + "\n"
                    "Match log (date opponent minutes rating G A xG xA shots/on target key passes tackles won interceptions): "
                    + ("; ".join(f"{l.date} {l.opponent} {l.minutes}' {l.rating:.2f} G{l.goals} A{l.assists} xG{l.xg:.2f} "
                                 f"xA{l.xa:.2f} sh{l.counters.get('shots', 0)}/{l.counters.get('shots_on_target', 0)} "
                                 f"kp{l.counters.get('key_passes', 0)} tk{l.counters.get('tackles_won', 0)} "
                                 f"int{l.counters.get('interceptions', 0)}" for l in ml) or "none captured") + "\n"
                    "Most similar club players (position + attributes): "
                    + ", ".join(f"{s['name']} ({s['position']}, CA {s['ca']}, {s['score']}%)" for s in sim))
        if name == "match" and args:
            s, lines = match_detail(con, club_id, int(args[0]))
            return _match_block("PAGE IN VIEW: match", s, lines) if s else ""
        if name == "compare" and len(args) >= 2:
            c = compare(con, club_id, int(args[0]), int(args[1]))
            a, b = c["players"]
            keys = sorted(set(a["attributes"]) | set(b["attributes"]))
            return (f"PAGE IN VIEW: comparing {a['name']} and {b['name']} (position match {c['position_match']}%, "
                    f"attribute match {c['attribute_match']}%)\n" + _table(
                        ["attribute", a["name"], b["name"]],
                        [[k, round(a["attributes"].get(k, 0) / 5), round(b["attributes"].get(k, 0) / 5)] for k in keys]))
        if name == "development":
            pair = snapshot_pair(con, club_id)
            if not pair:
                return "PAGE IN VIEW: development (only one snapshot so far)"
            up, down = leaderboard(development(con, *pair), n=10)
            fmt = lambda d: f"- {d.name} ({d.age}): CA {d.ca_before}->{d.ca_after} over {d.days} days; " + ", ".join(
                f"{c.attr} {c.shown_before}->{c.shown_after}" for c in d.changes if c.shown_delta)
            return "PAGE IN VIEW: development\nImprovers:\n" + "\n".join(map(fmt, up)) + "\nDecliners:\n" + "\n".join(map(fmt, down))
        if name == "shortlist":
            if args:
                f = _shortlist_focus(con, club_id, int(args[0]))
                return ("PAGE IN VIEW: shortlisted player page\n" + f) if f else "PAGE IN VIEW: shortlist"
            return "PAGE IN VIEW: the Shortlist (the SHORTLIST section above is everything on it)"
        if name == "tactical":
            who = f" for player {args[0]}" if args else ""
            return f"PAGE IN VIEW: Tactical Effectiveness{who} (the TACTICAL EFFECTIVENESS section above has the values)"
        if name == "per90":
            return "PAGE IN VIEW: Per 90 (role scores, goalkeepers and the PER 90 table above)"
        if name == "fixtures":
            res = con.execute("""SELECT f.date, f.home_id, h.name AS home, a.name AS away, f.home_goals, f.away_goals, f.competition
                                 FROM fixtures f LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                                 WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NOT NULL
                                 ORDER BY f.date DESC LIMIT 10""", (club_id, club_id)).fetchall()
            return "PAGE IN VIEW: fixtures\nLast results (newest first):\n" + "\n".join(
                f"- {r['date']} {'vs ' + (r['away'] or '?') if r['home_id'] == club_id else 'at ' + (r['home'] or '?')} "
                f"{r['home_goals'] if r['home_id'] == club_id else r['away_goals']}-"
                f"{r['away_goals'] if r['home_id'] == club_id else r['home_goals']} ({r['competition']})" for r in res)
        if name in ("players", "squad"):
            return "PAGE IN VIEW: all players (senior squad, youth teams and loans above; BEST NOW and MOST PROMISING are the app's badges)"
    except (ValueError, KeyError, IndexError):
        return ""
    return f"PAGE IN VIEW: {name}"
