"""Club details beyond the name: the club's primary colour (used to theme the dashboard)."""
from __future__ import annotations

from .memory import Memory
from .people import TEAM_OBJECTS
from .process import GameProcess
from .profile import load_profile


def read_club_colour(proc: GameProcess, club_id: int, profile: dict | None = None) -> str | None:
    """The club's primary colour as "#rrggbb", or None.

    TEAM -> pointer at colour.ptr -> 4 bytes at colour.off, stored blue, green, red, alpha (alpha 255 when set).
    The TEAM object comes from read_club_players (each player points to their club), so call that first.
    """
    profile = profile or load_profile(proc.build_id())
    spec = profile["club"].get("colour")
    team = TEAM_OBJECTS.get((proc.pid, club_id))
    if not spec or not team:
        return None
    mem = Memory(proc)
    sub = mem.ptr(team + spec["ptr"])
    raw = proc.read(sub + spec["off"], 4) if sub else None
    if not raw or len(raw) < 4 or raw[3] != 255:
        return None
    b, g, r = raw[0], raw[1], raw[2]
    return f"#{r:02x}{g:02x}{b:02x}"
