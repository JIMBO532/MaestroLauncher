"""Milestone 1 acceptance test.

Installs a Minecraft version into ./test_mc/ and prints live progress.
Exits 0 on success, 1 on failure.

    python scripts/test_install.py
    python scripts/test_install.py 1.20.4
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.installer import (  # noqa: E402
    InstallError,
    Progress,
    install_version,
    is_installed,
    latest_release,
)

TARGET = Path(__file__).resolve().parent.parent / "test_mc"
BAR_WIDTH = 30

_last_draw = 0.0


def render(progress: Progress) -> None:
    """Throttled single-line progress bar. 20 fps is plenty; the library fires
    this callback thousands of times and unthrottled printing dominates runtime."""
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

    print(f"MaestroLauncher install test")
    print(f"  version:   {version}")
    print(f"  directory: {TARGET}")

    try:
        print(f"  latest release available: {latest_release()}")
    except InstallError as exc:
        print(f"\nCould not reach Mojang: {exc}")
        return 1

    if is_installed(version, TARGET):
        print("  already installed -- re-running to confirm it is a no-op\n")
    else:
        print()

    started = time.monotonic()
    try:
        path = install_version(version, TARGET, on_progress=render)
    except InstallError as exc:
        print(f"\n\nFAILED: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        return 1

    elapsed = time.monotonic() - started
    print(f"\n\nInstalled in {elapsed:.1f}s")

    if not is_installed(version, path):
        print("FAILED: install finished but the version does not validate.")
        return 1

    jar = path / "versions" / version / f"{version}.jar"
    print(f"  client jar: {jar.exists()} ({jar.stat().st_size // 1024 // 1024} MB)"
          if jar.exists() else "  client jar: MISSING")
    print(f"  libraries:  {sum(1 for _ in (path / 'libraries').rglob('*.jar'))} jars")
    print("\nMilestone 1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
