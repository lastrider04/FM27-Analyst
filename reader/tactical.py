"""Tactical Effectiveness records (FM27): one 0x40-byte record per player per tactic, as the game last worked it out.

The game doesn't keep TE: it computes it when a TE screen (Training > Tactical Effectiveness, or a player's
Development > Tactical Effectiveness) or the match code asks, as an array of 11 records, one per XI slot, and the
arrays stay in the heap after use. A record starts with the player's Person ref and the next opponent's club, then
the 0-100 inputs (see analytics/tactical.py). Once an array is freed the allocator overwrites its first 8 bytes,
so slot 0 (the goalkeeper) loses its Person ref; it is put back from the packed copy the game sends to the UI,
which carries the player's database index instead.

    sets = read_tactical(p, {person ref: unique id})   # [] until the game has worked TE out this session
"""
from __future__ import annotations

import struct

from .memory import Memory
from .process import GameProcess
from .profile import load_profile

REC = 0x40
XI = 11


def _valid(b: bytes, club_vt: int, mem: Memory) -> bool:
    if len(b) < REC or any(b[0x3b:REC]) or any(x > 100 for x in b[0x10:0x3b]):
        return False
    if len(set(b[0x10:0x3b])) < 6:
        return False
    club = struct.unpack_from("<Q", b, 8)[0]
    return bool(club) and mem.ptr(club) == club_vt


_index_cache: dict[bytes, int] = {}          # record inputs -> Person db index (from a packed copy)


def _sig(b: bytes) -> bytes:
    return b[0x11:0x29] + bytes([b[0x10]]) + b[0x29:0x2c]            # 24 area bytes, tactical ability, complexity


def _packed_indexes(mem: Memory, recs: list[bytes], spec: dict) -> None:
    """Fill _index_cache for records whose Person ref was lost, from the packed UI copies (one pass for all)."""
    import re

    todo = {_sig(b): b for b in recs if b[0x10:0x3b] not in _index_cache}
    if not todo:
        return
    pat = re.compile(b"|".join(re.escape(k) for k in todo), re.DOTALL)
    for at in mem.find_bytes(pat, private_only=True, limit=500):
        sig = mem.proc.read(at, 28)
        b = todo.get(sig or b"")
        head = mem.proc.read(at - spec["packed_areas"], spec["packed_size"])
        if b is None or not head or len(head) < spec["packed_size"]:
            continue
        if head[0] == b[0x36] and head[1] == b[0x37]:                    # capability, role suitability
            _index_cache[b[0x10:0x3b]] = struct.unpack_from("<i", head, spec["packed_db_index"])[0]


def _scan(mem: Memory, refs: dict[int, int]):
    """(address, 0x40 bytes) of every 8-aligned slot holding one of `refs` and shaped like a record: the bytes at
    +0x10..+0x37 all <= 127 and +0x3b..+0x3f zero. Shape first (cheap, vectorised), then the pointer match."""
    import numpy as np

    want = np.array(sorted(refs), dtype="<u8")
    hi_bits = np.uint64(0x8080808080808080)
    for base, data in mem.scan_regions(private_only=True):
        pad = (-base) % 8
        arr = np.frombuffer(data, dtype="<u8", offset=pad, count=(len(data) - pad) // 8)
        n = len(arr) - 7
        if n <= 0:
            continue
        near = np.nonzero((arr[:n] >= want[0]) & (arr[:n] <= want[-1]))[0]     # cheap range filter first
        if not len(near):
            continue
        vals = arr[near]
        idx = near[want[np.minimum(np.searchsorted(want, vals), len(want) - 1)] == vals]
        if not len(idx):
            continue
        ok = (arr[idx + 7] >> np.uint64(24)) == 0
        for k in range(2, 7):
            ok &= (arr[idx + k] & hi_bits) == 0
        idx = idx[ok]
        for i in idx:
            off = pad + int(i) * 8
            yield base + off, data[off:off + REC]


def read_tactical(proc: GameProcess, refs: dict[int, int], profile: dict | None = None) -> list[dict]:
    """The TE arrays still in memory for the players in `refs` (Person ref -> unique id).

    Returns [{"club_ptr", "opponent_club_id", "start", "players": [{"slot", "uid", "raw"}]}], one per array found
    (one per tactic the game worked TE out for), duplicates removed.
    """
    profile = profile or load_profile(proc.build_id())
    spec = profile.get("tactical_effectiveness")
    if not spec or not refs:
        return []
    mem = Memory(proc)
    base = proc.module(profile["module"]).base
    club_vt = base + profile["club"]["vtable_rva"]
    club_id_off = profile["club"]["fields"]["club_id"]["off"]
    db_off = spec["person_db_index"]

    hits: dict[int, tuple[int, bytes]] = {}
    for where, b in _scan(mem, refs):
        if _valid(b, club_vt, mem):
            hits[where] = (refs[struct.unpack_from("<Q", b)[0]], b)

    # group records into arrays: same opponent club, 0x40 apart
    arrays: list[dict[int, tuple[int | None, bytes]]] = []
    for where in sorted(hits):
        uid, b = hits[where]
        club = b[8:16]
        for arr in arrays:
            first = min(arr)
            if (where - first) % REC == 0 and where - first < REC * XI and arr[first][1][8:16] == club:
                arr[where] = (uid, b)
                break
        else:
            arrays.append({where: (uid, b)})

    # put back slots whose Person ref was overwritten when the array was freed (the slots just before each array)
    lost: list[tuple[dict, int, bytes]] = []
    for arr in arrays:
        start = min(arr)
        club = arr[start][1][8:16]
        while len(arr) < XI and start - REC not in arr:
            b = mem.proc.read(start - REC, REC)
            if not b or not _valid(b, club_vt, mem) or b[8:16] != club:
                break
            start -= REC
            arr[start] = (None, b)
            lost.append((arr, start, b))
    if lost:
        _packed_indexes(mem, [b for _, _, b in lost], spec)
        by_index = {mem.i32(r + db_off): u for r, u in refs.items()}
        for arr, where, b in lost:
            arr[where] = (by_index.get(_index_cache.get(b[0x10:0x3b], -1)), b)

    out, seen = [], set()
    for arr in arrays:
        start = min(arr)
        club = arr[start][1][8:16]
        players = [{"slot": (w - start) // REC, "uid": u, "raw": b[:REC]} for w, (u, b) in sorted(arr.items())]
        if len(players) < 2 or max(p["slot"] for p in players) >= XI:
            continue
        key = tuple((p["slot"], p["uid"], p["raw"][8:]) for p in players)
        if key in seen:
            continue
        seen.add(key)
        club_ptr = struct.unpack_from("<Q", club)[0]
        out.append({"club_ptr": club_ptr, "opponent_club_id": mem.i32(club_ptr + club_id_off),
                    "start": start, "players": players})
    return out
