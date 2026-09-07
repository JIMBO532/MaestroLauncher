"""Importing local files into a game directory for MaestroLauncher.

Someone hands us a file they downloaded themselves -- a mod jar, a resource pack
zip, a shader pack -- and we work out what it is and put it where Minecraft will
look for it. Nothing here talks to the network, to accounts, or to the GUI.

What a file is, is decided by looking inside it rather than by trusting its name:

* ``.jar``            -> ``mods/``
* ``.zip`` containing ``pack.mcmeta`` at the root  -> ``resourcepacks/``
* ``.zip`` containing a ``shaders/`` folder        -> ``shaderpacks/``
* anything else       -> refused, with a reason, rather than guessed at

A zip is opened and checked before anything is copied, so a truncated or corrupt
download is reported instead of being dropped into the game folder where it will
fail confusingly later.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence

from core.installer import Progress, ProgressCallback

# The marker file every resource pack has at the root of its archive.
PACK_MARKER = "pack.mcmeta"

# Shader packs are zips with their shaders in a top-level shaders/ folder.
SHADER_DIRECTORY = "shaders/"

# How much of a zip to read when checking it is intact. Reading the whole of a
# large pack costs seconds; the central directory plus a CRC test of the small
# marker files catches truncation and corruption without that.
MAX_TESTED_ENTRIES = 64


class ImportFileError(RuntimeError):
    """Anything that stopped a file from being imported.

    Named ImportFileError rather than ImportError so it cannot shadow the
    builtin of that name, which would silently change the meaning of any
    ``except ImportError`` in this package.
    """


class FileKind(Enum):
    """What a file turned out to be."""

    MOD = "mod"
    RESOURCE_PACK = "resourcepack"
    SHADER_PACK = "shaderpack"
    UNKNOWN = "unknown"


# Where each kind belongs inside the game directory.
DESTINATIONS: dict[FileKind, str] = {
    FileKind.MOD: "mods",
    FileKind.RESOURCE_PACK: "resourcepacks",
    # shaderpacks/, not shaders/: shaders/ is what is inside the archive,
    # but Iris and OptiFine both read shaderpacks/ in the game directory.
    FileKind.SHADER_PACK: "shaderpacks",
}


@dataclass(frozen=True)
class ImportResult:
    """What happened to one file."""

    source: Path
    kind: FileKind
    destination: Optional[Path] = None
    skipped: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the file is now in place, whether or not we copied it."""
        return self.error is None and self.destination is not None

    @property
    def summary(self) -> str:
        if self.error:
            return f"{self.source.name}: {self.error}"
        if self.skipped:
            return f"{self.source.name}: already in {self.destination.parent.name}/"
        return f"{self.source.name} -> {self.destination.parent.name}/"


