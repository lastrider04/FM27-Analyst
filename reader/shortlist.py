"""The manager's shortlist called "FM Analyst": which players are on it, and when each was added.

FM keeps each shortlist as an object holding its name (a length-prefixed UTF-8 string, via a pointer) and a vector of
entry pointers; each entry points to the player's Person record and holds the date the player was added. There is no
static path to it, so it is found by its name once per game session (the name string, then the object pointing to it)
and re-checked on every read.

    with GameProcess() as p:
        entries = read_shortlist(p)      # None: no shortlist with that name; else [(person ref, date added), ...]
"""
from __future__ import annotations

import datetime as dt
import struct

from .memory import Memory
from .people import _fmdate
from .process import GameProcess
from .profile import load_profile

SHORTLIST_NAME = "FM Analyst"
MAX_ENTRIES = 500

_found: dict[tuple[int, str], int] = {}      # (game pid, name) -> shortlist object address


def _entries(mem: Memory, obj: int, spec: dict, person_vt: int) -> list[tuple[int, dt.date | None]] | None:
    """The entries of the shortlist object at `obj`, or None if it doesn't look like one."""
    beg, end = mem.ptr(obj + spec["entries"]), mem.ptr(obj + spec["entries"] + 8)
    if beg is None or end is None or end < beg or (end - beg) % 8 or (end - beg) // 8 > MAX_ENTRIES:
        return None
    if beg == end:
        return []
    data = mem.proc.read(beg, end - beg)
    if not data or len(data) != end - beg:
        return None
    out = []
    for (entry,) in struct.iter_unpack("<Q", data):
        person = mem.ptr(entry + spec["entry"]["person_ptr"]) if entry else None
        if not person or mem.ptr(person) != person_vt:
            return None                         # every entry must point to a Person
        raw = mem.proc.read(entry + spec["entry"]["added"], 4)
        out.append((person, _fmdate(raw) if raw and len(raw) == 4 else None))
    return out


def _name_at(mem: Memory, obj: int, spec: dict) -> str | None:
    s = mem.ptr(obj + spec["name_ptr"])
    n = mem.i32(s) if s else None
    if not n or not 0 < n < 128:
        return None
    raw = mem.proc.read(s + 4, n)
    return raw.decode("utf-8", "replace") if raw else None


def read_shortlist(proc: GameProcess, profile: dict | None = None, name: str = SHORTLIST_NAME
                   ) -> list[tuple[int, dt.date | None]] | None:
    """[(Person address, date added)] for the shortlist called `name`, or None if there is no such shortlist."""
    profile = profile or load_profile(proc.build_id())
    spec = profile.get("shortlist")
    if not spec:
        return None
    mem = Memory(proc)
    person_vt = proc.module(profile["module"]).base + profile["person"]["vtable_rva"]
    key = (proc.pid, name)
    obj = _found.get(key)
    if obj and _name_at(mem, obj, spec) == name:
        got = _entries(mem, obj, spec, person_vt)
        if got is not None:
            return got
    _found.pop(key, None)

    raw = name.encode("utf-8")
    strings = mem.find_bytes(struct.pack("<i", len(raw)) + raw, private_only=True, limit=5000)
    if not strings:
        return None
    best: tuple[int, list] | None = None
    for where, _ in mem.find_qwords(strings, private_only=True, limit=20_000):
        cand = where - spec["name_ptr"]
        got = _entries(mem, cand, spec, person_vt)
        if got is None:
            continue
        # the game object has a real entries vector; UI copies of the name sit next to other data. Prefer the
        # candidate with entries, then the one with the most.
        if best is None or len(got) > len(best[1]):
            best = (cand, got)
    if best is None:
        return None
    if best[1]:
        _found[key] = best[0]     # only cache a non-empty one: an empty vector could be a look-alike
    return best[1]
