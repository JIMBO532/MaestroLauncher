"""MaestroLauncher's web frontend, hosted in a native window.

M8 slice 1: the static shell only. Nothing here talks to ``core`` yet -- the
buttons are deliberately dead. The point of this slice is to see whether the
look works before anything is wired to it.

The one exception is the background-image setting: it needs real file I/O
(a native picker, compressing what the user drops, and keeping a copy that
outlives the source file), so it gets its own small bridge below rather than
waiting for the rest of M8 to be wired up.

The CustomTkinter app in ``gui/`` is untouched and keeps working; this lives
alongside it until M8 is finished.

    python gui_web/app.py
"""

from __future__ import annotations

import base64
import binascii
import io
import os
from pathlib import Path
from typing import Optional

import webview
from PIL import Image, UnidentifiedImageError

WEB_ROOT = Path(__file__).resolve().parent / "web"
INDEX = WEB_ROOT / "index.html"

WINDOW_TITLE = "MaestroLauncher"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 760
MIN_SIZE = (1024, 640)

# Matches --bg in styles.css. Set on the window too so the native frame does not
# flash white before the first paint.
BACKGROUND = "#0a0a0a"

# Same treatment as the bundled screenshot: cap the long edge and re-encode
# as JPEG so a phone photo dropped in here doesn't ship at multiple megabytes.
MAX_BACKGROUND_DIM = 1920
BACKGROUND_JPEG_QUALITY = 85


def data_dir() -> Path:
    """Where the launcher keeps its own files. Never the game directory --
    that is a caller-supplied argument everywhere in ``core``, not this."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".maestrolauncher"
    directory = base / "MaestroLauncher"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def custom_background_path() -> Path:
    return data_dir() / "background.jpg"


def _compress_to_jpeg(raw: bytes) -> bytes:
    """Re-encode arbitrary PNG/JPEG bytes to a size-capped JPEG.

    Raises ``ValueError`` for anything that isn't PNG/JPEG and
    ``UnidentifiedImageError``/``OSError`` for bytes Pillow can't read at all
    -- the caller turns both into a plain ``{"ok": False}`` for the frontend.
    """
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError(f"unsupported image format: {image.format}")
        image.load()
        rgb = image.convert("RGB")
    if rgb.width > MAX_BACKGROUND_DIM or rgb.height > MAX_BACKGROUND_DIM:
        rgb.thumbnail((MAX_BACKGROUND_DIM, MAX_BACKGROUND_DIM), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=BACKGROUND_JPEG_QUALITY)
    return buffer.getvalue()


def _as_data_url(jpeg_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")


class BackgroundApi:
    """Exposed to the page as ``window.pywebview.api``.

    Every method returns a plain dict instead of raising, so a cancelled
    dialog or a corrupt file is a JS-side ``{"ok": False}`` rather than an
    unhandled promise rejection with a Python traceback in it.
    """

    def __init__(self) -> None:
        self._window: Optional["webview.Window"] = None

    def bind(self, window: "webview.Window") -> None:
        self._window = window

    def pick_background(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "window not ready"}
        try:
            selection = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=("Images (*.png;*.jpg;*.jpeg)",),
            )
        except Exception as exc:  # native dialog can fail for reasons outside our control
            return {"ok": False, "error": str(exc)}
        if not selection:
            return {"ok": False, "cancelled": True}
        try:
            raw = Path(selection[0]).read_bytes()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return self._import(raw)

    def import_background_data(self, data_url: str) -> dict:
        """Used for drag-and-drop: the browser reads the dropped file into a
        data URL client-side since a dropped ``File`` carries no real path in
        a WebView2/Chromium sandbox, then hands the bytes over here."""
        try:
            _, encoded = data_url.split(",", 1)
            raw = base64.b64decode(encoded)
        except (ValueError, binascii.Error):
            return {"ok": False, "error": "malformed image data"}
        return self._import(raw)

    def _import(self, raw: bytes) -> dict:
        try:
            jpeg_bytes = _compress_to_jpeg(raw)
        except (UnidentifiedImageError, ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        custom_background_path().write_bytes(jpeg_bytes)
        return {"ok": True, "dataUrl": _as_data_url(jpeg_bytes)}

    def reset_background(self) -> dict:
        try:
            custom_background_path().unlink(missing_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def get_custom_background(self) -> dict:
        path = custom_background_path()
        if not path.is_file():
            return {"ok": True, "dataUrl": None}
        try:
            return {"ok": True, "dataUrl": _as_data_url(path.read_bytes())}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}


def create_window() -> "webview.Window":
    """Build the launcher window without starting the event loop.

    Separate from :func:`main` so the window can be created and inspected
    without blocking on ``webview.start()``.
    """
    if not INDEX.is_file():
        raise FileNotFoundError(f"Frontend missing: {INDEX}")

    api = BackgroundApi()
    window = webview.create_window(
        WINDOW_TITLE,
        str(INDEX),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=MIN_SIZE,
        resizable=True,
        background_color=BACKGROUND,
        js_api=api,
    )
    api.bind(window)
    return window


def main() -> int:
    create_window()
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
