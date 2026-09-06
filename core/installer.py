"""Game file installation for MaestroLauncher.

Owns everything to do with getting Minecraft onto disk: vanilla versions and the
Fabric loader. Knows nothing about accounts, mods, or the GUI -- keep it that way
so it stays testable without a login.
"""

from __future__ import annotations

import json
import os
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


def _runtime_executable(runtime_name: str, directory: Path) -> Optional[str]:
    """The java binary for one of Mojang's runtimes, if it is really on disk."""
    try:
        executable = mll.runtime.get_executable_path(runtime_name, str(directory))
    except Exception:
        return None
    if executable and Path(executable).is_file():
        return executable
    return None


def find_java_executable(
    directory: Path | str,
    version_id: Optional[str] = None,
) -> Optional[str]:
    """Find a Java runtime to use for this game directory.

    Looked for in this order:

    1. The runtime Mojang ships for ``version_id``, which ``install_version()``
       has already downloaded into ``<directory>/runtime/``.
    2. Any other runtime installed in that directory -- a Fabric profile's own
       json does not declare one, so it falls through to here.
    3. ``java`` or ``javaw`` on PATH.
    4. ``JAVA_HOME``.

    Returns None when there is no Java anywhere, leaving the caller to raise the
    error that suits it. Preferring the bundled runtime matters: a machine can
    have a perfectly good JRE inside the game directory and nothing on PATH.
    """
    path = Path(directory).expanduser()

    if version_id:
        try:
            information = mll.runtime.get_version_runtime_information(version_id, str(path))
        except Exception:
            information = None
        if information:
            executable = _runtime_executable(information["name"], path)
            if executable:
                return executable

    try:
        installed = mll.runtime.get_installed_jvm_runtimes(str(path))
    except Exception:
        installed = []
    # Any runtime that actually runs will do by this point; there is no
    # meaningful ordering between Mojang's runtime names.
    for name in installed:
        executable = _runtime_executable(name, path)
        if executable:
            return executable

    for candidate in ("java", "javaw"):
        found = shutil.which(candidate)
        if found:
            return found

    java_home = os.environ.get("JAVA_HOME", "").strip()
    if java_home:
        for name in ("java.exe", "java", "javaw.exe", "javaw"):
            candidate_path = Path(java_home) / "bin" / name
            if candidate_path.is_file():
                return str(candidate_path)

    return None


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


def _read_version_json(version_id: str, directory: Path) -> Optional[dict]:
    """The profile json for an installed version, or None if unreadable."""
    path = Path(directory) / "versions" / version_id / f"{version_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fabric_profiles(minecraft_version: str, directory: Path) -> list[str]:
    """Installed Fabric profiles for a game version, oldest first.

    A profile is recognised by what its json says -- it inherits from the vanilla
    version and boots Fabric's own launcher -- rather than by pattern-matching the
    profile name, which Fabric has changed before. This reads the json only to
    identify a profile; building the actual launch stays with the library.
    """
    try:
        installed = mll.utils.get_installed_versions(str(directory))
    except Exception:
        return []

    found: list[tuple[object, str]] = []
    for entry in installed:
        version_id = entry.get("id", "")
        data = _read_version_json(version_id, directory)
        if not data or data.get("inheritsFrom") != minecraft_version:
            continue
        if "fabric" not in str(data.get("mainClass", "")).lower():
            continue
        found.append((entry.get("releaseTime"), version_id))

    # Newest last. releaseTime is what separates two loader versions of the same
    # profile; string-sorting the ids would put 0.9 above 0.19.
    found.sort(key=lambda pair: (pair[0] is None, pair[0]))
    return [version_id for _, version_id in found]


def install_fabric_loader(
    minecraft_version: str,
    directory: Path | str,
    loader_version: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> str:
    """Install the Fabric loader for a version. Returns the new profile ID to launch.

    The profile ID is discovered by diffing installed versions rather than by
    guessing Fabric's naming scheme, which has changed before.

    Fabric's installer is a Java jar, so this needs a runtime -- see
    :func:`find_java_executable` for where one is looked for. The vanilla version
    must already be installed for Fabric to go on top of it.
    """
    path = _prepare_directory(directory)

    # The runtime downloaded with the game beats anything on PATH -- a machine
    # can easily have the former and not the latter.
    java = find_java_executable(path, minecraft_version)
    if java is None:
        raise InstallError(
            "No Java runtime found. Fabric's installer is a Java jar and needs one. "
            f"Install Minecraft {minecraft_version} first so its bundled runtime is "
            "downloaded, or put a JRE on PATH or in JAVA_HOME."
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
            java=java,
        )
    except mll.exceptions.VersionNotFound as exc:
        raise InstallError(
            f"Minecraft {minecraft_version} must be installed before Fabric can be "
            "added on top of it."
        ) from exc
    except mll.exceptions.UnsupportedVersion as exc:
        raise InstallError(f"Fabric rejected version '{minecraft_version}'.") from exc
    except mll.exceptions.ExternalProgramError as exc:
        raise InstallError(f"The Fabric installer failed: {exc}") from exc
    except OSError as exc:
        raise InstallError(f"Failed writing Fabric files to {path}: {exc}") from exc

    profiles = _fabric_profiles(minecraft_version, path)
    if not profiles:
        raise InstallError("Fabric reported success but created no launch profile.")

    # Prefer the profile this call just created. When Fabric was already
    # installed nothing is new, so fall back to the newest existing one and stay
    # idempotent -- a launcher calls this every time someone presses play.
    created = set(installed_versions(path)) - before
    for candidate in reversed(profiles):
        if candidate in created:
            return candidate
    return profiles[-1]


def install_fabric_with_sodium(
    minecraft_version: str,
    directory: Path | str,
    loader_version: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> str:
    """Produce a ready-to-play Fabric profile with Sodium in place.

    Installs the vanilla version if it is missing, adds the Fabric loader on top,
    then resolves Sodium from Modrinth for this game version and drops the jar
    into ``<directory>/mods/``. Returns the Fabric profile ID to launch.

    If Sodium cannot be fetched the Fabric profile is still installed and usable;
    the raised error says so.
    """
    # core.mods imports Progress from this module, so importing it at module
    # scope would be circular. Deferring it to call time breaks the cycle.
    from core import mods

    path = _prepare_directory(directory)

    if not is_installed(minecraft_version, path):
        install_version(minecraft_version, path, on_progress=on_progress)

    profile_id = install_fabric_loader(
        minecraft_version,
        path,
        loader_version=loader_version,
        on_progress=on_progress,
    )

    try:
        sodium = mods.resolve_version(
            "sodium", minecraft_version, loader="fabric", project_type="mod"
        )
        mods.download_file(sodium, path, on_progress=on_progress)
    except mods.ModError as exc:
        raise InstallError(
            f"The Fabric profile '{profile_id}' is installed, but Sodium could not "
            f"be added: {exc}"
        ) from exc

    return profile_id
