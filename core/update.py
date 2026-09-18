"""Checks GitHub Releases for a build newer than the one running, and can
fetch that release's installer.

Checking never raises. No internet, a rate-limited API, a malformed
response, a repo with no releases yet -- all mean the same thing to the
caller: nothing to report. An update notice is a courtesy, not something
worth a traceback over, and never something worth blocking startup on.

Downloading is real work with a real failure mode, so unlike the check it
raises ``UpdateError`` the normal way -- but it only ever fetches the file.
Nothing here runs it, closes anything, or restarts anything: what happens
with the downloaded installer is the user's decision, made by double-
clicking it themselves, same as the first install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from core import __version__
from core.installer import Progress, ProgressCallback

REPO = "JIMBO532/MaestroLauncher"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
FALLBACK_RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ASSET_NAME = "MaestroLauncherSetup.exe"

# (connect, read) -- kept short since this must never make startup feel slow.
TIMEOUT = (5.0, 10.0)
DOWNLOAD_TIMEOUT = (10.0, 60.0)
CHUNK_SIZE = 1 << 16
USER_AGENT = f"MaestroLauncher/{__version__} (update check)"


class UpdateError(RuntimeError):
    """The installer could not be fetched. The check itself never raises --
    only actually downloading something does."""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    url: str
    # None when the release has no installer asset attached (a draft, or a
    # release someone made by hand without uploading the exe) -- the page
    # link above still works as a fallback for that case.
    download_url: Optional[str]


def _parse_version(text: str) -> tuple[int, ...]:
    """"v0.1.2" -> (0, 1, 2). Text with no version-shaped number in it
    becomes the empty tuple, which never compares as newer than a real one."""
    match = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


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
        assets = payload.get("assets") or []
        download_url = next(
            (
                str(asset["browser_download_url"])
                for asset in assets
                if isinstance(asset, dict) and asset.get("name") == INSTALLER_ASSET_NAME
            ),
            None,
        )
    except (requests.RequestException, ValueError, AttributeError, KeyError):
        return None

    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if not latest or not current or latest <= current:
        return None

    return UpdateInfo(
        current_version=__version__,
        latest_version=tag[1:] if tag[:1] in "vV" else tag,
        url=url,
        download_url=download_url,
    )


def download_installer(
    url: str,
    destination: Path | str,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """Download the installer to ``destination``. Raises ``UpdateError`` on
    any failure; never leaves a partial file at the final name.

    Only ever fetches the bytes -- running it is left entirely to whoever
    called this. ``url`` is not re-validated against ``INSTALLER_ASSET_NAME``
    here; that check belongs to the caller (the GUI restricts it to the URL
    its own update check handed back).
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
                raise UpdateError(f"Download failed with HTTP {response.status_code}: {url}")

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
        raise UpdateError(f"Failed writing {partial}: {exc}") from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(destination)
    return destination
