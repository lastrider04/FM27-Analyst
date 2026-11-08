"""Read per-player match stats and group them into matches.

Layout:
  match-stats record (vt gp+0x449EA78, 0x110 bytes) -> one player in one match
  team-in-match block: vector<record*> line-up at +0, team totals just before it;
  the opponent's block sits 0x290 bytes earlier. Each match exists in ~4 identical copies.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import struct
from dataclasses import dataclass, field

import numpy as np

from .fixtures import Fixture
from .memory import Memory
from .people import _fmdate, enumerate_persons
from .process import GameProcess
from .profile import load_profile

UNPACK = {"i16": "<h", "i32": "<i", "u8": "<B", "f32": "<f"}
MIN_PLAYED = 11  # smaller vectors are partial copies, not full line-ups
MAX_LINEUP = 40  # starters + the biggest bench any competition allows, with room to spare


@dataclass
class PlayerMatch:
    person_index: int
    unique_id: int | None
    stats: dict[str, float]
    raw: bytes = b""  # the full 0x110-byte record, kept so unlabelled counters can be decoded later

    @property
    def rating(self) -> float:
        return self.stats["rating_x100"] / 100

    @property
    def played(self) -> bool:
        s = self.stats
        return s["distance_m"] > 0 or s["passes_attempted"] > 0 or s["sub_on_minute"] > 0


@dataclass
class TeamMatch:
    club_id: int | None
    lineup: list[PlayerMatch]
    team_block: list[int] = field(default_factory=list)  # raw team totals, not yet labelled
    conceded: int | None = None     # goals against from our keepers: shots on target faced - saves (None: unknown)


@dataclass
class Match:
    key: str                        # content hash, stable across snapshots
    team: TeamMatch
    opponent: TeamMatch | None      # opponent line-up, only kept when it agrees with the fixture
    fixture: "Fixture | None" = None
    link_confidence: str = "none"   # "high" (goals + opponent agree), "goals", "none"
    # every neighbouring line-up seen beside a copy of this one, by club: the real opponent is among them, but in
    # FM27 a neighbour can also be another match's team, so linking picks the one that fits the fixture
    candidates: dict[int, TeamMatch] = field(default_factory=dict)

    @property
    def goals_by_players(self) -> int:
        return sum(pm.stats["goals"] for pm in self.team.lineup if pm.played)


def game_date(proc: GameProcess, profile: dict | None = None) -> dt.date | None:
    profile = profile or load_profile(proc.build_id())
    raw = proc.read(proc.module(profile["module"]).base + profile["game_date"]["module_rva"], 4)
    return _fmdate(raw) if raw else None


def game_datetime(proc: GameProcess, profile: dict | None = None) -> dt.datetime | None:
    """In-game date and clock (the date's flag bits hold the time, like fixture kick-offs)."""
    from .fixtures import kickoff
    profile = profile or load_profile(proc.build_id())
    raw = proc.read(proc.module(profile["module"]).base + profile["game_date"]["module_rva"], 4)
    d = _fmdate(raw) if raw else None
    t = kickoff(raw) if raw else None
    if not d:
        return None
    h, m = map(int, t.split(":")) if t else (0, 0)
    return dt.datetime(d.year, d.month, d.day, h, m)


def _record(blob: bytes, fields: dict) -> dict[str, float]:
    out = {}
    for k, spec in fields.items():
        v = struct.unpack_from(UNPACK[spec["type"]], blob, spec["off"])[0]
        out[k] = round(v, 4) if spec["type"] == "f32" else v
    return out


def _find_holders(mem: Memory, targets: np.ndarray) -> dict[int, int]:
    """Map holder address -> record address for every 8-byte slot holding a record pointer."""
    out = {}
    if not len(targets):
        return out
    lo, hi = targets.min(), targets.max()
    for base, data in mem.scan_regions(private_only=True):
        pad = (-base) % 8
        arr = np.frombuffer(data, dtype="<u8", offset=pad, count=(len(data) - pad) // 8)
        cand = np.nonzero((arr >= lo) & (arr <= hi))[0]  # cheap range filter before the exact lookup
        if not len(cand):
            continue
        vals = arr[cand]
        pos = np.searchsorted(targets, vals)
        pos[pos == len(targets)] = 0
        for i in cand[targets[pos] == vals]:
            out[base + pad + int(i) * 8] = int(arr[i])
    return out


def vector_records(ptr, holders: dict[int, int], owner: int) -> list[int] | None:
    """The match records of the line-up vector whose header (begin, end, capacity) is at `owner`, or None if it
    isn't a plausible line-up vector. Only [begin, end) counts: pointers just outside it belong to something else."""
    begin, end, cap = ptr(owner), ptr(owner + 8), ptr(owner + 16)
    if not (begin and end and cap) or not begin < end <= cap or (end - begin) % 8:
        return None
    n = (end - begin) // 8
    if not MIN_PLAYED <= n <= MAX_LINEUP:
        return None
    slots = [begin + 8 * i for i in range(n)]
    return [holders[s] for s in slots] if all(s in holders for s in slots) else None


def read_matches(proc: GameProcess, club_id: int, profile: dict | None = None) -> list[Match]:
    """All matches in memory in which `club_id` took part (one entry per match, copies merged)."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    ms = profile["match_stats"]
    fields = {k: v for k, v in ms["fields"].items() if not k.startswith("_")}
    size = ms["size"]
    opp_delta = ms["lineup"]["opponent_owner_delta"]
    tb = ms["lineup"]["team_block"]
    gp = proc.module(profile["module"])
    vt = gp.base + ms["vtable_rva"]

    # person index -> (unique id, club id at, contract club id)
    pf = profile["person"]
    club_off = profile["club"]["fields"]["club_id"]["off"]
    persons: dict[int, tuple[int, int | None]] = {}
    for ref in enumerate_persons(proc, profile):
        idx = mem.i32(ref + pf["fields"]["db_index"]["off"])
        uid = mem.i32(ref + pf["fields"]["unique_id"]["off"])
        cptr = mem.ptr(ref + pf["contract_ptr"]["off"])
        owner_club = mem.ptr(cptr + profile["contract"]["fields"]["club_ptr"]["off"]) if cptr else None
        at_club = mem.ptr(ref + pf["club_ptr"]["off"])
        cid = mem.i32(at_club + club_off) if at_club else None
        persons[idx] = (uid, cid if cid is not None else (mem.i32(owner_club + club_off) if owner_club else None))

    records = np.array(sorted(a for a in mem.find_bytes(struct.pack("<Q", vt), private_only=True,
                                                         limit=500_000) if a % 8 == 0), dtype="<u8")
    holders = _find_holders(mem, records)

    # owner = a vector<record*> header (begin, end, capacity) whose begin is a holder slot. The line-up is exactly
    # [begin, end): neighbouring pointers to other records (another team's vector, or an unrelated structure just
    # before ours) must not be glued onto it, so contiguous runs of holder slots aren't trusted as line-ups.
    owners = _find_holders(mem, np.array(sorted(holders), dtype="<u8"))

    def team(owner: int) -> TeamMatch | None:
        recs = vector_records(mem.ptr, holders, owner)
        if recs is None:
            return None
        lineup = []
        for r in recs:
            blob = proc.read(r, size)
            if not blob or len(blob) < size:
                continue
            st = _record(blob, fields)
            uid, _ = persons.get(st["person_index"], (None, None))
            lineup.append(PlayerMatch(st["person_index"], uid, st, blob))
        conceded = None
        c = ms.get("counters", {})
        if all(k in c for k in ("shots_faced", "saves_held", "saves_parried", "saves_tipped")):
            conceded = 0
            for pm in lineup:
                if pm.played and len(pm.raw) > c["shots_faced"]:
                    b = pm.raw
                    conceded += max(0, b[c["shots_faced"]] - b[c["saves_held"]] - b[c["saves_parried"]] - b[c["saves_tipped"]])
        clubs = [persons.get(pm.person_index, (None, None))[1] for pm in lineup if pm.played]
        club = max(set(clubs), key=clubs.count) if clubs else None
        block = list(struct.unpack(f"<{tb['len'] // 4}i", proc.read(owner + tb["off"], tb["len"]) or b"\0" * tb["len"]))
        return TeamMatch(club, lineup, block, conceded)

    matches: dict[str, Match] = {}
    for owner in owners:
        t = team(owner)
        if not t or t.club_id != club_id or sum(pm.played for pm in t.lineup) < MIN_PLAYED:
            continue
        # the two team blocks are |opp_delta| apart; ours can be either the first or the second
        cands = []
        for delta in (opp_delta, -opp_delta):
            cand = team(owner + delta)
            if cand and cand.club_id not in (None, club_id) and sum(pm.played for pm in cand.lineup) >= MIN_PLAYED:
                cands.append(cand)
        sig = repr(sorted((pm.person_index, pm.stats["rating_x100"], pm.stats["distance_m"]) for pm in t.lineup))
        key = hashlib.sha1(sig.encode()).hexdigest()[:16]
        m = matches.setdefault(key, Match(key, t, None))
        for cand in cands:
            m.candidates.setdefault(cand.club_id, cand)
        if m.opponent is None and cands:
            m.opponent = cands[0]
    return list(matches.values())


CURRENT_SQUAD_SHARE = 0.8  # goals-only links need this share of players still at the club


def link_fixtures(matches: list[Match], fixtures: list[Fixture], club_id: int,
                  today: dt.date | None, window_days: int = 60,
                  current_uids: set[int] | None = None) -> None:
    """Attach each line-up to its fixture (in place).

    Line-ups carry no date, so pairs are scored: our goals must be >= goals scored by our players
    (own goals by the opponent explain any surplus), equality scores higher, a neighbouring
    opponent block whose club matches the fixture opponent scores high, recent fixtures win
    ties. When the line-up knows its goals conceded (keepers' shots on target faced - saves), the
    exact score (for and against) counts most, ahead of a neighbouring opponent, and a fixture
    conceding fewer is ruled out (FM27 keeps many matches' team blocks side by side, so a
    neighbour can belong to another match; the score can't). Assignment is greedy on the best
    score, one fixture per line-up.

    Old line-ups (e.g. last season's) can linger in memory and happen to fit on goals. When
    `current_uids` is given, a link without opponent confirmation is only accepted if most of the
    line-up is still at the club.
    """
    recent = [f for f in fixtures if today is None or 0 <= (today - f.date).days <= window_days]
    pairs = []
    for m in matches:
        played = [pm.unique_id for pm in m.team.lineup if pm.played]
        share = (sum(u in current_uids for u in played) / len(played)) if current_uids and played else 1.0
        g = m.goals_by_players
        for f in recent:
            gf, _ = f.for_club(club_id)
            if gf < g:
                continue
            opp_id = f.away_id if f.home_id == club_id else f.home_id
            opp_ok = opp_id in m.candidates or (m.opponent is not None and m.opponent.club_id == opp_id)
            if not opp_ok and share < CURRENT_SQUAD_SHARE:
                continue
            recency = (today - f.date).days / 30 if today else 0
            conceded, (_, ga) = m.team.conceded, f.for_club(club_id)
            if conceded is None:                         # no keeper data: the neighbouring opponent decides
                score = (100 if opp_ok else 0) + (10 if gf == g else 0) - recency
            elif conceded == ga:                         # the exact score outranks a neighbour, which may be another match's
                score = 100 + (100 if gf == g else 0) + (60 if opp_ok else 0) - recency
            elif conceded < ga and opp_ok:               # fewer only via own goals, and then the opponent must agree
                score = 60 + (10 if gf == g else 0) - recency
            else:
                continue
            pairs.append((score, id(m), m, f, opp_ok))
    used_m, used_f = set(), set()
    for score, _, m, f, opp_ok in sorted(pairs, key=lambda x: -x[0]):
        if id(m) in used_m or id(f) in used_f:
            continue
        used_m.add(id(m))
        used_f.add(id(f))
        m.fixture = f
        m.link_confidence = "high" if opp_ok else "goals"
        opp_id = f.away_id if f.home_id == club_id else f.home_id
        # keep the neighbour that is this fixture's opponent; any other belonged to a different match
        m.opponent = m.candidates.get(opp_id) or (m.opponent if opp_ok else None)
