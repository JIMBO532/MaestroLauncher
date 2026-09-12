"""MaestroLauncher's web frontend, hosted in a native window.

M8 slice 1 was the static shell, nothing wired to ``core``. Slice 5 wired the
version selector to ``core.installer``. This slice adds About (reads
``core.__version__``, nothing else) and Content -- Modrinth search, install,
and local file import via ``core.mods``/``core.imports``. Everything here is
read-only against ``core``: it calls what is already there and changes
nothing about how it works.

Content's drag-and-drop needs a real filesystem path, not just bytes, since a
dropped mod jar or resource pack can be far larger than the background image
the earlier bytes-over-the-bridge approach was built for. WebView2 only hands
out a real path through pywebview's ``window.dom`` event API rather than the
plain js_api bridge, so that one interaction is wired differently from
everything else here -- see ``_register_content_dropzone``.

The CustomTkinter app in ``gui/`` is untouched and keeps working; this lives
alongside it until M8 is finished.

    python gui_web/app.py
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# ``core`` is a package at the project root, one level above this file. Run
# directly (``python gui_web/app.py``), Python puts gui_web/ on sys.path, not
# the root, so ``import core`` would fail without this -- main.py avoids the
# problem by living at the root itself, but this module's own docstring says
# to run it standalone, so it has to add the root back itself.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import webview
from PIL import Image, UnidentifiedImageError

from core import __version__ as APP_VERSION
from core import auth, imports, installer, launch, mods
from core.auth import Account, AuthError, LoginCancelled, LoginRequired
from core.installer import InstallError, Progress
from core.launch import LaunchError
from core.mods import ModError


def _web_root() -> Path:
    """Where the frontend's files are, running from source or frozen.

    PyInstaller unpacks a one-file build into a temp directory and points
    ``sys._MEIPASS`` at it; MaestroLauncher.spec puts ``gui_web/web`` in
    there. Deriving it from ``__file__`` instead happens to land in the same
    place, but only because PyInstaller fabricates a ``__file__`` under that
    same directory for a module that no longer exists on disk. Saying which
    one is meant costs nothing and does not depend on that staying true.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "gui_web" / "web"
    return Path(__file__).resolve().parent / "web"


WEB_ROOT = _web_root()
INDEX = WEB_ROOT / "index.html"

WINDOW_TITLE = "MaestroLauncher"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 760
MIN_SIZE = (1024, 640)

# Matches --bg in styles.css. Set on the window too so the native frame does not
# flash white before the first paint.
BACKGROUND = "#0a0a0a"

# The launcher is Fabric-only for now, same as gui/app.py -- core.mods drops
# this filter by itself for the project types that have no loader.
MOD_LOADER = "fabric"

# Enough to fill the list without a scrollbar marathon, same as gui/app.py.
CONTENT_SEARCH_LIMIT = 10

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


# The one loader this launcher installs. mll's Fabric installer always names
# its profile this way -- see mod_loader's own source -- so this is reading
# a stable convention, not guessing at one.
FABRIC_PROFILE_PREFIX = "fabric-loader-"

# How long a finished-job message stays up before the status line goes quiet
# again, matching gui/app.py's RESULT_DWELL_MS. Errors ignore this and stay.
RESULT_DWELL_MS = 6000

# An install fires progress ticks in the thousands and each one crossing into
# the page costs a real round trip, so they are coalesced the way
# BackgroundWorker.progress_bridge coalesces them for Tk: at most one update
# per interval, with the last one always delivered.
PROGRESS_INTERVAL_S = 0.1

# core.launch.RunningGame.wait() returning 0 is not a success signal -- the
# game exits 0 even when it never created a window, a fact this launcher
# already knew and forgot the moment Play grew a real implementation. It
# reported the process as "running" the instant it spawned, which is also
# true one line before a crash. scripts/test_launch.py verifies a real
# launch by reading the log instead, so this reuses its definition of
# "reached the main menu" rather than inventing a second one.
#
# The sound engine and the GUI texture atlas are both built while the main
# menu is constructed, so either arriving in the log is enough on its own.
MENU_MARKERS = ("Sound engine started", "OpenAL initialized", "textures/atlas")

