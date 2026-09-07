"""M6 slice 5 acceptance test.

Builds real files in a temporary folder -- a mod jar, a resource pack zip, a
shader pack zip, an unrecognised zip and a corrupt zip -- then imports them into
a throwaway game directory and checks each lands where it should, or is refused
with a reason.

    python scripts/test_imports.py

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.imports import (  # noqa: E402
    FileKind,
    ImportFileError,
    ImportResult,
    describe,
    identify,
    import_file,
    import_files,
)

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


def make_jar(path: Path) -> Path:
    """A jar is a zip; a mod one carries fabric.mod.json."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", '{"id": "testmod", "version": "1.0.0"}')
        archive.writestr("testmod/Main.class", b"\xca\xfe\xba\xbe not really bytecode")
    return path


def make_resource_pack(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pack.mcmeta", '{"pack": {"pack_format": 34, "description": "test"}}')
        archive.writestr("assets/minecraft/textures/block/stone.png", b"\x89PNG not really")
    return path


def make_shader_pack(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("shaders/gbuffers_basic.vsh", "void main() {}")
        archive.writestr("shaders/shaders.properties", "profile.DEFAULT=")
    return path


def make_unrecognised_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("holiday.txt", "just some notes")
        archive.writestr("photos/beach.jpg", b"not a jpeg either")
    return path


def make_corrupt_zip(path: Path) -> Path:
    """A real zip, then truncated so its data is unreadable."""
    make_resource_pack(path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "downloads"
        game_dir = Path(tmp) / "game"
        source_dir.mkdir()
        game_dir.mkdir()

        print("MaestroLauncher file import test")
        print(f"  sources: {source_dir}")
        print(f"  game:    {game_dir}\n")

        jar = make_jar(source_dir / "testmod-1.0.0.jar")
        pack = make_resource_pack(source_dir / "PrettyPack.zip")
        shader = make_shader_pack(source_dir / "ShinyShaders.zip")
        junk = make_unrecognised_zip(source_dir / "holiday-photos.zip")
        broken = make_corrupt_zip(source_dir / "TruncatedPack.zip")
        text = source_dir / "readme.txt"
        text.write_text("not a mod", encoding="utf-8")

        print("Identification\n")
        check("a mod jar is a mod", identify(jar) is FileKind.MOD)
        check("pack.mcmeta means a resource pack", identify(pack) is FileKind.RESOURCE_PACK)
        check("a shaders/ folder means a shader pack", identify(shader) is FileKind.SHADER_PACK)
        check("an unrecognised zip is UNKNOWN, not a guess", identify(junk) is FileKind.UNKNOWN)
        check("a non-archive is UNKNOWN", identify(text) is FileKind.UNKNOWN)

        try:
            identify(broken)
            check("a corrupt zip raises", False, "nothing raised")
        except ImportFileError as exc:
            check("a corrupt zip raises ImportFileError", True)
            check(
                "its message says why",
                "truncated or corrupt" in str(exc) or "damaged" in str(exc),
                str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            check("a corrupt zip raises ImportFileError", False, f"leaked {type(exc).__name__}")

        try:
            identify(source_dir / "nope.jar")
            check("a missing file raises", False, "nothing raised")
        except ImportFileError:
            check("a missing file raises ImportFileError", True)

        print("\nImporting a batch\n")
        results = import_files([jar, pack, shader, junk, broken, text], game_dir)
        for result in results:
            print(f"    {result.summary}")
        print()

        by_name = {r.source.name: r for r in results}
        check("every file produced a result", len(results) == 6, str(len(results)))
        check("the jar landed in mods/", (game_dir / "mods" / jar.name).is_file())
        check("the pack landed in resourcepacks/", (game_dir / "resourcepacks" / pack.name).is_file())
        check(
            "the shader landed in shaderpacks/, where Iris looks",
            (game_dir / "shaderpacks" / shader.name).is_file(),
        )
        check("and NOT in shaders/", not (game_dir / "shaders").exists())
        check("the unrecognised zip was refused", by_name[junk.name].error is not None)
        check(
            "its refusal explains itself",
            "nowhere obvious" in (by_name[junk.name].error or ""),
            by_name[junk.name].error or "",
        )
        check("the corrupt zip was refused", by_name[broken.name].error is not None)
        check("the corrupt zip was NOT copied", not (game_dir / "resourcepacks" / broken.name).exists())
        check("the text file was refused", by_name[text.name].error is not None)
        check("one bad file did not stop the rest", sum(1 for r in results if r.ok) == 3)

        copied = game_dir / "mods" / jar.name
        check("the copy is byte-identical", copied.read_bytes() == jar.read_bytes())
        check("the original is left alone", jar.is_file())

        print("\nDuplicates\n")
        again = import_file(jar, game_dir)
        check("re-importing the same file is skipped, not an error", again.skipped and again.ok)
        check("skipping is not reported as failure", again.error is None)

        # A different file that wants the same name in mods/.
        different = make_jar(source_dir / "other.jar")
        with zipfile.ZipFile(different, "a") as archive:
            archive.writestr("padding.txt", "x" * 500)
        clash_source = source_dir / "clash" / jar.name
        clash_source.parent.mkdir()
        shutil.copy2(different, clash_source)

        clash = import_file(clash_source, game_dir)
        check("a same-named different file is refused", clash.error is not None, str(clash.error))
        check(
            "the refusal mentions the clash",
            "already exists" in (clash.error or ""),
            clash.error or "",
        )
        check(
            "the existing file was not overwritten",
            copied.read_bytes() == jar.read_bytes(),
        )

        forced = import_file(clash_source, game_dir, overwrite=True)
        check("overwrite=True does replace it", forced.ok and not forced.skipped)
        check("the file really changed", copied.read_bytes() == clash_source.read_bytes())

        print("\nStaying inside the game directory\n")
        sneaky = source_dir / "sneaky"
        sneaky.mkdir()
        traversal = sneaky / "escape.jar"
        make_jar(traversal)

        escaped = import_file(traversal, game_dir)
        check("a file from outside the game dir imports fine", escaped.ok)
        check(
            "and lands inside it",
            game_dir.resolve() in escaped.destination.parents,
            str(escaped.destination),
        )

        outside = Path(tmp) / "outside"
        outside.mkdir()
        # A clean directory: mods/ in game_dir was deliberately overwritten above,
        # so re-importing there would (correctly) refuse rather than copy.
        fresh = Path(tmp) / "fresh_game"
        fresh.mkdir()
        for result in import_files([jar, pack, shader], fresh):
            check(
                f"{result.source.name} destination is under the game dir",
                result.destination is not None
                and fresh.resolve() in result.destination.parents,
                str(result.destination),
            )
        check(
            "nothing was written outside the game dir",
            not any(outside.iterdir()),
            str(list(outside.iterdir())),
        )

        print("\nSummary line\n")
        summary = describe(results)
        print(f"    {summary}")
        check("describe() mentions what was added", "added to" in summary)
        check("describe() mentions what was skipped", "skipped" in summary)

    print(f"\n  {_passed} passed, {_failed} failed")
    if _failed:
        print("\nFAILED")
        return 1
    print("\nM6 slice 5 imports PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
