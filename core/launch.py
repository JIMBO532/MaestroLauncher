"""Launching the game for MaestroLauncher.

Builds the launch command with ``minecraft_launcher_lib.command`` and spawns it,
with the game's stdout and stderr going to a log file so a crash leaves evidence.

Account details arrive as plain strings. This module does not import ``core.auth``
and does not know how a token was obtained, which keeps it testable with dummy
credentials today and lets real login plug in unchanged later.

The access token appears inside the command line. Never print or log a command
without running it through :func:`redact` first.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Optional, Sequence

import minecraft_launcher_lib as mll

from core.installer import find_java_executable

DEFAULT_MEMORY_MB = 2048

# Below this the game will not get past the loading screen.
MINIMUM_MEMORY_MB = 512

# Our own logs, kept away from <dir>/logs/ where the game writes its own.
LOG_DIRNAME = "launcher_logs"

REDACTED = "<redacted>"


class LaunchError(RuntimeError):
    """Anything that stopped the game from being built or started."""


@dataclass
class RunningGame:
    """A spawned game process and the log it is writing to.

    ``command`` is kept out of the repr because it contains the access token.
    """

    process: subprocess.Popen
    log_path: Path
    command: list[str] = field(repr=False)
    _log_handle: Optional[IO[bytes]] = field(default=None, repr=False)

    @property
    def pid(self) -> int:
        return self.process.pid

    def is_running(self) -> bool:
        return self.process.poll() is None

    def wait(self, timeout: Optional[float] = None) -> int:
        """Block until the game exits and return its exit code."""
        try:
            code = self.process.wait(timeout=timeout)
        finally:
            self._close_log()
        return code

    def terminate(self) -> None:
        """Ask the game to close. Safe to call after it has already exited."""
        if self.is_running():
            self.process.terminate()
        self._close_log()

    def _close_log(self) -> None:
        if self._log_handle is not None and not self._log_handle.closed:
            self._log_handle.close()


def redact(command: Sequence[str], token: str) -> list[str]:
    """Copy a command with the access token replaced, safe to print or log."""
    if not token:
        return list(command)
    return [REDACTED if part == token else part for part in command]


def resolve_java_executable(version_id: str, directory: Path | str) -> str:
    """Find a Java runtime for this version, or raise ``LaunchError``.

    The search itself lives in ``installer.find_java_executable`` because the
    Fabric installer needs exactly the same lookup; this only turns "nothing
    found" into the error type launching callers expect.
    """
    executable = find_java_executable(directory, version_id)
    if executable is None:
        raise LaunchError(
            f"No Java runtime found for {version_id}. Reinstall the version so its "
            "bundled runtime is downloaded, or put a JRE on PATH or in JAVA_HOME."
        )
    return executable


def _memory_arguments(memory_mb: int, jvm_arguments: Sequence[str]) -> list[str]:
    """The -Xmx flag, unless the caller already set their own heap size."""
    if any(argument.startswith("-Xmx") for argument in jvm_arguments):
        return []
    return [f"-Xmx{memory_mb}M"]


def build_command(
    version_id: str,
    directory: Path | str,
    username: str,
    uuid: str,
    token: str,
    memory_mb: int = DEFAULT_MEMORY_MB,
    java_executable: Optional[str] = None,
    jvm_arguments: Optional[Sequence[str]] = None,
    game_directory: Path | str | None = None,
    resolution: Optional[tuple[int, int]] = None,
    demo: bool = False,
    launcher_name: str = "MaestroLauncher",
    launcher_version: str = "0.1.0",
) -> list[str]:
    """Build the full command line that starts the game.

    ``username``, ``uuid`` and ``token`` are passed through as given -- this
    module does not validate them against Mojang, so dummy values build a
    complete command for testing without a login.

    The returned list contains the access token; see :func:`redact`.
    """
    path = Path(directory).expanduser().resolve()

    if not username or not uuid or not token:
        raise LaunchError("username, uuid and token are all required to launch.")
    if memory_mb < MINIMUM_MEMORY_MB:
        raise LaunchError(f"memory_mb must be at least {MINIMUM_MEMORY_MB}.")
    if not mll.utils.is_version_valid(version_id, str(path)):
        raise LaunchError(
            f"Minecraft {version_id} is not installed in {path}. Install it first."
        )

    extra_jvm = list(jvm_arguments or [])
    options: dict = {
        "username": username,
        "uuid": uuid,
        "token": token,
        "executablePath": java_executable or resolve_java_executable(version_id, path),
        "jvmArguments": _memory_arguments(memory_mb, extra_jvm) + extra_jvm,
        "launcherName": launcher_name,
        "launcherVersion": launcher_version,
        "demo": demo,
    }

    if game_directory is not None:
        options["gameDirectory"] = str(Path(game_directory).expanduser().resolve())
    if resolution is not None:
        width, height = resolution
        options["customResolution"] = True
        options["resolutionWidth"] = str(width)
        options["resolutionHeight"] = str(height)

    try:
        return mll.command.get_minecraft_command(version_id, str(path), options)
    except mll.exceptions.VersionNotFound as exc:
        raise LaunchError(f"Minecraft version '{version_id}' was not found.") from exc
    except OSError as exc:
        raise LaunchError(f"Could not read the game files in {path}: {exc}") from exc
    except Exception as exc:
        raise LaunchError(f"Could not build the launch command: {exc}") from exc


def default_log_path(version_id: str, directory: Path | str) -> Path:
    """A timestamped log file for this launch, inside the game directory."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_version = version_id.replace(os.sep, "_").replace("/", "_")
    return Path(directory).expanduser().resolve() / LOG_DIRNAME / f"{safe_version}-{stamp}.log"


