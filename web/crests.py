"""Club crests from the logo pack installed for FM27 (e.g. TCM or the FMG standard logos), if there is one.

FM27 ships without real logos; players add a pack under Documents\\Sports Interactive\\Football Manager 27\\graphics.
Packs map each picture to a club with config.xml files, like
    <record from="TCM1_676" to="graphics/pictures/club/676/logo"/>
and the number is the club's ID in the game database, the same ID the reader uses. This reads those mappings (and
files simply named <club id>.png in a "club" folder) into an index, cached in data/crest_index.json and rebuilt when
the graphics folder changes. Only files found this way are ever served. With no pack, the app keeps its initials badge.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import app_config

RECORD = re.compile(r'<record\s+from="([^"]+)"\s+to="graphics/pictures/(?:club|team)/(\d+)/(logo|icon)"', re.I)
EXTS = (".png", ".jpg", ".jpeg")
REBUILD_AFTER = 7 * 86400        # also rebuild weekly, in case a pack was updated in place

_lock = threading.Lock()
_index: dict[str, str] | None = None
_building = False


def graphics_dirs() -> list[Path]:
    """FM27's graphics folders: a configured one, else Documents (or OneDrive Documents)."""
    custom = app_config.load_config().get("graphics_dir")
    if custom:
        return [Path(custom)]
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    found = []
    for docs in (home / "Documents", home / "OneDrive" / "Documents"):
        g = docs / "Sports Interactive" / "Football Manager 27" / "graphics"
        if g.is_dir():
            found.append(g)
    return found


def _signature(dirs: list[Path]) -> list:
    """Changes when a pack is added or removed (top-level folders' modified times)."""
    sig = []
    for g in dirs:
        try:
            sig.append([str(g), g.stat().st_mtime] + sorted([e.name, e.stat().st_mtime] for e in os.scandir(g)
                                                            if e.is_dir()))
        except OSError:
            pass
    return sig


def _picture(folder: Path, name: str) -> Path | None:
    for ext in ("",) + EXTS:
        p = folder / (name + ext)
        if p.suffix.lower() in EXTS and p.is_file():
            return p
    return None


def build(dirs: list[Path]) -> dict[str, str]:
    """{club id: picture path}. A "logo" mapping wins over an "icon" one."""
    logos: dict[str, str] = {}
    icons: dict[str, str] = {}
    named: dict[str, str] = {}
    for g in dirs:
        for root, _dirs, files in os.walk(g):
            folder = Path(root)
            if "config.xml" in files:
                try:
                    text = (folder / "config.xml").read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    text = ""
                for src, cid, kind in RECORD.findall(text):
                    target = logos if kind.lower() == "logo" else icons
                    if cid in target:
                        continue
                    p = _picture(folder, src)
                    if p:
                        target[cid] = str(p)
            if "club" in root.lower():
                for f in files:
                    stem, ext = os.path.splitext(f)
                    if stem.isdigit() and ext.lower() in EXTS:
                        named.setdefault(stem, str(folder / f))
    return {**named, **icons, **logos}


def _cache_file() -> Path:
    return app_config.DATA / "crest_index.json"


def _load_or_build() -> dict[str, str]:
    dirs = graphics_dirs()
    sig = _signature(dirs)
    try:
        cached = json.loads(_cache_file().read_text(encoding="utf-8"))
        if cached.get("sig") == sig and time.time() - cached.get("at", 0) < REBUILD_AFTER:
            return cached["index"]
    except (OSError, ValueError, KeyError):
        pass
    index = build(dirs) if dirs else {}
    try:
        _cache_file().parent.mkdir(parents=True, exist_ok=True)
        _cache_file().write_text(json.dumps({"sig": sig, "at": time.time(), "index": index}), encoding="utf-8")
    except OSError:
        pass
    print(f"[crests] {len(index)} club crests found" + (f" in {', '.join(map(str, dirs))}" if dirs else
                                                     " (no FM27 graphics folder)"))
    return index


def warm() -> None:
    """Build the index in the background (a big pack takes a few seconds to scan the first time)."""
    global _building
    with _lock:
        if _index is not None or _building:
            return
        _building = True

    def run():
        global _index, _building
        try:
            idx = _load_or_build()
        except Exception as e:  # noqa: BLE001  (never take the app down over logos)
            print(f"[crests] couldn't read the logo pack: {e}")
            idx = {}
        with _lock:
            _index, _building = idx, False

    threading.Thread(target=run, name="crests", daemon=True).start()


def path_for(club_id: int) -> Path | None:
    """The crest picture for a club, or None (no pack, not in it, or still scanning)."""
    if _index is None:
        warm()
        return None
    p = _index.get(str(int(club_id)))
    return Path(p) if p and Path(p).is_file() else None


def ready() -> bool:
    return _index is not None


def status() -> dict:
    """For Settings › Appearance: whether a logo pack was found, and where to put one."""
    dirs = graphics_dirs()
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    where = str(dirs[0] if dirs else home / "Documents" / "Sports Interactive" / "Football Manager 27" / "graphics")
    if _index is None:
        warm()
    return {"scanning": _index is None, "count": len(_index or {}), "folder": where, "found_folder": bool(dirs)}


def rescan() -> None:
    """Forget the index and look again (after installing a pack)."""
    global _index
    try:
        _cache_file().unlink()
    except OSError:
        pass
    with _lock:
        _index = None
    warm()
