"""Offset profiles: one JSON per game build, selected by GameProcess.build_id().

A new build without its own profile can use an *adopted* one: the self-check tries the known profiles and, if one
passes every check against the running game, records it in data/adopted_profiles.json ({new build: profile build}).
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_DIR = Path(__file__).parent / "profiles"
PREFIX = "fm27_"


class UnknownBuild(RuntimeError):
    pass


def _ints(node):
    """Convert "0x.." strings (and "-0x..") to ints, recursively."""
    if isinstance(node, dict):
        return {k: _ints(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_ints(v) for v in node]
    if isinstance(node, str):
        s = node.lstrip("-")
        if s.startswith("0x"):
            v = int(s, 16)
            return -v if node.startswith("-") else v
    return node


def _path(build_id: str) -> Path:
    return PROFILE_DIR / f"{PREFIX}{build_id}.json"


def known_builds() -> list[str]:
    """Builds with a profile of their own, newest file first (the likeliest match for the next patch)."""
    files = sorted(PROFILE_DIR.glob(f"{PREFIX}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem[len(PREFIX):] for p in files]


def _adopted_file() -> Path:
    import app_config           # the user's data folder (kept out of the reader package)
    return app_config.DATA / "adopted_profiles.json"


def adopted() -> dict[str, str]:
    try:
        return json.loads(_adopted_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def adopt(build_id: str, from_build: str) -> None:
    """Use `from_build`'s profile for `build_id` from now on (the self-check has just verified it)."""
    a = adopted()
    a[build_id] = from_build
    f = _adopted_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(a, indent=2), encoding="utf-8")


def load_profile_file(build_id: str) -> dict:
    return _ints(json.loads(_path(build_id).read_text(encoding="utf-8")))


def load_profile(build_id: str) -> dict:
    if _path(build_id).exists():
        return load_profile_file(build_id)
    src = adopted().get(build_id)
    if src and _path(src).exists():
        profile = load_profile_file(src)
        profile["adopted_from"] = src
        return profile
    raise UnknownBuild(
        f"No offset profile for game build {build_id}. The game was probably patched; "
        f"run recalibration. Known profiles: {[PREFIX + b for b in known_builds()]}")
