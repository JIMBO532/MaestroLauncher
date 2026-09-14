"""Regression test for the "wouldn't launch until he removed his resource
packs" report: a new user's .minecraft, or a version's instance folder, can
have real content already sitting where link_shared_data() wants to put a
junction. That content must end up migrated or left alone -- never lost,
never the reason a launch fails.

Covers three shapes of pre-existing content:

  1. The instance's own resourcepacks/saves already have real files in them
     before this instance has ever been linked (Minecraft or a person put
     them there directly).
  2. The traditional root-level .minecraft/resourcepacks, .minecraft/saves
     etc. already have real content from playing vanilla -- or any other
     launcher -- against this same directory before MaestroLauncher ever
     touched it.
  3. Both sides already have a same-named world: a real collision, which
     has no lossless automatic answer and must be reported, not silently
     resolved by deleting one copy.

    python scripts/test_link_shared_data_preexisting_content.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import installer  # noqa: E402

TARGET = Path(__file__).resolve().parent.parent / "test_link_preexisting"
PACK_BYTES = b"PK\x03\x04fake resource pack contents for a test, not a real zip"
WORLD_FILES = ("level.dat", "session.lock")


def _make_world(path: Path, marker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in WORLD_FILES:
        (path / name).write_bytes(marker.encode("utf-8"))


def test_instance_already_populated() -> list[str]:
    """resourcepacks/ and saves/ already have real files before this
    instance has ever been linked. Everything must survive, and both
    folders must end up shared."""
    problems = []
    directory = TARGET / "case1"
    instance = installer.instance_directory("26.2", directory)
    (instance / "resourcepacks").mkdir(parents=True)
    (instance / "resourcepacks" / "MyPack.zip").write_bytes(PACK_BYTES)
    _make_world(instance / "saves" / "New World", "instance-world")

    notes = installer.link_shared_data(instance, directory)
    if notes:
        problems.append(f"case1: unexpected notes for a collision-free merge: {notes}")

    shared = installer.shared_data_directory(directory)
    if not (shared / "resourcepacks" / "MyPack.zip").is_file():
        problems.append("case1: MyPack.zip did not end up in the shared folder")
    if (shared / "resourcepacks" / "MyPack.zip").read_bytes() != PACK_BYTES:
        problems.append("case1: MyPack.zip's content changed during the move")
    if not (shared / "saves" / "New World" / "level.dat").is_file():
        problems.append("case1: New World did not end up in the shared folder")
    if not os.path.isjunction(str(instance / "resourcepacks")):
        problems.append("case1: instance resourcepacks is not a junction afterward")
    if not os.path.isjunction(str(instance / "saves")):
        problems.append("case1: instance saves is not a junction afterward")

    return problems


def test_root_already_populated() -> list[str]:
    """The traditional .minecraft/resourcepacks, .minecraft/saves and
    .minecraft/mods already have real content -- someone who played vanilla,
    or used any other launcher, before ever opening MaestroLauncher. A
    brand-new instance must see that content through its junction; mods
    must be left exactly where they are, not merged blind."""
    problems = []
    directory = TARGET / "case2"
    (directory / "resourcepacks").mkdir(parents=True)
    (directory / "resourcepacks" / "OldPack.zip").write_bytes(PACK_BYTES)
    _make_world(directory / "saves" / "Old World", "root-world")
    (directory / "options.txt").write_text("fov:90\n", encoding="utf-8")
    (directory / "mods").mkdir(parents=True)
    (directory / "mods" / "old-mod-for-a-different-version.jar").write_bytes(b"jar")

    instance = installer.instance_directory("26.2", directory)
    notes = installer.link_shared_data(instance, directory)

    shared = installer.shared_data_directory(directory)
    if not (shared / "resourcepacks" / "OldPack.zip").is_file():
        problems.append("case2: root OldPack.zip was not migrated into the shared folder")
    if not (shared / "saves" / "Old World" / "level.dat").is_file():
        problems.append("case2: root Old World was not migrated into the shared folder")
    if not (instance / "resourcepacks" / "OldPack.zip").is_file():
        problems.append("case2: the new instance cannot see the migrated pack through its junction")
    if not (shared / "options.txt").is_file():
        problems.append("case2: root options.txt was not adopted as the shared copy")

    # mods is the one folder that must NOT be touched: mixing an unknown
    # version's jars into a fresh instance is exactly the bug per-instance
    # mods exists to prevent.
    root_mod = directory / "mods" / "old-mod-for-a-different-version.jar"
    if not root_mod.is_file():
        problems.append("case2: root mods jar was moved or deleted -- it must be left alone")
    if (instance / "mods" / "old-mod-for-a-different-version.jar").exists():
        problems.append("case2: root mod leaked into the new instance's mods folder")
    if not any("mods" in note and "left untouched" in note for note in notes):
        problems.append(f"case2: no note about the untouched root mods folder: {notes}")

    return problems


def test_genuine_collision_is_preserved_not_lost() -> list[str]:
    """Root and the instance both already have a world called the same
    thing. There is no automatic way to pick a winner, so both copies must
    survive on disk and the situation must be reported -- not resolved by
    quietly deleting one of them."""
    problems = []
    directory = TARGET / "case3"
    _make_world(directory / "saves" / "New World", "root-version")

    instance = installer.instance_directory("26.2", directory)
    _make_world(instance / "saves" / "New World", "instance-version")

    notes = installer.link_shared_data(instance, directory)

    if not any("New World" in note for note in notes):
        problems.append(f"case3: no note raised about the colliding world: {notes}")

    # Neither copy may vanish: this is the one situation with no lossless
    # automatic answer, so both must still be exactly as they were.
    instance_copy = instance / "saves" / "New World" / "level.dat"
    if not instance_copy.is_file() or instance_copy.read_bytes() != b"instance-version":
        problems.append("case3: the instance's own New World was lost or altered")

    shared = installer.shared_data_directory(directory)
    shared_copy = shared / "saves" / "New World" / "level.dat"
    if not shared_copy.is_file() or shared_copy.read_bytes() != b"root-version":
        problems.append("case3: the root's New World was lost or altered")

    if os.path.isjunction(str(instance / "saves")):
        problems.append("case3: saves became a junction despite the unresolved collision")

    return problems


def main() -> int:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    print("MaestroLauncher link_shared_data() pre-existing-content test\n")

    cases = [
        ("instance already populated", test_instance_already_populated),
        ("root .minecraft already populated", test_root_already_populated),
        ("genuine collision is preserved, not lost", test_genuine_collision_is_preserved_not_lost),
    ]

    problems: list[str] = []
    for name, case in cases:
        case_problems = case()
        status = "ok" if not case_problems else f"{len(case_problems)} problem(s)"
        print(f"  [{status}] {name}")
        problems.extend(case_problems)

    shutil.rmtree(TARGET, ignore_errors=True)

    if problems:
        print(f"\nFAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nAll cases passed -- pre-existing content is migrated or preserved, never lost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
