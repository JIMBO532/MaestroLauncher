"""Entry point for MaestroLauncher.

Lives at the repo root so that ``core`` and ``gui_web`` both resolve as packages
when this is the script being run, and so PyInstaller has a single file to build
from.

    python main.py

This starts the web frontend in ``gui_web/``. The CustomTkinter app in ``gui/``
is still in the repo and still works, but it is no longer what runs by default
or what gets packaged:

    python -m gui.app
"""

from __future__ import annotations

from gui_web.app import main

if __name__ == "__main__":
    raise SystemExit(main())
