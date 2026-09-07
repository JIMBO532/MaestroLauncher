"""MaestroLauncher's web frontend, hosted in a native window.

M8 slice 1: the static shell only. Nothing here talks to ``core`` yet -- the
buttons are deliberately dead. The point of this slice is to see whether the
look works before anything is wired to it.

The CustomTkinter app in ``gui/`` is untouched and keeps working; this lives
alongside it until M8 is finished.

    python gui_web/app.py
"""

from __future__ import annotations

from pathlib import Path

import webview

WEB_ROOT = Path(__file__).resolve().parent / "web"
INDEX = WEB_ROOT / "index.html"

WINDOW_TITLE = "MaestroLauncher"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 760
MIN_SIZE = (1024, 640)

# Matches --bg in styles.css. Set on the window too so the native frame does not
# flash white before the first paint.
BACKGROUND = "#0a0a0a"


def create_window() -> "webview.Window":
    """Build the launcher window without starting the event loop.

    Separate from :func:`main` so the window can be created and inspected
    without blocking on ``webview.start()``.
    """
    if not INDEX.is_file():
        raise FileNotFoundError(f"Frontend missing: {INDEX}")

    return webview.create_window(
        WINDOW_TITLE,
        str(INDEX),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=MIN_SIZE,
        resizable=True,
        background_color=BACKGROUND,
    )


def main() -> int:
    create_window()
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
