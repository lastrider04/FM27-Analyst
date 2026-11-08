"""Reader self-check: is the offset profile still right for the running game build?

Run when the game starts. A patch usually changes game_plugin.dll, so the build has no profile (UnknownBuild). Small
patches often leave the data where it was, so for an unknown build each known profile is tried: if one passes every
check against the user's own squad, it's adopted for that build (see profile.adopt) and captures carry on. If none
passes, or a known build's values look wrong, captures are paused until the reader is recalibrated.
"""
from __future__ import annotations

import datetime as dt
import time

from .process import GameProcess
from .profile import UnknownBuild, adopt, known_builds, load_profile, load_profile_file

MIN_PLAYERS = 11


def self_check(proc: GameProcess, club_id: int | None) -> dict:
    """{status: ok | unknown_build | failed, build_id, checks: [{name, ok, detail}], seconds}"""
    t0 = time.time()
    build = proc.build_id()
    try:
        profile = load_profile(build)
    except UnknownBuild as e:
        return _try_known_profiles(proc, club_id, build, str(e), t0)
    detail = profile.get("game_version", build)
    if profile.get("adopted_from"):
        detail += f" (offsets from build {profile['adopted_from']})"
    return _run_checks(proc, club_id, profile, build, [{"name": "game build recognised", "ok": True, "detail": detail}], t0)


def _try_known_profiles(proc: GameProcess, club_id: int | None, build: str, why: str, t0: float) -> dict:
    """A new build: adopt the first known profile that passes every check (a full squad check needs the club)."""
    unknown = {"status": "unknown_build", "build_id": build, "seconds": 0.0,
               "checks": [{"name": "game build recognised", "ok": False, "detail": why}]}
    candidates = known_builds()
    if club_id is None or not candidates:
        unknown["seconds"] = round(time.time() - t0, 1)
        return unknown
    for src in candidates:
        r = _run_checks(proc, club_id, load_profile_file(src), build, [], t0)
        if r["status"] == "ok":
            adopt(build, src)
            r["checks"].insert(0, {"name": "game build recognised", "ok": True,
                                   "detail": f"new build {build}: the offsets from build {src} still match, so they're used"})
            return r
    unknown["checks"][0]["detail"] = (f"{why} None of the known profiles ({', '.join(candidates)}) matches this build's data "
                                      "yet - if the save is still loading, this is checked again shortly.")
    unknown["adoption_tried"] = True      # lets the app retry while a save loads, like a failed check
    unknown["seconds"] = round(time.time() - t0, 1)
    return unknown


def _run_checks(proc: GameProcess, club_id: int | None, profile: dict, build: str, checks: list[dict], t0: float) -> dict:
    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    from .matches import game_date
    try:
        d = game_date(proc, profile)
    except Exception as e:      # noqa: BLE001 - any read error is a failed check
        d, err = None, str(e)
    else:
        err = ""
    add("game date readable", d is not None and 1990 <= d.year <= 2100, d.isoformat() if d else err or "unreadable")

    from .fixtures import read_club_names
    try:
        names = read_club_names(proc, profile)
    except Exception as e:      # noqa: BLE001
        names, err = {}, str(e)
    add("club names readable", len(names) > 500 and (club_id is None or club_id in names),
        (f"{len(names)} clubs" + (f"; your club: {names.get(club_id, 'not found')}" if club_id is not None else ""))
        if names else err)

    if club_id is not None:     # no club chosen yet: the squad check waits until one is
        from .people import read_club_players
        try:
            players = read_club_players(proc, club_id, profile)
        except Exception as e:      # noqa: BLE001
            players, err = [], str(e)
        else:
            err = ""
        named = sum(1 for p in players if p.name)
        sane = sum(1 for p in players if p.fitness is not None and 0 <= p.fitness <= 100 and 1 <= p.ca <= 200)
        ok = len(players) >= MIN_PLAYERS and named >= 0.9 * len(players) and sane >= 0.9 * len(players)
        add("squad readable", ok, f"{len(players)} players, {named} named, {sane} with sane CA/condition" if players else err or "no players")

    status = "ok" if all(c["ok"] for c in checks) else "failed"
    return {"status": status, "build_id": build, "game_date": d.isoformat() if d else None, "checks": checks,
            "seconds": round(time.time() - t0, 1), "checked_at": dt.datetime.now().isoformat(sep=" ", timespec="seconds")}
