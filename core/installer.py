"""Game file installation for MaestroLauncher.

Owns everything to do with getting Minecraft onto disk: vanilla versions and the
Fabric loader. Knows nothing about accounts, mods, or the GUI -- keep it that way
so it stays testable without a login.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
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
    """True if this version is really present in this directory.

    Deliberately not ``mll.utils.is_version_valid``, which answers a different
    question: it is True for any version Mojang offers for download, installed
    here or not, so it can never tell you whether a launch would work.
    """
    return version_id in installed_versions(directory)


def installed_versions(directory: Path | str) -> list[str]:
    path = Path(directory).expanduser()
    if not path.exists():
        return []
    return [v["id"] for v in mll.utils.get_installed_versions(str(path))]


def base_game_version(version_id: str, directory: Path | str) -> str:
    """The Minecraft version a profile is built on -- "1.21.1" for a Fabric profile.

    A modded profile is a thin JSON that inherits from a vanilla version, and its
    ID is whatever the loader's installer chose to call it. Modrinth only knows
    the vanilla number, so anything asking Modrinth "which game version is this?"
    has to resolve the profile first.

    The answer is read out of the profile's own ``inheritsFrom`` rather than
    parsed out of its ID, because the ID is the loader's to name and not ours to
    pattern-match. A vanilla version inherits from nothing and is its own answer,
    as is a profile we cannot read.
    """
    path = Path(directory).expanduser() / "versions" / version_id / f"{version_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return version_id

    inherits = payload.get("inheritsFrom") if isinstance(payload, dict) else None
    return str(inherits) if inherits else version_id


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
    """Install the Fabric loader for a version. Returns the profile ID to launch.

    Uses ``mll.mod_loader``, which reports the profile ID itself, so we neither
    guess Fabric's naming scheme nor go looking for it afterwards. Calling this
    for an already-installed profile re-runs the installer and returns the same
    ID, so a launcher can call it on every press of play.

    Fabric's installer is a Java jar, so this needs a runtime -- see
    :func:`find_java_executable`. The vanilla version must already be installed:
    mod_loader's docstring says it will install a missing one, but its code
    raises VersionNotFound before reaching that point. install_fabric_with_sodium
    installs vanilla first for exactly this reason.
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

    try:
        loader = mll.mod_loader.get_mod_loader("fabric")
    except Exception as exc:
        raise InstallError(f"Could not load Fabric support: {exc}") from exc

    try:
        supported = loader.is_minecraft_version_supported(minecraft_version)
    except Exception as exc:
        raise InstallError(
            f"Could not check whether Fabric supports {minecraft_version}: {exc}"
        ) from exc
    if not supported:
        raise InstallError(f"Fabric does not support Minecraft {minecraft_version}.")

    callback = _build_callback(on_progress) if on_progress else None

    try:
        return loader.install(
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
    except subprocess.CalledProcessError as exc:
        # mod_loader runs the installer with check=True, so a non-zero exit
        # arrives as CalledProcessError rather than the old ExternalProgramError.
        # It carries no captured output; the installer writes to our own stderr.
        raise InstallError(
            f"The Fabric installer exited with code {exc.returncode}. Its output is "
            "above."
        ) from exc
    except OSError as exc:
        raise InstallError(f"Failed writing Fabric files to {path}: {exc}") from exc
    except Exception as exc:
        raise InstallError(f"Installing Fabric failed unexpectedly: {exc}") from exc


# What a generated profile is called: "1.21.1-optimized". The suffix is in the
# ID because the ID is what the version list shows, and telling an optimized
# profile apart from plain Fabric at a glance is the whole point of making one.
OPTIMIZED_SUFFIX = "optimized"


# Generated profiles get their own game directory under here, one per profile.
# Prism and MultiMC call these instances; the idea is the same and so is the
# reason for it.
INSTANCES_DIRNAME = "maestro-instances"


def optimized_profile_id(minecraft_version: str) -> str:
    """The profile ID :func:`install_optimized_profile` creates for a version."""
    return f"{minecraft_version}-{OPTIMIZED_SUFFIX}"


def instance_directory(version_id: str, directory: Path | str) -> Path:
    """The private game directory a version runs in.

    Keyed by the *Minecraft* version, not by the profile, so ``26.2``,
    ``fabric-loader-0.19.5-26.2`` and ``26.2-optimized`` all share one folder
    while ``1.21.11`` gets its own. Mods are compatible with a game version
    rather than with a profile, so that is the line worth drawing: a pack
    installed for 26.2 is visible to every 26.2 profile and invisible to
    everything else.

    ``mods/`` is read from the *game* directory, not from the version, so every
    profile sharing one ``.minecraft`` also shares one mods folder. Install for
    two Minecraft versions and both sets of jars sit in it at once; Fabric then
    finds a build for the wrong version and refuses to start the game. Giving
    each profile its own directory is what makes "install optimizations for
    26.2" unable to touch what 1.21.11 is using.

    Versions, libraries and assets stay in the shared directory -- those are
    keyed by version already and are far too big to duplicate per profile.
    """
    base = base_game_version(version_id, directory)
    return Path(directory).expanduser() / INSTANCES_DIRNAME / base


def shared_mods_directory(directory: Path | str) -> Path:
    """The old ``.minecraft/mods`` that every profile used to share."""
    return Path(directory).expanduser() / "mods"


# Everything under an instance that should NOT be per-version. Worlds are the
# reason this exists: a world that vanishes because someone changed version is
# not an acceptable way to lose a build. Settings and packs follow the same
# logic -- nobody expects their keybinds to reset because they launched 1.21.11.
#
# mods/ is deliberately absent and must stay absent. It is the one folder that
# genuinely is per-version, and sharing it is the bug all of this came from.
SHARED_DIRNAME = "maestro-shared"
SHARED_DIRECTORIES = ("saves", "resourcepacks", "shaderpacks", "screenshots")
SHARED_FILES = ("options.txt",)


def shared_data_directory(directory: Path | str) -> Path:
    """Where the data that every version shares actually lives."""
    return Path(directory).expanduser() / SHARED_DIRNAME


def _is_link_to(path: Path, target: Path) -> bool:
    """True when path is a link already pointing at target."""
    if not path.exists() and not path.is_symlink():
        return False
    try:
        return Path(os.path.realpath(path)) == Path(os.path.realpath(target))
    except OSError:
        return False


def _make_directory_link(link: Path, target: Path) -> None:
    """Point link at target, by junction on Windows and symlink elsewhere.

    A junction rather than a symlink on Windows because a symlink needs either
    administrator rights or developer mode, and a junction needs neither. The
    game cannot tell the difference.
    """
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _merge_into(source: Path, target: Path) -> list[str]:
    """Move source's entries into target without overwriting. Returns collisions.

    Used when an instance already has real worlds in it from before sharing.
    Moving them is the whole point -- leaving them behind would strand exactly
    the worlds this change exists to protect -- but a name that already exists in
    the shared folder is never overwritten, because one of the two would be lost
    and no rule here can say which.
    """
    collisions: list[str] = []
    try:
        entries = sorted(source.iterdir())
    except OSError:
        return collisions

    for entry in entries:
        destination = target / entry.name
        if destination.exists():
            collisions.append(entry.name)
            continue
        try:
            shutil.move(str(entry), str(destination))
        except OSError:
            collisions.append(entry.name)
    return collisions


def link_shared_data(instance: Path | str, directory: Path | str) -> list[str]:
    """Point an instance's shared folders at the one copy everyone uses.

    Returns notes worth showing someone -- what was migrated, what could not be.
    An empty list means it did what it was asked and there is nothing to say.

    Safe to call before every launch: an instance already linked is left alone,
    so this is how a newly created instance and a long-standing one end up in the
    same state.
    """
    instance_path = Path(instance).expanduser()
    shared = shared_data_directory(directory)
    notes: list[str] = []

    instance_path.mkdir(parents=True, exist_ok=True)
    shared.mkdir(parents=True, exist_ok=True)

    for name in SHARED_DIRECTORIES:
        target = shared / name
        target.mkdir(parents=True, exist_ok=True)
        link = instance_path / name

        if _is_link_to(link, target):
            continue

        if link.is_dir() and not os.path.isjunction(str(link)) and not link.is_symlink():
            # A real folder already here, possibly with worlds in it.
            collisions = _merge_into(link, target)
            moved = not collisions
            try:
                link.rmdir()
            except OSError:
                # Not empty, so something stayed behind. Leave it exactly as it
                # is rather than deleting anything, and say so.
                notes.append(
                    f"{link} still holds {', '.join(collisions) or 'files'} that "
                    f"could not be merged into {target} (same name already there); "
                    "it is not shared until you move them yourself"
                )
                continue
            if moved and collisions == []:
                pass
        elif link.exists() or link.is_symlink():
            # A stale link somewhere else, or a file where a folder should be.
            try:
                if os.path.isjunction(str(link)) or link.is_symlink():
                    link.unlink()
                else:
                    notes.append(f"{link} is a file, so {name} could not be shared")
                    continue
            except OSError as exc:
                notes.append(f"Could not replace {link}: {exc}")
                continue

        try:
            _make_directory_link(link, target)
        except OSError as exc:
            notes.append(f"Could not share {name}: {exc}")

    for name in SHARED_FILES:
        target = shared / name
        link = instance_path / name

        try:
            if link.exists() and target.exists() and link.samefile(target):
                continue
        except OSError:
            pass

        try:
            if link.is_file() and not target.exists():
                # First instance to be linked donates its settings to everyone.
                shutil.move(str(link), str(target))
            elif link.exists():
                link.unlink()

            if not target.exists():
                # The game writes this on first run; the link has to exist before
                # then or the game simply makes its own and shares nothing.
                target.touch()

            os.link(target, link)
        except OSError as exc:
            notes.append(f"Could not share {name}: {exc}")

    return notes


def _declared_release(constraint: str) -> str:
    """The Minecraft release a dependency string is about, e.g. "26.2".

    Fabric constraints come in many shapes -- ``"1.21.11"``, ``">=1.21.11-
    <1.21.12-"``, ``"~26.2"``, a list of several -- and grouping on the raw text
    would file ``~26.2`` and ``~26.2-`` as two different versions when they are
    plainly one. Every version-looking number is reduced to its major.minor and
    the lowest is taken, which is the release the jar was built against.

    Returns "" when nothing version-shaped is in there, which is a jar that
    declares no game version and so cannot be the one causing a mismatch.
    """
    numbers = re.findall(r"\d+\.\d+(?:\.\d+)?", constraint or "")
    releases = {".".join(number.split(".")[:2]) for number in numbers}
    if not releases:
        return ""
    return sorted(releases, key=lambda v: [int(part) for part in v.split(".")])[0]


def mixed_version_mods(directory: Path | str) -> dict[str, list[str]]:
    """Group a shared mods folder's jars by the Minecraft release they declare.

    Only interesting when it finds more than one group: that is the folder that
    stops Fabric from starting, because a build for the wrong version is an error
    and not something it skips over. Reported rather than touched -- what to
    delete out of a folder someone filled by hand is their call.

    Jars declaring no game version at all are left out entirely rather than
    lumped together, since they are compatible with whatever is running and can
    never be the cause of a mismatch.
    """
    # core.mods imports from this module, so this import is deferred to call
    # time for the same reason install_fabric_with_sodium's is.
    from core.mods import read_fabric_metadata

    folder = shared_mods_directory(directory)
    try:
        jars = sorted(folder.glob("*.jar"))
    except OSError:
        return {}

    groups: dict[str, list[str]] = {}
    for jar in jars:
        meta = read_fabric_metadata(jar)
        release = _declared_release(meta.minecraft if meta else "")
        if release:
            groups.setdefault(release, []).append(jar.name)
    return groups


def is_optimized_profile(version_id: str) -> bool:
    """True for a profile this launcher generated."""
    return version_id.endswith(f"-{OPTIMIZED_SUFFIX}")


def install_optimized_profile(
    minecraft_version: str,
    directory: Path | str,
    loader_version: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> str:
    """Install vanilla and Fabric, then add a clearly named profile beside them.

    Returns the new profile's ID, e.g. ``1.21.1-optimized``.

    Fabric's installer names its profile ``fabric-loader-<loader>-<version>``
    and offers no way to call it anything else, so a launcher that wants a
    recognisable entry in the version list has to add one. This writes a version
    JSON, which is as close to the launch protocol as this module gets, so it
    does the least it possibly can: it copies the profile Fabric just generated
    and changes exactly two keys.

    * ``id`` becomes the new name, because that is what the version list shows.
    * ``jar`` is pointed at Fabric's profile, because the classpath takes the
      client jar from ``versions/<jar or id>/<...>.jar`` and the new profile has
      no jar of its own. Setting it avoids copying Fabric's 26 MB jar per
      profile.

    Everything else -- libraries, main class, arguments, ``inheritsFrom`` -- is
    Fabric's, untouched. No manifest is parsed, no assets are fetched, no JVM
    arguments are built; ``minecraft_launcher_lib`` still resolves and launches
    the result exactly as it does the profile it was copied from. Inheritance is
    deliberately kept one level deep, pointing at the vanilla version, because
    the library resolves ``inheritsFrom`` once rather than recursively -- a
    profile inheriting from Fabric's would silently lose vanilla's libraries.

    Re-running replaces the profile, so this is safe to call repeatedly.
    """
    path = _prepare_directory(directory)

    if not is_installed(minecraft_version, path):
        install_version(minecraft_version, path, on_progress=on_progress)

    fabric_id = install_fabric_loader(
        minecraft_version, path, loader_version=loader_version, on_progress=on_progress
    )

    source = path / "versions" / fabric_id / f"{fabric_id}.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(
            f"Could not read the Fabric profile at {source}: {exc}"
        ) from exc

    profile_id = optimized_profile_id(minecraft_version)
    data["id"] = profile_id
    data["jar"] = fabric_id

    target = path / "versions" / profile_id
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{profile_id}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise InstallError(f"Could not write the profile {profile_id}: {exc}") from exc

    return profile_id


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
