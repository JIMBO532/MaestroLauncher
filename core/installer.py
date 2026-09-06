"""Game file installation for MaestroLauncher.

Owns everything to do with getting Minecraft onto disk: vanilla versions and the
Fabric loader. Knows nothing about accounts, mods, or the GUI -- keep it that way
so it stays testable without a login.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import minecraft_launcher_lib as mll


@dataclass(frozen=True)
class Progress:
    """A single progress tick reported during an install."""

    status: str
    current: int
    total: int

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(self.current / self.total, 1.0)

    @property
    def percent(self) -> int:
        return int(self.fraction * 100)


ProgressCallback = Callable[[Progress], None]


class InstallError(RuntimeError):
    """Anything that stopped an install from finishing."""


def _build_callback(on_progress: ProgressCallback) -> dict:
    """Adapt our single-callback API to the library's three-callback dict."""
    state = {"status": "", "current": 0, "total": 0}

    def emit() -> None:
        on_progress(Progress(state["status"], state["current"], state["total"]))

    def set_status(text: str) -> None:
        state["status"] = text
        state["current"] = 0
        emit()

    def set_progress(value: int) -> None:
        state["current"] = value
        emit()

    def set_max(value: int) -> None:
        state["total"] = value

    return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}


def _prepare_directory(directory: Path | str) -> Path:
    path = Path(directory).expanduser().resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"Cannot create game directory {path}: {exc}") from exc
    return path


def default_directory() -> Path:
    """The standard .minecraft location for this OS."""
    return Path(mll.utils.get_minecraft_directory())


def list_releases() -> list[str]:
    """Every released (non-snapshot) version, newest first."""
    try:
        return [v["id"] for v in mll.utils.get_version_list() if v["type"] == "release"]
    except Exception as exc:  # network, malformed manifest
        raise InstallError(f"Could not fetch the version list: {exc}") from exc


def latest_release() -> str:
    try:
        return mll.utils.get_latest_version()["release"]
    except Exception as exc:
        raise InstallError(f"Could not fetch the latest version: {exc}") from exc


def is_installed(version_id: str, directory: Path | str) -> bool:
    """True if this version is already present and usable in this directory."""
    return mll.utils.is_version_valid(version_id, str(Path(directory).expanduser()))


def installed_versions(directory: Path | str) -> list[str]:
    path = Path(directory).expanduser()
    if not path.exists():
        return []
    return [v["id"] for v in mll.utils.get_installed_versions(str(path))]


def install_version(
    version_id: str,
    directory: Path | str,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """Download and install a vanilla version. Safe to call if already installed.

    Returns the resolved game directory.
    """
    path = _prepare_directory(directory)
    callback = _build_callback(on_progress) if on_progress else None

    try:
        mll.install.install_minecraft_version(version_id, str(path), callback=callback)
    except mll.exceptions.VersionNotFound as exc:
        raise InstallError(f"Minecraft version '{version_id}' does not exist.") from exc
    except OSError as exc:
        raise InstallError(f"Failed writing game files to {path}: {exc}") from exc

    return path


def install_fabric_loader(
    minecraft_version: str,
    directory: Path | str,
    loader_version: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> str:
    """Install the Fabric loader for a version. Returns the new profile ID to launch.

    The profile ID is discovered by diffing installed versions rather than by
    guessing Fabric's naming scheme, which has changed before.

    Requires a JRE on PATH -- the Fabric installer is a Java jar.
    """
    path = _prepare_directory(directory)

    # get_java_executable() falls back to the bare string "java"/"javaw" when it
    # finds nothing, so it can never be None. Check the path is real.
    java = mll.utils.get_java_executable()
    if not (Path(java).is_file() or shutil.which(java)):
        raise InstallError(
            "No Java runtime found. Fabric's installer is a Java jar and needs one "
            "on PATH or in JAVA_HOME."
        )

    if not mll.fabric.is_minecraft_version_supported(minecraft_version):
        raise InstallError(f"Fabric does not support Minecraft {minecraft_version}.")

    before = set(installed_versions(path))
    callback = _build_callback(on_progress) if on_progress else None

    try:
        mll.fabric.install_fabric(
            minecraft_version,
            str(path),
            loader_version=loader_version,
            callback=callback,
        )
    except mll.exceptions.UnsupportedVersion as exc:
        raise InstallError(f"Fabric rejected version '{minecraft_version}'.") from exc
    except mll.exceptions.ExternalProgramError as exc:
        raise InstallError(f"The Fabric installer failed: {exc}") from exc
    except OSError as exc:
        raise InstallError(f"Failed writing Fabric files to {path}: {exc}") from exc

    new = set(installed_versions(path)) - before
    if not new:
        raise InstallError("Fabric reported success but created no launch profile.")
    return sorted(new)[-1]
