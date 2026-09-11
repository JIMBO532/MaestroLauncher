"""Reading what a Minecraft world says about itself.

Exists for one question: is this world about to be opened by a newer version than
the one that made it? Minecraft upgrades a world's format on load and does not
put it back, so a world opened once in a newer version cannot be opened in the
older one again. That is worth a warning before it happens.

The answer is in the world's ``level.dat`` (gzipped NBT) as ``Data.DataVersion``,
an integer that only ever goes up, and in the client jar's own ``version.json``
as ``world_version``. Comparing those two is exact. Comparing the version *names*
would not be -- Mojang has used "1.21.11" and "26.2" in the same year, and no
string ordering puts those in the right order.

Only enough NBT is implemented to walk a compound and read the few fields that
matter. This is not a general NBT library and should not become one.
"""

from __future__ import annotations

import gzip
import json
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional

# NBT tag ids, per https://minecraft.wiki/w/NBT_format
_END = 0
_BYTE = 1
_SHORT = 2
_INT = 3
_LONG = 4
_FLOAT = 5
_DOUBLE = 6
_BYTE_ARRAY = 7
_STRING = 8
_LIST = 9
_COMPOUND = 10
_INT_ARRAY = 11
_LONG_ARRAY = 12

_FIXED = {
    _BYTE: 1,
    _SHORT: 2,
    _INT: 4,
    _LONG: 8,
    _FLOAT: 4,
    _DOUBLE: 8,
}


class WorldError(RuntimeError):
    """A world or a client jar could not be read."""


def _read(stream: BinaryIO, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise WorldError("level.dat ended in the middle of a tag.")
    return data


def _read_string(stream: BinaryIO) -> str:
    (length,) = struct.unpack(">H", _read(stream, 2))
    # NBT strings are modified UTF-8; for the fields read here plain UTF-8 is
    # identical, and a world name with an unusual byte is not worth failing over.
    return _read(stream, length).decode("utf-8", errors="replace")


def _read_payload(stream: BinaryIO, tag: int) -> Any:
    if tag in _FIXED:
        size = _FIXED[tag]
        raw = _read(stream, size)
        formats = {1: ">b", 2: ">h", 4: ">i", 8: ">q"}
        if tag == _FLOAT:
            return struct.unpack(">f", raw)[0]
        if tag == _DOUBLE:
            return struct.unpack(">d", raw)[0]
        return struct.unpack(formats[size], raw)[0]

    if tag == _STRING:
        return _read_string(stream)

    if tag == _BYTE_ARRAY:
        (length,) = struct.unpack(">i", _read(stream, 4))
        stream.seek(max(length, 0), 1)
        return None

    if tag in (_INT_ARRAY, _LONG_ARRAY):
        (length,) = struct.unpack(">i", _read(stream, 4))
        stream.seek(max(length, 0) * (4 if tag == _INT_ARRAY else 8), 1)
        return None

    if tag == _LIST:
        (item_tag,) = struct.unpack(">b", _read(stream, 1))
        (length,) = struct.unpack(">i", _read(stream, 4))
        for _ in range(max(length, 0)):
            _read_payload(stream, item_tag)
        return None

    if tag == _COMPOUND:
        result: dict[str, Any] = {}
        while True:
            (child_tag,) = struct.unpack(">b", _read(stream, 1))
            if child_tag == _END:
                return result
            name = _read_string(stream)
            result[name] = _read_payload(stream, child_tag)

    raise WorldError(f"Unknown NBT tag {tag}.")


def read_level_dat(path: Path | str) -> dict:
    """Parse a level.dat into nested dicts. Raises WorldError if it cannot."""
    try:
        with gzip.open(Path(path), "rb") as stream:
            (tag,) = struct.unpack(">b", _read(stream, 1))
            if tag != _COMPOUND:
                raise WorldError("level.dat does not start with a compound tag.")
            _read_string(stream)  # the root tag's name, always empty in practice
            return _read_payload(stream, _COMPOUND)
    except WorldError:
        raise
    except (OSError, struct.error, EOFError, gzip.BadGzipFile) as exc:
        raise WorldError(f"Could not read {path}: {exc}") from exc


@dataclass(frozen=True)
class World:
    """One world folder, and the game version that last wrote it."""

    name: str
    folder: str
    data_version: int
    version_name: str


def read_world(folder: Path | str) -> Optional[World]:
    """Describe a world folder, or None if it is not one we can read."""
    path = Path(folder)
    level = path / "level.dat"
    if not level.is_file():
        return None

    try:
        data = read_level_dat(level).get("Data")
    except WorldError:
        return None
    if not isinstance(data, dict):
        return None

    version = data.get("Version")
    version_name = ""
    if isinstance(version, dict):
        version_name = str(version.get("Name") or "")

    raw_data_version = data.get("DataVersion")
    if not isinstance(raw_data_version, int):
        return None

    return World(
        name=str(data.get("LevelName") or path.name),
        folder=path.name,
        data_version=raw_data_version,
        version_name=version_name,
    )


def list_worlds(saves_directory: Path | str) -> list[World]:
    """Every readable world in a saves folder."""
    path = Path(saves_directory)
    try:
        candidates = sorted(p for p in path.iterdir() if p.is_dir())
    except OSError:
        return []
    return [world for world in (read_world(p) for p in candidates) if world]


def client_world_version(version_id: str, directory: Path | str) -> Optional[int]:
    """The world format a version writes, from ``version.json`` inside its jar.

    Returns None when the jar is missing or says nothing -- a profile that
    inherits from another has no jar of its own, so callers resolve to the base
    version first.
    """
    jar = Path(directory).expanduser() / "versions" / version_id / f"{version_id}.jar"
    try:
        with zipfile.ZipFile(jar) as archive:
            payload = json.loads(archive.read("version.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None

    value = payload.get("world_version")
    return value if isinstance(value, int) else None


def worlds_needing_upgrade(
    saves_directory: Path | str,
    version_id: str,
    directory: Path | str,
) -> list[World]:
    """Worlds that this version would upgrade, and could not then downgrade.

    Empty when the version is the same age as every world, older than them, or
    when the client jar does not say -- reporting nothing is right in all three,
    because the point is to warn about a one-way change and not to editorialise.
    """
    target = client_world_version(version_id, directory)
    if target is None:
        return []
    return [
        world
        for world in list_worlds(saves_directory)
        if world.data_version < target
    ]
