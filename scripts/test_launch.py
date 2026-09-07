"""Milestone 3 acceptance test.

Builds a full launch command for an installed version using dummy credentials,
prints it, and checks it has the pieces a real launch needs: JVM arguments, the
classpath, and the version's declared main class.

The game is never started -- there is no login yet, so it could not get past the
authentication step. The spawn-and-log half of core/launch.py is exercised with a
harmless command instead, which is what actually proves the log capture works.

    python scripts/test_launch.py
    python scripts/test_launch.py 1.21.1

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.launch import (  # noqa: E402
    DEFAULT_MEMORY_MB,
    REDACTED,
    LaunchError,
    build_command,
    default_log_path,
    redact,
    resolve_java_executable,
)
from core.launch import _spawn  # noqa: E402 -- the spawn/log seam under test

TARGET = Path(__file__).resolve().parent.parent / "test_mc"

# Obviously fake, and non-empty so they build a complete command.
DUMMY_USERNAME = "MaestroTester"
DUMMY_UUID = "00000000-0000-0000-0000-000000000000"
DUMMY_TOKEN = "dummy-access-token-not-a-real-credential"

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}{'  -- ' + detail if detail else ''}")


def declared_main_class(version: str) -> str:
    """The mainClass the version's own json asks for."""
    client_json = TARGET / "versions" / version / f"{version}.json"
    return str(json.loads(client_json.read_text(encoding="utf-8"))["mainClass"])


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.21.1"

    print("MaestroLauncher launch test")
    print(f"  version:   {version}")
    print(f"  directory: {TARGET}")
    print("  the game is NOT started; this builds and inspects the command only\n")

    try:
        java = resolve_java_executable(version, TARGET)
    except LaunchError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"  java: {java}\n")

    # Build the command with dummy credentials.
    try:
        command = build_command(
            version, TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN
        )
    except LaunchError as exc:
        print(f"FAILED: could not build the command: {exc}")
        return 1

    print("Full command (dummy credentials):\n")
    print("  " + command[0])
    for argument in command[1:]:
        shown = argument if len(argument) <= 100 else argument[:97] + "..."
        print(f"    {shown}")
    print(f"\n  {len(command)} arguments in total\n")

    print("Checks\n")

    # The java binary.
    check("the command starts with a real java executable", Path(command[0]).is_file(), command[0])

    # JVM arguments: heap size, and the natives path the library assembles.
    check(
        f"default heap size is -Xmx{DEFAULT_MEMORY_MB}M",
        f"-Xmx{DEFAULT_MEMORY_MB}M" in command,
    )
    check(
        "the natives library path is set",
        any(a.startswith("-Djava.library.path=") for a in command),
    )

    # Classpath.
    check("a -cp argument is present", "-cp" in command)
    if "-cp" in command:
        classpath = command[command.index("-cp") + 1]
        entries = classpath.split(os.pathsep)
        check("the classpath has many entries", len(entries) > 10, f"{len(entries)} entries")
        check(
            "the classpath includes the version jar",
            any(entry.endswith(f"{version}.jar") for entry in entries),
        )
        check("every classpath entry is a jar", all(e.endswith(".jar") for e in entries))

    # Main class, taken from the version's own json rather than hardcoded.
    expected_main = declared_main_class(version)
    check(
        f"the declared main class is present ({expected_main})",
        expected_main in command,
    )
    if "-cp" in command and expected_main in command:
        check(
            "the main class comes after the classpath",
            command.index(expected_main) > command.index("-cp"),
        )

    # Game arguments carry the account details we passed in.
    for flag, value in (
        ("--username", DUMMY_USERNAME),
        ("--uuid", DUMMY_UUID),
        ("--accessToken", DUMMY_TOKEN),
    ):
        check(
            f"{flag} carries the value we passed",
            flag in command and command[command.index(flag) + 1] == value,
        )
    check("the version is named in the command", version in command)

    # RAM is configurable.
    custom = build_command(
        version, TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN, memory_mb=4096
    )
    check("memory_mb changes the heap size", "-Xmx4096M" in custom and "-Xmx2048M" not in custom)

    explicit = build_command(
        version, TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN,
        memory_mb=4096, jvm_arguments=["-Xmx1234M"],
    )
    check(
        "an explicit -Xmx wins and is not duplicated",
        explicit.count("-Xmx1234M") == 1 and "-Xmx4096M" not in explicit,
    )

    # The token must not leak into anything printable.
    redacted = redact(command, DUMMY_TOKEN)
    check("redact() removes the token", DUMMY_TOKEN not in redacted and REDACTED in redacted)
    check("redact() leaves the rest alone", len(redacted) == len(command))

    # Bad input is our error type.
    for label, call in (
        ("a nonexistent version", lambda: build_command("0.0.1-nope", TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN)),
        # A real version that simply is not installed here. This one used to slip
        # through: the guard called mll.utils.is_version_valid, which is True for
        # anything Mojang offers, installed or not.
        ("a real but uninstalled version", lambda: build_command("1.20.4", TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN)),
        ("an empty token", lambda: build_command(version, TARGET, DUMMY_USERNAME, DUMMY_UUID, "")),
        ("too little memory", lambda: build_command(version, TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN, memory_mb=64)),
    ):
        try:
            call()
            check(f"{label} raises LaunchError", False, "nothing raised")
        except LaunchError:
            check(f"{label} raises LaunchError", True)
        except Exception as exc:  # noqa: BLE001
            check(f"{label} raises LaunchError", False, f"leaked {type(exc).__name__}: {exc}")

    # Spawning and log capture, proven with a harmless process.
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "run.log"
        program = (
            "import sys; print('hello from stdout'); "
            "print('hello from stderr', file=sys.stderr); sys.exit(3)"
        )
        # The token is passed as an argument so it genuinely appears in the
        # command line, which is what the header has to redact. The child never
        # prints its argv, so it cannot reach the log by any other route.
        game = _spawn(
            [sys.executable, "-c", program, DUMMY_TOKEN], Path(tmp), log, token=DUMMY_TOKEN
        )
        code = game.wait(timeout=30)

        check("the spawned process runs and its exit code comes back", code == 3, f"got {code}")
        check("the log file exists", log.exists())

        text = log.read_text(encoding="utf-8", errors="replace")
        check("stdout is captured", "hello from stdout" in text)
        check("stderr is captured into the same log", "hello from stderr" in text)
        check("the log header records the command", "MaestroLauncher" in text)
        check("the log header hides the token", DUMMY_TOKEN not in text and REDACTED in text)
        check("the token stays out of the repr", DUMMY_TOKEN not in repr(game))
        check("the process is no longer running", not game.is_running())
        game.terminate()  # must be safe after exit
        check("terminate() is safe after exit", True)

    # A default log path lands inside the game directory.
    path = default_log_path(version, TARGET)
    check("the default log path is under the game directory", TARGET.resolve() in path.parents)
    check("the default log path is not the game's own logs/", path.parent.name != "logs")

    # core.launch must not drag in auth.
    check("core.launch does not import core.auth", "core.auth" not in sys.modules)

    print(f"\n  {_passed} passed, {_failed} failed")

    if _failed:
        print("\nFAILED")
        return 1

    print("\nMilestone 3 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