# Generous on purpose: assets are already on disk by the time Play calls
# this (installing happens first), but a cold JVM, shader compilation or a
# slow machine can still take real time to get from spawn to menu.
PLAY_MENU_TIMEOUT_S = 90.0

# Minecraft writes this exact line, split across two "#@!@#" markers, when it
# crashes during startup -- the path after it is the crash report to point
# someone at instead of a bare "it didn't start".
_CRASH_REPORT_RE = re.compile(r"Crash report saved to:\s*#@!@#\s*(.+)")


# The Azure application this launcher signs in as.
#
# Shipped in the clear on purpose. This is a PKCE public client -- the OAuth
# flow built precisely for apps that cannot keep a secret, which is every
# desktop app, since anything compiled into one can be read back out of it.
# The ID names the application; it authorises nothing on its own. Microsoft
# expects public clients to ship it, and the redirect URI plus PKCE are what
# actually stop someone else's app from using it to get tokens.
#
# The alternative was asking every person who installs this to register their
# own Azure app and then wait for Mojang to approve it, which is not a thing
# anyone would do.
#
# A .env beside the launcher still wins, so a development build can point at
# a different app registration without touching this.
CLIENT_ID = "acf0e9ef-541e-45e6-8e50-7c5b09250dcc"


def _env_file_candidates() -> list[Path]:
    """Where the Azure client ID might live, same order as gui/app.py."""
    beside_exe = Path(sys.executable).resolve().parent
    return [_PROJECT_ROOT / ".env", beside_exe / ".env", beside_exe.parent / ".env"]


def _client_id() -> Optional[str]:
    """The client ID to sign in with: a local override, else the shipped one.

    auth.load_client_id checks MAESTRO_CLIENT_ID/AZURE_CLIENT_ID in the
    environment before it reads any file, so an environment variable beats a
    .env, which in turn beats the bundled default.
    """
    for candidate in _env_file_candidates():
        found = auth.load_client_id(candidate)
        if found:
            return found
    return CLIENT_ID or None


