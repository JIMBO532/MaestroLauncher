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
    argv = [a for a in sys.argv[1:] if a != "--real"]
    version = argv[0] if argv else "1.21.1"

    if "--real" in sys.argv:
        return real_launch(version, memory_mb=DEFAULT_MEMORY_MB, timeout=240.0)

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

    # -- how the game is spawned ---------------------------------------------
    #
    # Two bugs lived here. A console window opened beside the game, and closing
    # that console killed the game, because a child sharing its parent's console
    # is sent CTRL_CLOSE_EVENT when the console goes away. Both are creation
    # flags, and the flags are easy to lose in a refactor without anything
    # failing until someone launches and watches a console appear.
    import subprocess as _subprocess

    from core.launch import _popen_detached

    captured: dict = {}
    real_popen = _subprocess.Popen

    class RecordingPopen(real_popen):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    _subprocess.Popen = RecordingPopen
    captured_output = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "spawn.log"
            with log.open("wb") as handle:
                probe = _popen_detached(
                    [sys.executable, "-c", "print('spawned')"], Path(tmp), handle
                )
                probe.wait(timeout=30)
            # Read it before the temp directory goes away.
            captured_output = log.read_text(encoding="utf-8", errors="replace")
    finally:
        _subprocess.Popen = real_popen

    if os.name == "nt":
        flags = captured.get("creationflags", 0)
        check(
            "the game is spawned with no console window",
            bool(flags & _subprocess.CREATE_NO_WINDOW),
            hex(flags),
        )
        check(
            "it gets its own process group, so Ctrl+C does not reach it",
            bool(flags & _subprocess.CREATE_NEW_PROCESS_GROUP),
            hex(flags),
        )
        check(
            "DETACHED_PROCESS is not combined with CREATE_NO_WINDOW",
            not (flags & 0x00000008),
            hex(flags),
        )
    else:
        check(
            "the game is spawned in its own session",
            captured.get("start_new_session") is True,
            repr(captured.get("start_new_session")),
        )

    # Detaching is only half of it: the log has to survive the change, because
    # the exit code is not a usable success signal -- the game exits 0 even when
    # it fails to get a renderer -- so the log is the only evidence there is.
    check(
        "stdout is still redirected to the log handle",
        captured.get("stdout") is not None
        and captured.get("stderr") == _subprocess.STDOUT,
        repr(captured.get("stderr")),
    )
    check(
        "the detached spawn still captures output",
        captured_output.strip().endswith("spawned"),
        repr(captured_output[:60]),
    )

    # core.launch must not drag in auth.
    check("core.launch does not import core.auth", "core.auth" not in sys.modules)

    print(f"\n  {_passed} passed, {_failed} failed")

    if _failed:
        print("\nFAILED")
        return 1

    print("\nMilestone 3 PASSED")
    return 0


# --- The real thing -------------------------------------------------------
#
# Everything above builds a command with dummy credentials and never starts the
# game, which was all that was possible before M2 landed. With a real login there
# is no longer an excuse for that: the milestone says "launches to the main
# menu", so --real signs in, starts the game, and watches its log until the menu
# is actually up.

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# The game prints this once it has accepted the account.
LOGIN_MARKER = "Setting user:"

# Any one of these means rendering got as far as the main menu. The sound engine
# and the GUI texture atlas are both built while the menu is constructed, so they
# arrive together and either is enough on its own.
MENU_MARKERS = ("Sound engine started", "OpenAL initialized", "textures/atlas")


def _log_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def real_launch(version: str, memory_mb: int, timeout: float) -> int:
    """Sign in for real, start the game, and wait for the main menu."""
    from core.auth import AuthError, load_client_id, login_or_refresh
    from core.launch import launch

    print("Real launch")
    print()

    client_id = load_client_id(ENV_FILE)
    if not client_id:
        print(f"BLOCKED: no Azure client ID in {ENV_FILE}. See PLAN.md M0.")
        return 1

    try:
        account = login_or_refresh(
            client_id, TARGET, on_status=lambda text: print(f"  ... {text}")
        )
    except AuthError as exc:
        print(f"FAILED: could not sign in: {exc}")
        return 1

    print(f"  signed in as {account.username} ({account.uuid})")

    try:
        game = launch(
            version,
            TARGET,
            account.username,
            account.uuid,
            account.access_token,
            memory_mb=memory_mb,
        )
    except LaunchError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"  pid {game.pid}, logging to {game.log_path}")
    print(f"  waiting up to {timeout:.0f}s for the main menu")
    print()

    deadline = time.monotonic() + timeout
    seen_login = False
    reached_menu = False

    while time.monotonic() < deadline:
        text = _log_text(game.log_path)

        if not seen_login and LOGIN_MARKER in text:
            seen_login = True
            print("  ... the game accepted the account")

        if any(marker in text for marker in MENU_MARKERS):
            reached_menu = True
            break

        if not game.is_running():
            break

        time.sleep(1.0)

    text = _log_text(game.log_path)
    running = game.is_running()
    exit_code = None if running else game.process.poll()

    check("the game process started", game.pid > 0)
    check("the game accepted the account", seen_login or LOGIN_MARKER in text)
    check(
        "the game reached the main menu",
        reached_menu,
        f"still running={running}, exit code={exit_code}",
    )
    check("the game did not exit on its own", running, f"exit code={exit_code}")
    check(
        "the access token is not in the log",
        account.access_token not in text,
        "the log leaked the token",
    )

    if reached_menu and running:
        print()
        print("  main menu reached; closing the game")
        game.terminate()
        try:
            game.wait(timeout=30)
        except Exception:  # noqa: BLE001 -- best effort shutdown
            pass
    else:
        game.terminate()

        # Which renderer the game got is the first thing worth knowing, and it is
        # easy to miss in the tail. Modern versions try OpenGL, fall back to
        # Vulkan and carry on; versions that predate that fallback just die. So a
        # launch that works and one that does not can differ only in the game
        # version, with the launcher behaving identically in both.
        backend = [
            line for line in text.splitlines()
            if "graphics backend" in line
            or "Failed to create backend" in line
            or "BackendCreationException" in line
            or "GLFW error" in line
            or "Backend library" in line
        ]
        if backend:
            print()
            print("  renderer:")
            for line in backend:
                print(f"    {line.strip()}")

        print()
        print("  last 25 log lines:")
        print()
        for line in text.splitlines()[-25:]:
            print(f"    {line}")

    print()
    print(f"  {_passed} passed, {_failed} failed")
    if _failed:
        print()
        print("FAILED")
        return 1
    print()
    print(f"Real launch of {version} PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
