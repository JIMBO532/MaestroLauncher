"""Entry point for MaestroLauncher.

Lives at the repo root so that ``core`` and ``gui`` both resolve as packages when
this is the script being run, and so PyInstaller has a single file to build from.

    python main.py
"""

from __future__ import annotations

from gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
