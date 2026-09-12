"""Regression test for the concurrent-launch crash fixed in core/installer.py.

Two nearly-simultaneous launches of the same brand-new instance raced on
link_shared_data() creating its shared-folder junctions for the first time;
one caller's create call failed with FileAlreadyExistsException, and the
game that spawned from it crashed on startup. This calls link_shared_data()
from two threads at once, many times over, and fails loudly if either call
raises or if the result is anything but a properly linked directory.

    python scripts/test_link_shared_data_concurrency.py
"""

from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import installer  # noqa: E402

TARGET = Path(__file__).resolve().parent.parent / "test_link_concurrency"
TRIALS = 100


def run_trial(index: int, directory: Path) -> list[str]:
    """Two threads linking the same brand-new instance at once. Returns
    whatever exceptions escaped link_shared_data() -- empty means neither did."""
    instance = directory / "maestro-instances" / f"trial{index}"
    escaped: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        try:
            installer.link_shared_data(instance, directory)
        except BaseException as exc:  # noqa: BLE001 -- a test, catch everything
            escaped.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    problems = [f"trial {index}: {type(exc).__name__}: {exc}" for exc in escaped]

    shared = installer.shared_data_directory(directory)
    for name in installer.SHARED_DIRECTORIES:
        link = instance / name
        target = shared / name
        if not installer._is_link_to(link, target):
            problems.append(f"trial {index}: {name} is not linked to {target} after both calls")

    return problems


def main() -> int:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    print(f"MaestroLauncher link_shared_data() concurrency test")
    print(f"  directory: {TARGET}")
    print(f"  trials:    {TRIALS} (2 threads racing a brand-new instance each time)\n")

    problems: list[str] = []
    for i in range(TRIALS):
        problems.extend(run_trial(i, TARGET))
        print(f"\r  {i + 1}/{TRIALS}", end="", flush=True)
    print()

    shutil.rmtree(TARGET, ignore_errors=True)

    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        for p in problems[:20]:
            print(f"  {p}")
        return 1

    print(f"\n{TRIALS}/{TRIALS} trials: no exception, every shared folder linked correctly.")
    print("Milestone -- link_shared_data() concurrency -- PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