def _spawn(
    command: Sequence[str],
    working_directory: Path,
    log_path: Path,
    token: str = "",
) -> RunningGame:
    """Start a command with its output going to ``log_path``.

    Kept separate from :func:`launch` so the spawn-and-capture behaviour can be
    tested with a harmless command instead of the game.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("wb")
    except OSError as exc:
        raise LaunchError(f"Could not open the log file {log_path}: {exc}") from exc

    header = (
        f"MaestroLauncher {datetime.now().isoformat(timespec='seconds')}\n"
        f"{' '.join(redact(command, token))}\n\n"
    )
    try:
        handle.write(header.encode("utf-8"))
        handle.flush()
    except OSError:
        # A log we cannot write a header to is still worth trying to use.
        pass

    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(working_directory),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        handle.close()
        raise LaunchError(f"Could not start {command[0]}: {exc}") from exc

    return RunningGame(
        process=process,
        log_path=log_path,
        command=list(command),
        _log_handle=handle,
    )


def launch(
    version_id: str,
    directory: Path | str,
    username: str,
    uuid: str,
    token: str,
    memory_mb: int = DEFAULT_MEMORY_MB,
    java_executable: Optional[str] = None,
    jvm_arguments: Optional[Sequence[str]] = None,
    game_directory: Path | str | None = None,
    resolution: Optional[tuple[int, int]] = None,
    demo: bool = False,
    log_path: Path | str | None = None,
) -> RunningGame:
    """Build the command and start the game, logging its output to a file.

    Returns as soon as the process is running; call ``wait()`` on the result to
    block until the game exits.
    """
    path = Path(directory).expanduser().resolve()
    command = build_command(
        version_id,
        path,
        username,
        uuid,
        token,
        memory_mb=memory_mb,
        java_executable=java_executable,
        jvm_arguments=jvm_arguments,
        game_directory=game_directory,
        resolution=resolution,
        demo=demo,
    )

    destination = (
        Path(log_path).expanduser().resolve()
        if log_path is not None
        else default_log_path(version_id, path)
    )
    working_directory = Path(game_directory).expanduser().resolve() if game_directory else path

    return _spawn(command, working_directory, destination, token=token)