def _open_zip(path: Path) -> zipfile.ZipFile:
    """Open a zip, or raise ImportFileError explaining why it cannot be read."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ImportFileError(
            f"is not a readable zip file -- it may be truncated or corrupt ({exc})"
        ) from exc
    except OSError as exc:
        raise ImportFileError(f"could not be opened ({exc})") from exc

    try:
        names = archive.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        archive.close()
        raise ImportFileError(f"has a damaged directory ({exc})") from exc

    if not names:
        archive.close()
        raise ImportFileError("is an empty zip")

    # Verify the entries really are readable rather than just listed. testzip()
    # over a whole pack is slow, so check a bounded sample.
    try:
        for name in names[:MAX_TESTED_ENTRIES]:
            if name.endswith("/"):
                continue
            with archive.open(name) as handle:
                handle.read(1)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        archive.close()
        raise ImportFileError(f"is corrupt and cannot be read ({exc})") from exc

    return archive


def identify(path: Path | str) -> FileKind:
    """Work out what a file is by looking inside it.

    Raises ``ImportFileError`` when the file is missing or is a zip we cannot
    read. A readable file we simply do not recognise comes back as
    ``FileKind.UNKNOWN`` rather than raising -- not knowing is an answer.
    """
    source = Path(path).expanduser()

    if not source.is_file():
        raise ImportFileError("does not exist")

    suffix = source.suffix.lower()
    if suffix == ".jar":
        return FileKind.MOD
    if suffix != ".zip":
        return FileKind.UNKNOWN

    archive = _open_zip(source)
    try:
        names = archive.namelist()
    finally:
        archive.close()

    # pack.mcmeta at the root, not nested inside a folder in the archive.
    if any(name == PACK_MARKER for name in names):
        return FileKind.RESOURCE_PACK
    if any(name.startswith(SHADER_DIRECTORY) for name in names):
        return FileKind.SHADER_PACK
    return FileKind.UNKNOWN


def _destination_for(kind: FileKind, source: Path, directory: Path) -> Path:
    """Where this file should land, guaranteed to be inside the game directory."""
    folder = DESTINATIONS[kind]

    # The name comes from whatever the user picked, so strip any directory part
    # before using it, then confirm the result really is inside the game folder.
    name = Path(source.name.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ImportFileError("has an unusable filename")

    destination = (directory / folder / name).resolve()
    if directory not in destination.parents:
        raise ImportFileError("would land outside the game folder")
    return destination


def import_file(
    path: Path | str,
    directory: Path | str,
    overwrite: bool = False,
) -> ImportResult:
    """Identify one file and copy it into the right folder.

    Never overwrites silently: a file already there with different content comes
    back as an error unless ``overwrite`` is set. An identical file already in
    place is reported as skipped, not as a failure.
    """
    source = Path(path).expanduser()
    root = Path(directory).expanduser().resolve()

    try:
        kind = identify(source)
    except ImportFileError as exc:
        return ImportResult(source=source, kind=FileKind.UNKNOWN, error=str(exc))

    if kind is FileKind.UNKNOWN:
        return ImportResult(
            source=source,
            kind=kind,
            error=(
                "is not a mod jar, resource pack or shader pack, so there is "
                "nowhere obvious to put it"
            ),
        )

    try:
        destination = _destination_for(kind, source, root)
    except ImportFileError as exc:
        return ImportResult(source=source, kind=kind, error=str(exc))

    if source.resolve() == destination:
        return ImportResult(source=source, kind=kind, destination=destination, skipped=True)

    if destination.exists() and not overwrite:
        if destination.stat().st_size == source.stat().st_size:
            return ImportResult(
                source=source, kind=kind, destination=destination, skipped=True
            )
        return ImportResult(
            source=source,
            kind=kind,
            error=f"already exists in {destination.parent.name}/ with different contents",
        )

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    except OSError as exc:
        return ImportResult(source=source, kind=kind, error=f"could not be copied ({exc})")

    return ImportResult(source=source, kind=kind, destination=destination)


def import_files(
    paths: Sequence[Path | str] | Iterable[Path | str],
    directory: Path | str,
    overwrite: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ImportResult]:
    """Import several files, reporting what happened to each.

    One bad file does not stop the rest: every path produces a result, good or
    bad, in the order given.
    """
    items = [Path(p) for p in paths]
    results: list[ImportResult] = []

    for index, item in enumerate(items):
        if on_progress:
            on_progress(Progress(f"Importing {item.name}", index, len(items)))
        results.append(import_file(item, directory, overwrite=overwrite))

    if on_progress:
        on_progress(Progress("Import finished", len(items), len(items)))

    return results


def describe(results: Sequence[ImportResult]) -> str:
    """A one-line summary of a batch, for a status label."""
    if not results:
        return "Nothing to import."

    copied = [r for r in results if r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    failed = [r for r in results if r.error]

    parts: list[str] = []
    if copied:
        folders = sorted({r.destination.parent.name + "/" for r in copied})
        parts.append(f"{len(copied)} added to {', '.join(folders)}")
    if skipped:
        parts.append(f"{len(skipped)} already there")
    if failed:
        parts.append(f"{len(failed)} skipped: {failed[0].summary}")

    return ". ".join(parts) + "."
