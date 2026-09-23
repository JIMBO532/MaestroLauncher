"""Checks GitHub Releases for a build newer than the one running, and can
install it in place -- but only when someone presses Update.

Checking never raises. No internet, a rate-limited API, a malformed
response, a repo with no releases yet -- all mean the same thing to the
caller: nothing to report. An update notice is a courtesy, not something
worth a traceback over, and never something worth blocking startup on.

Installing is the opposite: every failure raises ``UpdateError`` with a
message fit to show as-is, because a one-click update that fails quietly
leaves someone thinking they are current when they are not.

The install is: fetch the release's published SHA-256, download the
installer, re-hash the file on disk and refuse to run it unless the two
match, then start it with ``/VERYSILENT``. The installer (see the [Code]
section of MaestroLauncher.iss) waits for this process to exit before it
touches any files, and relaunches the launcher when it finishes -- success
or failure -- so the relaunched copy can say which one it was
(``take_install_outcome``).
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse

import requests

from core import __version__
from core.installer import Progress, ProgressCallback

REPO = "JIMBO532/MaestroLauncher"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
FALLBACK_RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ASSET_NAME = "MaestroLauncherSetup.exe"
CHECKSUM_ASSET_NAME = INSTALLER_ASSET_NAME + ".sha256"

# (connect, read) -- kept short since this must never make startup feel slow.
TIMEOUT = (5.0, 10.0)
DOWNLOAD_TIMEOUT = (10.0, 60.0)
CHUNK_SIZE = 1 << 16
USER_AGENT = f"MaestroLauncher/{__version__} (update check)"

# The installer runs in two stages: the Setup.exe we start, and a setup.tmp
# it unpacks into %TEMP% and runs. Smart App Control can block that second
# stage after a reputation lookup that takes several seconds, by which
# point the first stage has long since "started fine". So the launcher does
# not close until the second stage writes READY_FILE (MaestroLauncher.iss,
# InitializeSetup) -- and gives up, staying open, if that never happens.
READY_TIMEOUT_SECONDS = 60.0
READY_FILE = "installer-ready"
PENDING_MARKER = "pending-install.json"

_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


class UpdateError(RuntimeError):
    """Installing the update failed. The message is written for the user."""


class IntegrityError(UpdateError):
    """The downloaded installer does not match its published checksum."""


class InstallerBlocked(UpdateError):
    """The installer could not be started, or died as soon as it did."""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    url: str
    # Both None unless the release carries the installer *and* its
    # checksum: an installer with nothing to verify it against is never run.
    download_url: Optional[str]
    checksum_url: Optional[str]
    download_size: int = 0

    @property
    def installable(self) -> bool:
        return bool(self.download_url and self.checksum_url)


@dataclass(frozen=True)
class InstallOutcome:
    target_version: str
    succeeded: bool
    log_path: str
    release_url: str


def _parse_version(text: str) -> tuple[int, ...]:
    """"v0.1.2" -> (0, 1, 2). Text with no version-shaped number in it
    becomes the empty tuple, which never compares as newer than a real one."""
    match = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _is_github_https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "github.com"


def check_for_update() -> Optional[UpdateInfo]:
    """The latest release, if it is newer than this build. None otherwise,
    including on any failure -- there is no error case a caller needs to
    handle differently from "nothing to report right now"."""
    try:
        response = requests.get(
            RELEASES_API_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        tag = str(payload.get("tag_name") or "")
        url = str(payload.get("html_url") or "") or FALLBACK_RELEASES_URL
        assets = {
            asset.get("name"): asset
            for asset in payload.get("assets") or []
            if isinstance(asset, dict)
        }
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        return None

    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if not latest or not current or latest <= current:
        return None

    installer = assets.get(INSTALLER_ASSET_NAME) or {}
    checksum = assets.get(CHECKSUM_ASSET_NAME) or {}
    download_url = str(installer.get("browser_download_url") or "")
    checksum_url = str(checksum.get("browser_download_url") or "")
    installable = _is_github_https(download_url) and _is_github_https(checksum_url)
    try:
        size = int(installer.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    return UpdateInfo(
        current_version=__version__,
        latest_version=tag[1:] if tag[:1] in "vV" else tag,
        url=url if _is_github_https(url) else FALLBACK_RELEASES_URL,
        download_url=download_url if installable else None,
        checksum_url=checksum_url if installable else None,
        download_size=size,
    )


def fetch_expected_sha256(url: str) -> str:
    """The hex digest published in the release's ``.sha256`` asset.

    Accepts a bare digest or ``sha256sum`` output (``<digest>  <name>``).
    """
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise UpdateError(f"Could not fetch the update's checksum: {exc}") from exc
    if not response.ok:
        raise UpdateError(f"Could not fetch the update's checksum (HTTP {response.status_code}).")
    match = _SHA256_RE.search(response.text[:4096])
    if not match:
        raise UpdateError("The release's checksum file does not contain a SHA-256 digest.")
    return match.group(1).lower()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_installer(
    url: str,
    destination: Path | str,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """Download the installer to ``destination``. Raises ``UpdateError`` on
    any failure; never leaves a partial file at the final name.

    Downloading verifies nothing -- ``run_installer`` does that, on the
    file as it sits on disk, immediately before running it.
    """
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")

    def emit(current: int, total: int) -> None:
        if on_progress:
            on_progress(Progress("Downloading the update", current, total))

    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        ) as response:
            if not response.ok:
                raise UpdateError(f"Download failed with HTTP {response.status_code}.")

            total = int(response.headers.get("Content-Length") or 0)
            written = 0
            emit(0, total)

            with partial.open("wb") as handle:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    emit(written, total or written)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Could not download the update: {exc}") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Could not save the update: {exc}") from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    try:
        partial.replace(destination)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Could not save the update: {exc}") from exc
    return destination


def _image_path(pid: int) -> Optional[str]:
    """Full exe path of a running process, or None if it cannot be read."""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def launcher_pids() -> list[int]:
    """Every process the installer has to outwait before replacing the exe.

    A PyInstaller one-file build is two processes running the same exe: the
    bootloader, and this interpreter as its child. Both hold the file open.
    """
    pids = [os.getpid()]
    if getattr(sys, "frozen", False):
        parent = os.getppid()
        image = _image_path(parent)
        if image and os.path.normcase(image) == os.path.normcase(sys.executable):
            pids.append(parent)
    return pids


def _blocked_message(exc: OSError) -> str:
    code = getattr(exc, "winerror", None)
    if code is not None and 4550 <= code <= 4580:
        why = "Windows blocked it (Smart App Control or an app control policy)"
    elif code in (225, 226):
        why = "antivirus flagged it"
    elif code == 1260:
        why = "a Windows policy blocked it"
    elif code == 5 or isinstance(exc, PermissionError):
        why = "access was denied -- usually antivirus"
    elif isinstance(exc, FileNotFoundError):
        why = "the downloaded file disappeared -- usually antivirus quarantining it"
    else:
        why = str(exc)
    return f"The update installer could not start: {why}."


def _spawn(args: list[str]) -> subprocess.Popen:
    common = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    detached = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        # Out of any job object we might be in, so closing the launcher
        # cannot take the installer down with it.
        return subprocess.Popen(
            args, creationflags=detached | subprocess.CREATE_BREAKAWAY_FROM_JOB, **common
        )
    except PermissionError:
        # The job forbids breakaway. Retrying without it tells that apart
        # from an antivirus denial, which fails the same way twice.
        return subprocess.Popen(args, creationflags=detached, **common)


def run_installer(
    info: UpdateInfo,
    installer: Path | str,
    expected_sha256: str,
    *,
    workdir: Path | str,
    wait_pids: Sequence[int],
    timeout: float = READY_TIMEOUT_SECONDS,
) -> None:
    """Verify ``installer`` and start it silently.

    Returns only once the installer's second stage reports it is running,
    at which point it is waiting for ``wait_pids`` to exit -- the caller
    should now close. Raises ``IntegrityError`` (file deleted, nothing run)
    on a hash mismatch, and ``InstallerBlocked`` if it could not start,
    exited, or never reported in -- the caller must stay open for both.
    """
    installer = Path(installer)
    workdir = Path(workdir)
    try:
        actual = sha256_file(installer)
    except OSError as exc:
        raise InstallerBlocked(_blocked_message(exc)) from exc
    if not hmac.compare_digest(actual, expected_sha256.lower()):
        installer.unlink(missing_ok=True)
        raise IntegrityError(
            "The downloaded installer does not match the checksum published with "
            "the release, so it was deleted instead of run."
        )

    log_path = workdir / "install.log"
    ready = workdir / READY_FILE
    ready.unlink(missing_ok=True)
    marker = workdir / PENDING_MARKER
    marker.write_text(
        json.dumps(
            {
                "target_version": info.latest_version,
                "log_path": str(log_path),
                "release_url": info.url,
            }
        ),
        encoding="utf-8",
    )

    args = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/LOG={log_path}",
        "/RELAUNCH=1",
        f"/READYFILE={ready}",
    ]
    args += [f"/WAITPID{index}={pid}" for index, pid in enumerate(wait_pids[:2], start=1)]

    try:
        process = _spawn(args)
    except OSError as exc:
        marker.unlink(missing_ok=True)
        raise InstallerBlocked(_blocked_message(exc)) from exc

    deadline = time.monotonic() + timeout
    while not ready.exists():
        code = process.poll()
        if code is not None:
            marker.unlink(missing_ok=True)
            raise InstallerBlocked(
                f"Windows stopped the update installer before it could run (exit code {code}). "
                "Smart App Control or antivirus most likely blocked it."
            )
        if time.monotonic() >= deadline:
            # Stuck -- typically the first stage sitting on an error box
            # after its second stage was blocked. It is ours and it failed.
            try:
                process.kill()
            except OSError:
                pass
            marker.unlink(missing_ok=True)
            raise InstallerBlocked(
                f"The update installer did not get going within {timeout:.0f} seconds, so it "
                "was stopped. Smart App Control or antivirus most likely blocked it."
            )
        time.sleep(0.1)
    ready.unlink(missing_ok=True)


def take_install_outcome(workdir: Path | str) -> Optional[InstallOutcome]:
    """What happened to the install started before the last restart, if any.

    Reads and removes the marker ``run_installer`` left, so each outcome is
    reported exactly once.
    """
    marker = Path(workdir) / PENDING_MARKER
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        marker.unlink(missing_ok=True)
    if not isinstance(data, dict):
        return None
    target = str(data.get("target_version") or "")
    release_url = str(data.get("release_url") or "")
    return InstallOutcome(
        target_version=target,
        succeeded=bool(_parse_version(target)) and _parse_version(__version__) >= _parse_version(target),
        log_path=str(data.get("log_path") or ""),
        release_url=release_url if _is_github_https(release_url) else FALLBACK_RELEASES_URL,
    )
