"""Milestone 5 acceptance test.

Searches Modrinth for "sodium", prints the top 5 hits, then downloads Sodium for
Minecraft 1.21.1 + Fabric into ./test_mc/mods/ and checks the jar is really there.
Exits 0 on success, 1 on failure.

    python scripts/test_mods.py
    python scripts/test_mods.py 1.20.4
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mods import (  # noqa: E402
    ModError,
    Progress,
    download_file,
    resolve_version,
    search_projects,
    subdirectory_for,
)

TARGET = Path(__file__).resolve().parent.parent / "test_mc"
LOADER = "fabric"
BAR_WIDTH = 30

_last_draw = 0.0


def render(progress: Progress) -> None:
    """Throttled single-line progress bar, same shape as the install test."""
    global _last_draw
    now = time.monotonic()
    if now - _last_draw < 0.05 and progress.percent < 100:
        return
    _last_draw = now

    filled = int(BAR_WIDTH * progress.fraction)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    status = progress.status[:42].ljust(42)
    print(f"\r[{bar}] {progress.percent:3d}%  {status}", end="", flush=True)


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.21.1"

    print("MaestroLauncher mod browser test")
    print(f"  game version: {version}")
    print(f"  loader:       {LOADER}")
    print(f"  directory:    {TARGET}")

    # 1. Search.
    print('\nSearching Modrinth for "sodium"...\n')
    try:
        results = search_projects(
            "sodium", game_version=version, loader=LOADER, limit=5
        )
    except ModError as exc:
        print(f"FAILED: search: {exc}")
        return 1

    if not results:
        print("FAILED: search returned no results.")
        return 1

    for i, hit in enumerate(results, start=1):
        blurb = hit.description[:58] + ("..." if len(hit.description) > 58 else "")
        print(f"  {i}. {hit.title[:28]:<28} {hit.downloads:>12,} dl  by {hit.author}")
        print(f"     {hit.slug}  [{hit.project_type}]  {blurb}")

    # 2. Resolve. Search relevance is not a promise, so ask for Sodium by slug.
    print()
    try:
        file = resolve_version(
            "sodium", version, loader=LOADER, project_type="mod"
        )
    except ModError as exc:
        print(f"FAILED: resolve: {exc}")
        return 1

    print(f"Resolved: {file.name}")
    print(f"  version:  {file.version_number}  ({file.version_type})")
    print(f"  file:     {file.filename}  ({file.size / 1024:.0f} KB)")
    print(f"  loaders:  {', '.join(file.loaders)}  |  game: {', '.join(file.game_versions)}")
    print(f"  goes to:  {subdirectory_for(file.project_type)}/\n")

    if version not in file.game_versions:
        print(f"FAILED: resolved a file that does not list {version}.")
        return 1
    if LOADER not in file.loaders:
        print(f"FAILED: resolved a file that does not list the {LOADER} loader.")
        return 1

    # 3. Download.
    started = time.monotonic()
    try:
        path = download_file(file, TARGET, on_progress=render)
    except ModError as exc:
        print(f"\n\nFAILED: download: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        return 1

    print(f"\n\nFinished in {time.monotonic() - started:.1f}s")

    # 4. Verify it is on disk, in mods/, and non-empty.
    expected_dir = TARGET.resolve() / "mods"
    if not path.exists():
        print(f"FAILED: {path} does not exist after download.")
        return 1
    if path.parent != expected_dir:
        print(f"FAILED: landed in {path.parent}, expected {expected_dir}.")
        return 1

    size = path.stat().st_size
    print(f"  jar:  {path}")
    print(f"  size: {size:,} bytes")
    if size == 0:
        print("FAILED: the jar is empty.")
        return 1
    if file.size and size != file.size:
        print(f"FAILED: size is {size}, Modrinth said {file.size}.")
        return 1

    # 5. The same pipeline for a resource pack: a different project type, a
    #    different folder, and one Modrinth files under the "minecraft" loader,
    #    so the Fabric filter must not be applied to it.
    print("\n" + "-" * 60)
    print("Resource packs\n")

    try:
        packs = search_projects(
            "faithful", game_version=version, loader=LOADER,
            project_type="resourcepack", limit=5,
        )
    except ModError as exc:
        print(f"FAILED: resource pack search: {exc}")
        return 1

    if not packs:
        print("FAILED: no resource packs found. The loader filter may be leaking.")
        return 1

    print(f"  {len(packs)} results even though loader={LOADER!r} was passed:")
    for hit in packs:
        print(f"    {hit.title[:30]:<30} {hit.project_type:<13} {hit.downloads:>12,} dl")

    if any(hit.project_type != "resourcepack" for hit in packs):
        print("FAILED: a non-resourcepack came back from a resourcepack search.")
        return 1

    # Take the smallest, so this does not download a 200MB 512x pack.
    resolved = []
    for hit in packs:
        try:
            resolved.append(
                resolve_version(hit.slug, version, loader=LOADER, project_type="resourcepack")
            )
        except ModError:
            continue
    if not resolved:
        print(f"FAILED: none of those packs has a {version} release.")
        return 1

    pack = min(resolved, key=lambda f: f.size or 1 << 40)
    print(f"\n  Resolved: {pack.name}")
    print(f"    file:    {pack.filename}  ({pack.size / 1024 / 1024:.1f} MB)")
    print(f"    loaders: {', '.join(pack.loaders)}  <- what Modrinth reports")
    print(f"    goes to: {subdirectory_for(pack.project_type)}/\n")

    if subdirectory_for(pack.project_type) != "resourcepacks":
        print("FAILED: a resource pack is not routed to resourcepacks/.")
        return 1

    try:
        pack_path = download_file(pack, TARGET, on_progress=render)
    except ModError as exc:
        print(f"\n\nFAILED: resource pack download: {exc}")
        return 1

    print()
    if not pack_path.exists():
        print(f"FAILED: {pack_path} does not exist after download.")
        return 1
    if pack_path.parent != TARGET.resolve() / "resourcepacks":
        print(f"FAILED: landed in {pack_path.parent}, expected resourcepacks/.")
        return 1
    if pack_path.stat().st_size == 0:
        print("FAILED: the resource pack is empty.")
        return 1
    if (TARGET / "mods" / pack_path.name).exists():
        print("FAILED: the resource pack also landed in mods/.")
        return 1

    print(f"  pack: {pack_path}")
    print(f"  size: {pack_path.stat().st_size:,} bytes")

    # 6. Shaders are a third type going to a third folder.
    print("\nShaders\n")
    try:
        shaders = search_projects(
            "shader", game_version=version, loader=LOADER,
            project_type="shader", limit=3,
        )
    except ModError as exc:
        print(f"FAILED: shader search: {exc}")
        return 1

    for hit in shaders:
        print(f"    {hit.title[:30]:<30} {hit.project_type:<13} -> {subdirectory_for(hit.project_type)}/")
    if any(subdirectory_for(hit.project_type) != "shaderpacks" for hit in shaders):
        print("FAILED: a shader is not routed to shaderpacks/.")
        return 1
    if subdirectory_for("shader") != "shaderpacks":
        print("FAILED: shader routing is wrong.")
        return 1
    print("\n  shaders route to shaderpacks/, which is what Iris and OptiFine read")

    print("\nMilestone 5 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
