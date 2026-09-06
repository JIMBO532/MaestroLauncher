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

    print("\nMilestone 5 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