def _read_log(path: Path) -> str:
    """The game's log so far. Empty if it has not been created yet -- a race
    at the very start of a launch, not a reason to blow up watching it."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _installed_fabric_profile(version: str, directory: Path) -> Optional[str]:
    """The Fabric profile already on disk for a Minecraft version, if any.

    Fabric's installer names its own profile and offers no way to predict the
    loader number in it, so the only honest way to find one already installed
    is to look at what inherits from this version.
    """
    for version_id in installer.installed_versions(directory):
        if not version_id.startswith(FABRIC_PROFILE_PREFIX):
            continue
        if installer.base_game_version(version_id, directory) == version:
            return version_id
    return None


class _Throttle:
    """Rate-limit progress ticks on their way to the page.

    100% is always let through, so the bar never stops one tick short of
    finished just because the last tick arrived too soon after the one before.
    """

    def __init__(self, emit: Callable[[Progress], None]) -> None:
        self._emit = emit
        self._last = 0.0

    def __call__(self, progress: Progress) -> None:
        now = time.monotonic()
        if progress.percent < 100 and now - self._last < PROGRESS_INTERVAL_S:
            return
        self._last = now
        self._emit(progress)


def _classify_installed(directory: Path) -> dict[str, dict[str, bool]]:
    """Group installed profiles by the Minecraft release they belong to.

    Only a Fabric profile or an optimized profile counts as one of the two
    variants the selector offers. A plain vanilla install (or anything left
    by another launcher) is still noted so the release sorts to the front,
    but starts both variants unchecked.
    """
    result: dict[str, dict[str, bool]] = {}
    for version_id in installer.installed_versions(directory):
        if installer.is_optimized_profile(version_id):
            base = installer.base_game_version(version_id, directory)
            result.setdefault(base, {"fabric": False, "optimized": False})["optimized"] = True
        elif version_id.startswith(FABRIC_PROFILE_PREFIX):
            base = installer.base_game_version(version_id, directory)
            result.setdefault(base, {"fabric": False, "optimized": False})["fabric"] = True
        else:
            result.setdefault(version_id, {"fabric": False, "optimized": False})
    return result


def _ordered_versions(directory: Path) -> tuple[list[dict], Optional[str]]:
    """Every version the selector should list, installed ones first.

    Offline is survivable the same way it is in gui/app.py's load_versions():
    what is already on disk still has something to show even when Mojang
    cannot be reached, and only a token empty of *both* is a real failure.
    """
    classified = _classify_installed(directory)

    warning: Optional[str] = None
    try:
        releases = installer.list_releases()
    except InstallError as exc:
        if not classified:
            raise
        releases = []
        warning = f"{exc} Showing installed versions only."

    front = [v for v in releases if v in classified]
    orphans = [v for v in classified if v not in releases]
    back = [v for v in releases if v not in classified]
    order = front + orphans + back

    versions = [
        {
            "version": v,
            "fabricInstalled": classified.get(v, {}).get("fabric", False),
            "optimizedInstalled": classified.get(v, {}).get("optimized", False),
        }
        for v in order
    ]
    return versions, warning


class Api:
    """Exposed to the page as ``window.pywebview.api``.

    Every method returns a plain dict instead of raising, so a cancelled
    dialog or a corrupt file is a JS-side ``{"ok": False}`` rather than an
    unhandled promise rejection with a Python traceback in it.
    """

    def __init__(self) -> None:
        self._window: Optional["webview.Window"] = None
        self._account: Optional[Account] = None
        self._game: Optional[launch.RunningGame] = None
        # One long job at a time, same as gui/app.py's busy flag: the inputs
        # are locked while one runs, and a second press must not start a
        # parallel install over the top of the first.
        self._busy = False
        self._busy_lock = threading.Lock()

    def bind(self, window: "webview.Window") -> None:
        self._window = window

    # -- job bookkeeping: busy state, status line, progress bar --------------

    def _claim(self) -> bool:
        """Take the busy flag, or report that something else already has it."""
        with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
        self._push("job", "onBusy", True)
        return True

    def _release(self) -> None:
        with self._busy_lock:
            self._busy = False
        self._push("job", "onBusy", False)

    def _status(self, text: str) -> None:
        """Say what is happening. Stays up until something replaces it."""
        self._push("job", "onStatus", text)

    def _result(self, text: str) -> None:
        """Report a finished job. Clears itself after a few seconds."""
        self._push("job", "onResult", text)

    def _failed(self, text: str) -> None:
        """Report a problem. Stays up until the next action."""
        self._push("job", "onError", text)

    def _reporter(self) -> Callable[[Progress], None]:
        """A throttled progress callback to hand to any core function."""

        def emit(progress: Progress) -> None:
            self._push(
                "job",
                "onProgress",
                {"status": progress.status, "percent": progress.percent},
            )

        return _Throttle(emit)

    # -- background image --------------------------------------------------

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

    # -- versions ------------------------------------------------------------
    #
    # The same shape as BackgroundWorker in gui/app.py, adapted to this
    # architecture: a plain background thread stands in for the worker
    # thread, and ``window.evaluate_js`` (documented safe from any thread)
    # stands in for posting a callback onto Tk's queue and draining it with
    # ``after()``. Either way, work that can take a network round trip runs
    # off the thread that has to keep drawing, and status/progress/results
    # are delivered back rather than returned, so the call that kicks a job
    # off returns immediately.

    def list_versions(self) -> dict:
        """Kick off the version fetch. Results arrive via window.__maestro.versions."""
        threading.Thread(
            target=self._list_versions_worker, daemon=True, name="maestro-versions"
        ).start()
        return {"ok": True}

    def _list_versions_worker(self) -> None:
        directory = installer.default_directory()
        self._push("versions", "onStatus", "Checking installed versions...")
        self._status("Fetching the version list from Mojang...")
        try:
            self._push("versions", "onStatus", "Fetching the release list from Mojang...")
            versions, warning = _ordered_versions(directory)
        except InstallError as exc:
            self._push("versions", "onError", str(exc))
            self._failed(f"Could not load versions: {exc}")
            return
        self._push("versions", "onLoaded", {"versions": versions, "warning": warning})
        # Nothing to report: the version menu is the result.
        self._status(warning or "")

    def install_variant(self, version: str, variant: str) -> dict:
        """Install the Fabric or Fabric+Optimized profile for ``version``.

        Fire-and-forget like :meth:`list_versions`: progress and the outcome
        arrive through window.__maestro.versions so a slow install cannot
        block the page waiting on this call to return.
        """
        if variant not in ("fabric", "optimized"):
            return {"ok": False, "error": f"unknown variant: {variant}"}
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._install_variant_worker,
            args=(version, variant),
            daemon=True,
            name="maestro-install",
        ).start()
        return {"ok": True}

    def _install_variant_worker(self, version: str, variant: str) -> None:
        directory = installer.default_directory()
        report = self._reporter()

        def on_progress(progress: Progress) -> None:
            # Two audiences for the same tick: the row in the version menu
            # draws its own inline bar, and the shared status line below Play
            # reports whatever is happening anywhere.
            self._push(
                "versions",
                "onInstallProgress",
                {
                    "version": version,
                    "variant": variant,
                    "status": progress.status,
                    "percent": progress.percent,
                },
            )
            report(progress)

        try:
            self._ensure_profile(version, variant, directory, on_progress)
        except (InstallError, ModError) as exc:
            self._push(
                "versions",
                "onInstallError",
                {"version": version, "variant": variant, "error": str(exc)},
            )
            self._failed(f"Could not install {version}: {exc}")
            self._release()
            return
        self._push("versions", "onInstallComplete", {"version": version, "variant": variant})
        label = "Fabric · Optimized" if variant == "optimized" else "Fabric"
        self._result(f"{version} {label} is ready -- press Play.")
        self._release()

    # -- account -------------------------------------------------------------

    def restore_account(self) -> dict:
        """Bring back a saved login on startup, without opening a browser.

        Deliberately ``auth.refresh`` rather than ``auth.login_or_refresh``,
        for the same reason gui/app.py's restore_account() is: the latter
        falls through to an interactive login when the saved token is dead,
        and a browser opening by itself because the launcher started is not
        something anyone asked for. A token that will not renew just leaves
        the panel signed out, with Sign in right there.
        """
        threading.Thread(
            target=self._restore_account_worker, daemon=True, name="maestro-restore"
        ).start()
        return {"ok": True}

    def _restore_account_worker(self) -> None:
        directory = installer.default_directory()
        saved = auth.load_account(directory)
        if saved is None or not saved.refresh_token:
            self._push("account", "onSignedOut", {"message": None})
            return

        client_id = _client_id()
        if client_id is None:
            self._push(
                "account",
                "onSignedOut",
                {
                    "username": saved.username,
                    "message": (
                        f"Signed in as {saved.username} last time, but there is no Azure "
                        "client ID to renew it with. See PLAN.md M0."
                    ),
                },
            )
            return

        self._push("account", "onRestoring", {"username": saved.username})
        try:
            account = auth.refresh(client_id, saved.refresh_token)
            auth.save_account(account, directory)
        except LoginRequired:
            # The normal end of a token's life, not an error worth shouting
            # about. Say it once and leave the panel signed out.
            self._push(
                "account",
                "onSignedOut",
                {
                    "username": saved.username,
                    "message": "Your saved login expired. Sign in again to play.",
                },
            )
            return
        except AuthError as exc:
            self._push(
                "account",
                "onSignedOut",
                {"username": saved.username, "message": f"Could not restore your login: {exc}"},
            )
            return

        self._account = account
        self._push("account", "onSignedIn", {"username": account.username, "uuid": account.uuid})

    def sign_in(self) -> dict:
        """Interactive Microsoft login, browser and all, off the UI thread."""
        client_id = _client_id()
        if client_id is None:
            return {
                "ok": False,
                "error": (
                    "No Azure client ID. Put MAESTRO_CLIENT_ID=<the id> in a .env file "
                    "beside the launcher. See PLAN.md M0."
                ),
            }
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._sign_in_worker, args=(client_id,), daemon=True, name="maestro-login"
        ).start()
        return {"ok": True}

    def _sign_in_worker(self, client_id: str) -> None:
        directory = installer.default_directory()
        self._status("Opening your browser to sign in with Microsoft...")
        try:
            # login_or_refresh here, unlike restore: this one was asked for, so
            # falling through to a browser is exactly what was wanted.
            account = auth.login_or_refresh(client_id, directory, on_status=self._status)
        except LoginCancelled:
            self._failed("Sign in was cancelled.")
            self._push("account", "onSignedOut", {"message": None})
            self._release()
            return
        except AuthError as exc:
            self._failed(f"Sign in failed: {exc}")
            self._push("account", "onSignedOut", {"message": None})
            self._release()
            return

        self._account = account
        self._push("account", "onSignedIn", {"username": account.username, "uuid": account.uuid})
        self._result(f"Signed in as {account.username}.")
        self._release()

    def sign_out(self) -> dict:
        """Forget the saved login. A game already running is left alone."""
        try:
            auth.clear_account(installer.default_directory())
        except AuthError as exc:
            return {"ok": False, "error": str(exc)}
        self._account = None
        self._push("account", "onSignedOut", {"message": None})
        self._result("Signed out.")
        return {"ok": True}

    # -- play ----------------------------------------------------------------

    def play(self, version: str, variant: str, memory_mb: int) -> dict:
        """Install the chosen version if it is missing, then launch it.

        One press for the whole thing, like gui/app.py's Play: whether the
        files happen to be on disk already is not a decision worth making
        anyone take.
        """
        if not version:
            return {"ok": False, "error": "Pick a version first."}
        if self._account is None or not self._account.access_token:
            return {
                "ok": False,
                "error": "Sign in first -- Minecraft will not start without an account.",
            }
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._play_worker,
            args=(version, variant, int(memory_mb or launch.DEFAULT_MEMORY_MB)),
            daemon=True,
            name="maestro-play",
        ).start()
        return {"ok": True}

    def _play_worker(self, version: str, variant: str, memory_mb: int) -> None:
        account = self._account
        directory = installer.default_directory()
        report = self._reporter()

        try:
            profile_id = self._ensure_profile(version, variant, directory, report)

            self._status(f"Starting Minecraft {profile_id}...")

            # Every version launches in its own directory. Mods belong to a
            # game version, and two versions sharing one mods folder is what
            # makes Fabric refuse to start.
            game_directory = installer.instance_directory(profile_id, directory)
            game_directory.mkdir(parents=True, exist_ok=True)

            # Worlds, settings and packs are shared across versions; only mods
            # are not. Relinking before every launch keeps an instance made
            # before this existed in step with one made after.
            for note in installer.link_shared_data(game_directory, directory):
                self._status(note)

            game = launch.launch(
                profile_id,
                directory,
                account.username,
                account.uuid,
                account.access_token,
                memory_mb=memory_mb,
                game_directory=game_directory,
            )
        except (InstallError, ModError, LaunchError) as exc:
            self._failed(f"Could not start the game: {exc}")
            self._release()
            return
        except Exception as exc:  # noqa: BLE001 -- the page must never see a traceback
            self._failed(f"Could not start the game: {exc}")
            self._release()
            return

        self._game = game
        self._status(f"Waiting for {profile_id} to reach the main menu...")
        outcome, detail = self._await_game_start(game)

        if outcome == "menu":
            self._push(
                "job",
                "onPlayStarted",
                {"profile": profile_id, "pid": game.pid, "logPath": str(game.log_path)},
            )
            self._result(f"Minecraft {profile_id} is running (pid {game.pid}).")
        elif outcome == "crashed":
            where = f" Crash report: {detail}" if detail else " Check the log."
            self._failed(f"Minecraft {profile_id} crashed on startup.{where}")
        elif outcome == "exited":
            self._failed(
                f"Minecraft {profile_id} exited before reaching the main menu "
                f"(exit code {detail}). Log: {game.log_path}"
            )
        else:  # "timeout" -- still running, genuinely unknown either way
            self._status(
                f"Minecraft {profile_id} (pid {game.pid}) is taking a while to start. "
                f"Log: {game.log_path}"
            )
        self._release()

    def _await_game_start(self, game: launch.RunningGame) -> tuple[str, Optional[str]]:
        """Wait for the log to say the game actually got somewhere.

        Returns ``("menu", None)``, ``("crashed", <report path or None>)``,
        ``("exited", <exit code as str>)`` or ``("timeout", None)``. Reading
        the log rather than trusting the exit code is the whole point --
        see the comment on MENU_MARKERS above.
        """
        deadline = time.monotonic() + PLAY_MENU_TIMEOUT_S
        while time.monotonic() < deadline:
            text = _read_log(game.log_path)

            if any(marker in text for marker in MENU_MARKERS):
                return "menu", None

            match = _CRASH_REPORT_RE.search(text)
            if match:
                return "crashed", match.group(1).strip()

            if not game.is_running():
                # The crash line can land a beat after the process handle
                # already reports gone; one more read before calling it a
                # bare exit avoids blaming a plain exit on what was actually
                # a crash.
                time.sleep(0.5)
                text = _read_log(game.log_path)
                match = _CRASH_REPORT_RE.search(text)
                if match:
                    return "crashed", match.group(1).strip()
                if any(marker in text for marker in MENU_MARKERS):
                    return "menu", None
                return "exited", str(game.process.poll())

            time.sleep(1.0)

        return "timeout", None

    def _ensure_profile(
        self,
        version: str,
        variant: str,
        directory: Path,
        report: Callable[[Progress], None],
    ) -> str:
        """The profile ID to launch, installing it first if it is missing.

        Fabric and Fabric+Optimized are the two the version selector offers,
        and they install by different routes: the optimized one additionally
        installs the Modrinth pack into the instance, which is the same pair
        of steps gui/app.py's begin_optimization() runs.
        """
        if variant == "optimized":
            profile_id = installer.optimized_profile_id(version)
            if installer.is_installed(profile_id, directory):
                return profile_id

            self._status(f"Installing Minecraft {version} and Fabric...")
            profile_id = installer.install_optimized_profile(
                version, directory, on_progress=report
            )

            instance = installer.instance_directory(profile_id, directory)
            self._status("Installing the optimization pack from Modrinth...")
            # Sodium goes in as a candidate rather than a fallback decided
            # here -- install_collection reads what the jars declare and drops
            # whichever of a mutually exclusive pair came second.
            entries = mods.install_collection(
                mods.OPTIMIZATION_COLLECTION,
                version,
                instance,
                extra_projects=("sodium",),
                on_progress=report,
            )
            skipped = [entry for entry in entries if not entry.installed]
            if skipped:
                self._status(
                    f"{len(skipped)} of the pack's mods were skipped: "
                    + "; ".join(f"{entry.title} ({entry.error})" for entry in skipped[:3])
                )
            return profile_id

        existing = _installed_fabric_profile(version, directory)
        if existing is not None:
            return existing

        self._status(f"Installing Minecraft {version} with Fabric and Sodium...")
        return installer.install_fabric_with_sodium(version, directory, on_progress=report)

    # -- settings ------------------------------------------------------------
    #
    # These back the new Settings controls with real values and real OS
    # actions (a folder dialog, opening Explorer) where that is cheap and
    # self-contained. What is deliberately NOT here yet: threading a chosen
    # game folder into list_versions()/install_variant() -- the memory value
    # now reaches a real launch, but the folder does not.

    def get_launch_settings_bounds(self) -> dict:
        """The RAM slider's range, read from core.launch rather than
        duplicated as a second set of numbers that could drift from it."""
        return {
            "ok": True,
            "minMemoryMb": launch.MINIMUM_MEMORY_MB,
            "defaultMemoryMb": launch.DEFAULT_MEMORY_MB,
        }

    def get_default_game_folder(self) -> dict:
        return {"ok": True, "path": str(installer.default_directory())}

    def pick_game_folder(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "window not ready"}
        try:
            selection = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not selection:
            return {"ok": False, "cancelled": True}
        return {"ok": True, "path": selection[0]}

    def open_instance_folder(self, version: str) -> dict:
        """Open the selected version's mods/ folder in Explorer.

        Created if it does not exist yet -- opening a path that is not there
        would just fail, and an empty mods/ is exactly what installing
        something into this version would create anyway.
        """
        if not version:
            return {"ok": False, "error": "no version selected"}
        directory = installer.default_directory()
        instance = installer.instance_directory(version, directory)
        mods_path = instance / "mods"
        try:
            mods_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Could not create {mods_path}: {exc}"}
        try:
            os.startfile(str(mods_path))  # noqa: S606 -- opening a folder, Windows-only build
        except OSError as exc:
            return {"ok": False, "error": f"Could not open {mods_path}: {exc}"}
        return {"ok": True, "path": str(mods_path)}

    # -- content: Modrinth search, install, local file import ---------------
    #
    # Same fire-and-forget-then-push shape as the version methods above:
    # search and install are both network calls, so both run on a background
    # thread and report back through window.__maestro.content rather than
    # making the page wait on this call's return value.

    def search_content(self, query: str, project_type: str, version: str) -> dict:
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._search_content_worker,
            args=(query, project_type, version),
            daemon=True,
            name="maestro-content-search",
        ).start()
        return {"ok": True}

    def _search_content_worker(self, query: str, project_type: str, version: str) -> None:
        self._push("content", "onStatus", f'Searching Modrinth for "{query}"...')
        self._status(f'Searching Modrinth for "{query}" ({project_type}, {version})...')
        try:
            results = mods.search_projects(
                query,
                game_version=version or None,
                loader=MOD_LOADER,
                project_type=project_type,
                limit=CONTENT_SEARCH_LIMIT,
            )
        except ModError as exc:
            self._push("content", "onError", str(exc))
            self._failed(f"Search failed: {exc}")
            self._release()
            return
        payload = [
            {
                "projectId": r.project_id,
                "slug": r.slug,
                "title": r.title,
                "description": r.description,
                "author": r.author,
                "projectType": r.project_type,
                "downloads": r.downloads,
                "iconUrl": r.icon_url,
            }
            for r in results
        ]
        self._push("content", "onResults", {"results": payload})
        self._result(f"{len(payload)} result(s) for “{query}”.")
        self._release()

    def install_content(self, project: str, project_type: str, version: str) -> dict:
        if not version:
            return {"ok": False, "error": "no version selected"}
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._install_content_worker,
            args=(project, project_type, version),
            daemon=True,
            name="maestro-content-install",
        ).start()
        return {"ok": True}

    def _install_content_worker(self, project: str, project_type: str, version: str) -> None:
        directory = installer.default_directory()
        instance = installer.instance_directory(version, directory)
        report = self._reporter()
        self._status(f"Installing {project} for {version}...")

        def on_progress(progress: Progress) -> None:
            self._push(
                "content",
                "onInstallProgress",
                {"project": project, "status": progress.status, "percent": progress.percent},
            )
            report(progress)

        try:
            path = mods.install_project(
                project,
                version,
                instance,
                loader=MOD_LOADER,
                project_type=project_type,
                on_progress=on_progress,
            )
        except ModError as exc:
            self._push("content", "onInstallError", {"project": project, "error": str(exc)})
            self._failed(f"Install failed: {exc}")
            self._release()
            return
        self._push(
            "content",
            "onInstallComplete",
            {"project": project, "path": str(path), "folder": path.parent.name},
        )
        self._result(f"{path.name} installed into {path.parent.name}/.")
        self._release()

    def pick_content_files(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "window not ready"}
        try:
            selection = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("Mods and packs (*.jar;*.zip)", "All files (*.*)"),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not selection:
            return {"ok": False, "cancelled": True}
        return {"ok": True, "paths": list(selection)}

    def import_content_files(self, paths: list, version: str) -> dict:
        """Shared by "Add files" (paths from :meth:`pick_content_files`) and
        drag-and-drop (paths from :meth:`on_content_files_dropped`) -- both
        end up with real filesystem paths, so both funnel through here."""
        if not version:
            return {"ok": False, "error": "no version selected"}
        if not paths:
            return {"ok": False, "error": "no files given"}
        if not self._claim():
            return {"ok": False, "error": "Something else is still running."}
        threading.Thread(
            target=self._import_content_worker,
            args=(list(paths), version),
            daemon=True,
            name="maestro-content-import",
        ).start()
        return {"ok": True}

    def _import_content_worker(self, paths: list, version: str) -> None:
        directory = installer.default_directory()
        instance = installer.instance_directory(version, directory)
        report = self._reporter()
        self._status(f"Importing {len(paths)} file(s)...")

        def on_progress(progress: Progress) -> None:
            self._push("content", "onImportProgress", {"status": progress.status, "percent": progress.percent})
            report(progress)

        results = imports.import_files(paths, instance, on_progress=on_progress)
        payload = [
            {
                "source": result.source.name,
                "ok": result.ok,
                "skipped": result.skipped,
                "error": result.error,
                "summary": result.summary,
            }
            for result in results
        ]
        summary = imports.describe(results)
        self._push("content", "onImportComplete", {"results": payload, "summary": summary})
        # A failure in here is per-file and already in the summary, so it goes
        # up as an error that stays rather than a result that clears itself.
        if any(result.error for result in results):
            self._failed(summary)
        else:
            self._result(summary)
        self._release()

    def on_content_files_dropped(self, event: dict) -> None:
        """Registered on #content-dropzone through ``window.dom`` in
        :func:`create_window`, not through the plain js_api bridge every
        other method here uses -- that is the one place a real filesystem
        path is available for a drop rather than just the file's bytes. See
        the module docstring.
        """
        files = ((event or {}).get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            self._push("content", "onFilesDropped", {"paths": paths})

    # -- about ----------------------------------------------------------------

    def get_about_info(self) -> dict:
        return {"ok": True, "appName": WINDOW_TITLE, "version": APP_VERSION}

    def _push(self, channel: str, event: str, payload) -> None:
        """Call ``window.__maestro.<channel>.<event>(payload)`` in the page.

        Silently drops the event if the window is gone or the page has not
        defined the handler yet -- there is nobody left to show it to, and
        this runs on a worker thread with no good way to surface an error
        about failing to report an error.
        """
        if self._window is None:
            return
        script = (
            f"window.__maestro && window.__maestro.{channel} "
            f"&& window.__maestro.{channel}.{event}({json.dumps(payload)})"
        )
        try:
            self._window.evaluate_js(script)
        except Exception:
            pass


def _register_content_dropzone(window: "webview.Window", api: Api) -> None:
    """Give #content-dropzone real filesystem paths on drop.

    window.dom is pywebview's own DOM API, separate from the js_api bridge
    every other method on Api goes through -- see the module docstring for
    why this one interaction needs it. The element does not exist until the
    page has loaded, so this waits for that event rather than running once at
    window-creation time.
    """

    def attach() -> None:
        element = window.dom.get_element("#content-dropzone")
        if element is None:
            return
        element.events.drop += webview.dom.DOMEventHandler(
            api.on_content_files_dropped, prevent_default=True, stop_propagation=True
        )

    window.events.loaded += attach


def create_window() -> "webview.Window":
    """Build the launcher window without starting the event loop.

    Separate from :func:`main` so the window can be created and inspected
    without blocking on ``webview.start()``.
    """
    if not INDEX.is_file():
        raise FileNotFoundError(f"Frontend missing: {INDEX}")

    api = Api()
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
    _register_content_dropzone(window, api)
    return window


def main() -> int:
    create_window()
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
