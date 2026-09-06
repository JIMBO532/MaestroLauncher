"""Milestone 4 acceptance test.

Builds a ready-to-play Fabric profile for 1.21.1 in ./test_mc/ -- loader plus
Sodium -- then checks the profile is really in versions/, Sodium's jar is really
in mods/, and core/launch.py can build a valid command for the new profile.

Also checks the thing that made this milestone necessary: that Java resolution
finds the runtime bundled inside the game directory, since this machine has no
java on PATH.

The game is not started; there is still no login.

    python scripts/test_fabric.py
    python scripts/test_fabric.py 1.21.1

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.installer import (  # noqa: E402
    InstallError,
    Progress,
    find_java_executable,
    install_fabric_with_sodium,
    installed_versions,
    is_installed,
)
from core.launch import LaunchError, build_command, resolve_java_executable  # noqa: E402

TARGET = Path(__file__).resolve().parent.parent / "test_mc"
BAR_WIDTH = 30

DUMMY_USERNAME = "MaestroTester"
DUMMY_UUID = "00000000-0000-0000-0000-000000000000"
DUMMY_TOKEN = "dummy-access-token-not-a-real-credential"

_passed = 0
_failed = 0
_last_draw = 0.0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}{'  -- ' + detail if detail else ''}")


def render(progress: Progress) -> None:
    global _last_draw
    now = time.monotonic()
    if now - _last_draw < 0.05 and progress.percent < 100:
        return
    _last_draw = now
    filled = int(BAR_WIDTH * progress.fraction)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    print(f"\r[{bar}] {progress.percent:3d}%  {progress.status[:42].ljust(42)}", end="", flush=True)


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.21.1"

    print("MaestroLauncher Fabric + Sodium test")
    print(f"  version:   {version}")
    print(f"  directory: {TARGET}\n")

    # The bug this milestone fixes: no java on PATH, but one inside the game dir.
    on_path = shutil.which("java") or shutil.which("javaw")
    print(f"  java on PATH:      {on_path or 'none'}")
    print(f"  JAVA_HOME:         {os.environ.get('JAVA_HOME') or 'unset'}")

    bundled = find_java_executable(TARGET, version)
    print(f"  resolved java:     {bundled}\n")

    check("a java runtime is found at all", bundled is not None)
    if bundled is None:
        print("\nFAILED: cannot continue without Java.")
        return 1

    runtime_dir = (TARGET / "runtime").resolve()
    used_bundled = runtime_dir in Path(bundled).resolve().parents
    if on_path is None:
        check("the bundled runtime is used when PATH has no java", used_bundled, bundled)
    else:
        check("the bundled runtime is preferred over the one on PATH", used_bundled, bundled)
    check("the resolved java really exists", Path(bundled).is_file())

    # Build the profile.
    print("\nInstalling Fabric + Sodium\n")
    before = set(installed_versions(TARGET))
    try:
        profile_id = install_fabric_with_sodium(version, TARGET, on_progress=render)
    except InstallError as exc:
        print(f"\n\nFAILED: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        return 1

    print(f"\n\n  profile id: {profile_id}\n")
    print("Checks\n")

    # The Fabric profile is on disk and registered.
    profile_dir = TARGET / "versions" / profile_id
    check("the profile directory exists", profile_dir.is_dir(), str(profile_dir))
    check("the profile json exists", (profile_dir / f"{profile_id}.json").is_file())
    check("the profile is a listed installed version", profile_id in installed_versions(TARGET))
    check("the profile is new or already present, not vanilla", profile_id != version)
    check("fabric is named in the profile id", "fabric" in profile_id.lower(), profile_id)
    check("the vanilla version is still installed", is_installed(version, TARGET))
    if before:
        print(f"    (versions before: {sorted(before)})")

    # Calling it again must return the same profile rather than failing. A
    # launcher runs this every time someone presses play.
    try:
        again = install_fabric_with_sodium(version, TARGET)
        check("a second call is idempotent", again == profile_id, f"{again!r} != {profile_id!r}")
    except InstallError as exc:
        check("a second call is idempotent", False, str(exc))

    # Sodium landed in mods/, not anywhere else.
    mods_dir = TARGET / "mods"
    jars = sorted(mods_dir.glob("*.jar")) if mods_dir.is_dir() else []
    sodium = [j for j in jars if "sodium" in j.name.lower()]
    check("mods/ exists", mods_dir.is_dir(), str(mods_dir))
    check("a sodium jar is in mods/", bool(sodium), f"{len(jars)} jars: {[j.name for j in jars]}")
    if sodium:
        size = sodium[0].stat().st_size
        check("the sodium jar is non-empty", size > 0, f"{size} bytes")
        check("the jar is matched to this game version", version in sodium[0].name, sodium[0].name)
        print(f"    {sodium[0].name}  ({size:,} bytes)")
    check(
        "sodium did not land in resourcepacks/",
        not list((TARGET / "resourcepacks").glob("*sodium*")),
    )

    # launch.py can build a command for the Fabric profile.
    try:
        java_for_profile = resolve_java_executable(profile_id, TARGET)
        check("java resolves for the fabric profile too", Path(java_for_profile).is_file())
        check(
            "the fabric profile also uses the bundled runtime",
            runtime_dir in Path(java_for_profile).resolve().parents,
            java_for_profile,
        )
    except LaunchError as exc:
        check("java resolves for the fabric profile too", False, str(exc))

    try:
        command = build_command(
            profile_id, TARGET, DUMMY_USERNAME, DUMMY_UUID, DUMMY_TOKEN
        )
    except LaunchError as exc:
        check("a launch command builds for the fabric profile", False, str(exc))
        print(f"\n  {_passed} passed, {_failed} failed\n\nFAILED")
        return 1

    check("a launch command builds for the fabric profile", bool(command))
    check("the command starts with the bundled java", runtime_dir in Path(command[0]).resolve().parents)
    check("the heap size is set", any(a.startswith("-Xmx") for a in command))
    check("a classpath is present", "-cp" in command)

    if "-cp" in command:
        entries = command[command.index("-cp") + 1].split(os.pathsep)
        check("the classpath includes the fabric loader", any("fabric" in e.lower() for e in entries))
        check("the classpath includes intermediary mappings", any("intermediary" in e.lower() for e in entries))
        check("every classpath entry is a jar", all(e.endswith(".jar") for e in entries))
        print(f"    classpath: {len(entries)} jars")

    check(
        "the fabric main class is used, not vanilla's",
        any("knot" in a.lower() for a in command),
        next((a for a in command if "main" in a.lower() or "knot" in a.lower()), "none found"),
    )
    check("the profile id is named in the command", profile_id in command)

    print(f"\n  {_passed} passed, {_failed} failed")

    if _failed:
        print("\nFAILED")
        return 1

    print("\nMilestone 4 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
