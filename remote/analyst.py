"""The FM27 analyst's data for the phone's Team panel: next-match advice (Phase 3), squad and fixtures (Phase 4).

Read-only: it GETs endpoints from the analyst running on this PC (127.0.0.1, FM27's port 8775 by default) and
trims them to what the panel shows. The analyst stays local-only; only paired phones reach this through remote play.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_PORT = 8775          # the FM27 analyst (8765 is the frozen FM26 one)
PLAYER_KEYS = ("unique_id", "name", "position", "condition", "sharpness", "jadedness", "form", "injury",
               "unfit", "caution", "why", "starter")


class AnalystUnavailable(RuntimeError):
    pass


def port() -> int:
    import app_config
    try:
        return int(app_config.load_config().get("remote_play", {}).get("analyst_port", DEFAULT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def fetch(path: str, port_: int, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port_}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AnalystUnavailable(f"The FM27 analyst isn't answering on port {port_} ({e}).") from e


def player(p: dict | None) -> dict | None:
    return {k: p.get(k) for k in PLAYER_KEYS} if isinstance(p, dict) else None


def summary(port_: int | None = None) -> dict:
    port_ = port_ or port()
    status, overview = fetch("/api/status", port_), fetch("/api/overview", port_)
    nm = overview.get("next_match") or {}
    return {
        "as_of": (status.get("latest") or {}).get("game_date"),
        "game_running": status.get("game_running"),
        "next": status.get("next"),
        "upcoming": [{k: f.get(k) for k in ("date", "kickoff", "opponent", "venue", "competition")}
                     for f in (overview.get("upcoming") or [])[:5]],
        "swaps": [{"out": player(s.get("out")), "in": player(s.get("in"))} for s in nm.get("swaps") or []],
        "rest": [player(p) for p in nm.get("rest") or []],
        "picks": [player(p) for p in nm.get("recommended") or []],
        "alerts": [{k: a.get(k) for k in ("kind", "name", "detail")} for a in overview.get("alerts") or []],
        "basis": nm.get("basis"),
    }


# FM's positions, in the order a squad list reads (goalkeeper first, strikers last), grouped into lines.
POSITIONS = ("GK", "SW", "DL", "DC", "DR", "WBL", "DM", "WBR", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST")
GROUPS = {"GK": "Goalkeepers", "SW": "Defenders", "DL": "Defenders", "DC": "Defenders", "DR": "Defenders",
          "WBL": "Defenders", "WBR": "Defenders", "DM": "Midfielders", "ML": "Midfielders", "MC": "Midfielders",
          "MR": "Midfielders", "AML": "Attackers", "AMC": "Attackers", "AMR": "Attackers", "ST": "Attackers"}
NATURAL = 18                 # FM rates each position 1-20; 18+ is natural or accomplished


def positions(raw) -> list[str]:
    """The positions a player is natural in, best first ("ST", or "DC, DM" …)."""
    try:
        ratings = json.loads(raw) if isinstance(raw, str) else raw or {}
    except ValueError:
        return []
    best = max(ratings.values(), default=0)
    good = [p for p in POSITIONS if ratings.get(p, 0) >= min(NATURAL, best)]
    return sorted(good, key=lambda p: -ratings[p])


def squad(port_: int | None = None) -> dict:
    """The first team (and loanees), trimmed to what a phone list needs, grouped GK → attackers."""
    from analytics.squad import injury_status, injury_text
    d = fetch("/api/squad", port_ or port())
    out = []
    for p in d.get("players") or []:
        pos = positions(p.get("positions"))
        inj = injury_status(p.get("injuries"), d.get("game_date"))
        out.append({
            "unique_id": p.get("unique_id"), "name": p.get("name"), "age": p.get("age"),
            "positions": pos, "group": GROUPS.get(pos[0], "Other") if pos else "Other",
            "loan": p.get("status") == "loaned in",
            "condition": p.get("condition"), "sharpness": p.get("sharpness"), "jadedness": p.get("jadedness"),
            "form": p.get("form") or [], "form_label": p.get("form_label"), "avg_rating": p.get("avg_rating"),
            "apps": p.get("apps"), "injury": injury_text(inj) if inj else None,
            "contract_expires": p.get("contract_expires"), "value": p.get("value"),
            "wage_per_week": p.get("wage_per_week"),
        })
    order = {g: i for i, g in enumerate(("Goalkeepers", "Defenders", "Midfielders", "Attackers", "Other"))}
    out.sort(key=lambda p: (order[p["group"]], POSITIONS.index(p["positions"][0]) if p["positions"] else 99))
    return {"as_of": d.get("game_date"), "players": out}


def fixtures(port_: int | None = None, results: int = 10, upcoming: int = 10) -> dict:
    """The latest results (newest first) and the next fixtures (soonest first)."""
    port_ = port_ or port()
    as_of = (fetch("/api/status", port_).get("latest") or {}).get("game_date")
    keys = ("id", "date", "kickoff", "opponent", "opponent_id", "venue", "competition", "result", "has_stats")
    rows = fetch("/api/fixtures", port_).get("fixtures") or []           # newest first
    played = [r for r in rows if r.get("result")]
    to_come = [r for r in rows if not r.get("result") and (not as_of or r.get("date", "") >= as_of)]

    def trim(r):
        home = r.get("venue") != "A"
        gf, ga = (r.get("home_goals"), r.get("away_goals")) if home else (r.get("away_goals"), r.get("home_goals"))
        return {k: r.get(k) for k in keys} | {"score": None if gf is None else f"{gf}-{ga}"}

    return {"as_of": as_of, "results": [trim(r) for r in played[:results]],
            "upcoming": [trim(r) for r in reversed(to_come[-upcoming:])]}


def crest(club_id: int, port_: int | None = None) -> tuple[bytes, str] | None:
    """A club's crest from the analyst (its FM27 logo pack), or None when there isn't one."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port_ or port()}/api/crest/{int(club_id)}", timeout=5) as r:
            return r.read(), r.headers.get("Content-Type", "image/png")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def start_capture(port_: int | None = None) -> dict:
    """Ask the analyst to capture FM27 now (it reads game memory, the same as its hotkey)."""
    port_ = port_ or port()
    req = urllib.request.Request(f"http://127.0.0.1:{port_}/api/capture", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AnalystUnavailable(f"The FM27 analyst isn't answering on port {port_} ({e}).") from e


def capture_state(port_: int | None = None) -> dict:
    s = fetch("/api/capture", port_ or port())
    return {"running": bool(s.get("running")), "elapsed": s.get("elapsed"), "last": s.get("last")}


# ---- AI coach (the App panel's chat). The analyst holds the provider settings, the keys and the saved conversations;
# the phone only sends questions and reads answers.
CHAT_TIMEOUT_S = 300


def coach_status(port_: int | None = None) -> dict:
    s = fetch("/api/llm/status", port_ or port())
    return {"ready": bool(s.get("ready")), "label": s.get("label") or ""}     # nothing else (no email, no endpoint)


def coach_conversation(cid: str, port_: int | None = None) -> dict | None:
    import urllib.parse
    try:
        d = fetch(f"/api/chats/{urllib.parse.quote(cid, safe='')}", port_ or port())
    except AnalystUnavailable:
        return None
    return {"messages": [{k: m.get(k) for k in ("role", "content", "tools") if m.get(k) is not None}
                         for m in d.get("messages") or [] if m.get("role") in ("user", "assistant")]}


def coach_stream(body: dict, port_: int | None = None):
    """POST the question to the analyst's /api/chat and pass its server-sent events straight through."""
    port_ = port_ or port()
    req = urllib.request.Request(f"http://127.0.0.1:{port_}/api/chat", data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=CHAT_TIMEOUT_S)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise AnalystUnavailable(str(detail)) from e
    except (urllib.error.URLError, OSError) as e:
        raise AnalystUnavailable(f"The FM27 analyst isn't answering on port {port_} ({e}).") from e

    def chunks():
        with r:
            while True:
                b = r.read1(4096)
                if not b:
                    return
                yield b
    return chunks()
