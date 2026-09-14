"""Checks GitHub Releases for a build newer than the one running.

Nothing here ever raises. No internet, a rate-limited API, a malformed
response, a repo with no releases yet -- all mean the same thing to the
caller: nothing to report. An update notice is a courtesy, not something
worth a traceback over, and never something worth blocking startup on.

Notice-and-link only, on purpose: this tells the user a newer build exists
and hands them the release page. It does not download or run anything --
that stays a decision the user makes for themselves, on the page, same as
grabbing the installer for the first time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

from core import __version__

REPO = "JIMBO532/MaestroLauncher"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
FALLBACK_RELEASES_URL = f"https://github.com/{REPO}/releases/latest"

# (connect, read) -- kept short since this must never make startup feel slow.
TIMEOUT = (5.0, 10.0)
USER_AGENT = f"MaestroLauncher/{__version__} (update check)"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    url: str


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
    except (requests.RequestException, ValueError, AttributeError):
        return None

    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if not latest or not current or latest <= current:
        return None

    return UpdateInfo(
        current_version=__version__,
        latest_version=tag[1:] if tag[:1] in "vV" else tag,
        url=url,
    )
