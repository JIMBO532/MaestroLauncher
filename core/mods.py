"""Modrinth integration for MaestroLauncher.

Search projects, resolve one to a concrete downloadable file, and put that file
on disk. Talks to the Modrinth v2 API over HTTPS and nothing else -- no accounts,
no launching, no GUI, so it stays testable on its own.

API reference: https://docs.modrinth.com/api/

Two quirks of the v2 API that this module papers over:

* In *search*, mod loaders are not their own facet -- they are lumped in with
  ``categories``, so a Fabric filter is ``categories:fabric``. In the *version*
  listing they are a real ``loaders`` parameter. The two are not interchangeable.
* Resource packs, shaders and data packs have no loader in the modding sense;
  Modrinth reports their loader as ``minecraft``. Filtering those by "fabric"
  silently returns nothing, so we drop the loader filter for them instead.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from core import __version__
from core.installer import Progress, ProgressCallback

API_ROOT = "https://api.modrinth.com/v2"

# Modrinth's docs ask every client to identify itself and to include a contact.
# An anonymous or stock python-requests UA is rate limited harder and may be
# refused outright. Add a real contact URL here before this ships publicly.
USER_AGENT = (
    f"MaestroLauncher/{__version__} (custom Minecraft Java launcher; python-requests)"
)

# (connect, read) -- the CDN is usually quick, but a cold file can stall a while.
TIMEOUT = (10.0, 30.0)
CHUNK_SIZE = 1 << 16

# Where a project's file belongs inside the game directory, by project type.
# Anything unrecognised is treated as a mod, which is the common case.
SUBDIRECTORY: dict[str, str] = {
    "mod": "mods",
    "resourcepack": "resourcepacks",
    "shader": "shaderpacks",
    "datapack": "datapacks",
    "modpack": "modpacks",
    "plugin": "plugins",
}

# Project types that have no mod loader; Modrinth files them under "minecraft".
LOADERLESS_TYPES = frozenset({"resourcepack", "shader", "datapack"})

SORT_INDEXES = frozenset({"relevance", "downloads", "follows", "newest", "updated"})

# Lower is better, so a release always beats a beta of the same age.
_STABILITY = {"release": 0, "beta": 1, "alpha": 2}


class ModError(RuntimeError):
    """Anything that stopped a Modrinth search, lookup or download."""


@dataclass(frozen=True)
class SearchResult:
    """One project from a search. Enough to render a row and then resolve it."""

    project_id: str
    slug: str
    title: str
    description: str
    author: str
    project_type: str
    downloads: int
    follows: int
    categories: tuple[str, ...]
    game_versions: tuple[str, ...]
    icon_url: Optional[str]


@dataclass(frozen=True)
class ModFile:
    """A specific downloadable file: one version of one project."""

    project_id: str
    project_type: str
    slug: str
    version_id: str
    version_number: str
    name: str
    filename: str
    url: str
    size: int
    sha1: str
    version_type: str
    date_published: str
    game_versions: tuple[str, ...]
    loaders: tuple[str, ...]

    @property
    def is_stable(self) -> bool:
        return self.version_type == "release"


_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _session = session
    return _session


def _api_get(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    """GET a Modrinth endpoint and return parsed JSON, or raise ModError."""
    url = f"{API_ROOT}{path}"
    try:
        response = _get_session().get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ModError(f"Could not reach Modrinth: {exc}") from exc

    if response.status_code == 404:
        raise ModError(f"Modrinth has no such project or version ({path}).")
    if response.status_code == 429:
        reset = response.headers.get("X-Ratelimit-Reset", "?")
        raise ModError(f"Modrinth rate limit hit. Try again in {reset}s.")
    if not response.ok:
        raise ModError(f"Modrinth returned {response.status_code} for {path}.")

    try:
        return response.json()
    except ValueError as exc:
        raise ModError(f"Modrinth sent a malformed response for {path}.") from exc


def _prepare_directory(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ModError(f"Cannot create directory {path}: {exc}") from exc
    return path


def _safe_filename(name: str) -> str:
    """Strip any directory component from a server-supplied filename.

    The name comes from the API, so it is not ours to trust with a path.
    """
    cleaned = Path(name.replace("\\", "/")).name
    if not cleaned or cleaned in {".", ".."}:
        raise ModError(f"Modrinth returned an unusable filename: {name!r}")
    return cleaned


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def subdirectory_for(project_type: str) -> str:
    """The game-directory subfolder a project of this type installs into."""
    return SUBDIRECTORY.get(project_type, "mods")


def search_projects(
    query: str,
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
    project_type: str = "mod",
    limit: int = 10,
    offset: int = 0,
    index: str = "relevance",
) -> list[SearchResult]:
    """Search Modrinth, optionally narrowed to a game version and loader.

    ``loader`` is ignored for project types that have none (resource packs and
    friends), where sending it would filter every result away.
    """
    if limit < 1 or limit > 100:
        raise ModError("limit must be between 1 and 100.")
    if index not in SORT_INDEXES:
        raise ModError(
            f"Unknown sort index '{index}'. Use one of: {', '.join(sorted(SORT_INDEXES))}."
        )

    # Each inner list is OR'd together; the outer list is AND'd.
    facets: list[list[str]] = []
    if project_type:
        facets.append([f"project_type:{project_type}"])
    if game_version:
        facets.append([f"versions:{game_version}"])
    if loader and project_type not in LOADERLESS_TYPES:
        facets.append([f"categories:{loader}"])

    params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "index": index,
    }
    if facets:
        params["facets"] = json.dumps(facets)

    payload = _api_get("/search", params)
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if hits is None:
        raise ModError("Modrinth search returned no result list.")

    return [
        SearchResult(
            project_id=hit.get("project_id", ""),
            slug=hit.get("slug", ""),
            title=hit.get("title", ""),
            description=hit.get("description", ""),
            author=hit.get("author", ""),
            project_type=hit.get("project_type", ""),
            downloads=int(hit.get("downloads", 0)),
            follows=int(hit.get("follows", 0)),
            categories=tuple(hit.get("categories") or ()),
            game_versions=tuple(hit.get("versions") or ()),
            icon_url=hit.get("icon_url") or None,
        )
        for hit in hits
    ]


def get_project_type(project: str) -> str:
    """The project type ("mod", "resourcepack", ...) for a slug or project ID."""
    payload = _api_get(f"/project/{project}")
    project_type = payload.get("project_type") if isinstance(payload, dict) else None
    if not project_type:
        raise ModError(f"Modrinth did not report a project type for '{project}'.")
    return str(project_type)


def resolve_version(
    project: str,
    game_version: str,
    loader: Optional[str] = None,
    allow_unstable: bool = False,
    project_type: Optional[str] = None,
) -> ModFile:
    """Pick the file to download for a project on a given game version.

    ``project`` is a slug or a project ID. Prefers stable releases over betas and
    newer publish dates over older ones. Pass ``project_type`` when you already
    know it -- a search result carries one -- to save a request.
    """
    resolved_type = project_type or get_project_type(project)

    params: dict[str, Any] = {"game_versions": json.dumps([game_version])}
    if loader and resolved_type not in LOADERLESS_TYPES:
        params["loaders"] = json.dumps([loader])

    payload = _api_get(f"/project/{project}/version", params)
    if not isinstance(payload, list):
        raise ModError(f"Modrinth returned an unexpected version list for '{project}'.")

    # The server filters loosely, so confirm each match ourselves before trusting it.
    compatible = [
        version
        for version in payload
        if game_version in (version.get("game_versions") or ())
        and (
            not loader
            or resolved_type in LOADERLESS_TYPES
            or loader in (version.get("loaders") or ())
        )
    ]
    candidates = [
        version
        for version in compatible
        if allow_unstable or version.get("version_type") == "release"
    ]

    if not candidates:
        wanted = f"Minecraft {game_version}" + (f" + {loader}" if loader else "")
        # Only suggest the flag when a prerelease is genuinely what we filtered out.
        hint = " (only prereleases exist; try allow_unstable=True)" if compatible else ""
        raise ModError(f"'{project}' has no version for {wanted}{hint}.")

    # Two stable sorts: newest first, then stable-channel first wins over it.
    # ISO-8601 with a Z suffix compares correctly as a plain string.
    candidates.sort(key=lambda v: v.get("date_published") or "", reverse=True)
    candidates.sort(key=lambda v: _STABILITY.get(v.get("version_type", ""), 9))
    version = candidates[0]

    files = version.get("files") or []
    chosen = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not chosen or not chosen.get("url"):
        raise ModError(
            f"Version {version.get('version_number')} of '{project}' has no downloadable file."
        )

    return ModFile(
        project_id=version.get("project_id", ""),
        project_type=resolved_type,
        slug=project,
        version_id=version.get("id", ""),
        version_number=version.get("version_number", ""),
        name=version.get("name", ""),
        filename=_safe_filename(chosen.get("filename", "")),
        url=chosen["url"],
        size=int(chosen.get("size") or 0),
        sha1=str((chosen.get("hashes") or {}).get("sha1", "")),
        version_type=version.get("version_type", ""),
        date_published=version.get("date_published", ""),
        game_versions=tuple(version.get("game_versions") or ()),
        loaders=tuple(version.get("loaders") or ()),
    )


def download_file(
    file: ModFile,
    directory: Path | str,
    on_progress: Optional[ProgressCallback] = None,
    overwrite: bool = False,
) -> Path:
    """Download a resolved file into the right subfolder of the game directory.

    Mods land in ``<directory>/mods/``, resource packs in
    ``<directory>/resourcepacks/``. Returns the path to the installed file.
    """
    root = Path(directory).expanduser().resolve()
    target_dir = _prepare_directory(root / subdirectory_for(file.project_type))
    destination = target_dir / file.filename

    def emit(status: str, current: int, total: int) -> None:
        if on_progress:
            on_progress(Progress(status, current, total))

    if destination.exists() and not overwrite:
        if not file.sha1 or _sha1(destination) == file.sha1:
            size = destination.stat().st_size
            emit(f"Already installed: {file.filename}", size, size)
            return destination
        # Present but stale or corrupt -- fall through and fetch it again.

    partial = destination.with_name(destination.name + ".part")
    status = f"Downloading {file.filename}"
    digest = hashlib.sha1()
    written = 0

    try:
        with _get_session().get(file.url, stream=True, timeout=TIMEOUT) as response:
            if not response.ok:
                raise ModError(
                    f"Download failed with HTTP {response.status_code}: {file.url}"
                )

            total = int(response.headers.get("Content-Length") or file.size or 0)
            emit(status, 0, total)

            with partial.open("wb") as handle:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    emit(status, written, total or written)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise ModError(f"Could not download {file.filename}: {exc}") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ModError(f"Failed writing {partial}: {exc}") from exc
    except BaseException:
        # Ctrl-C included: never leave a half-written .part behind.
        partial.unlink(missing_ok=True)
        raise

    if written == 0:
        partial.unlink(missing_ok=True)
        raise ModError(f"{file.filename} downloaded as an empty file.")

    if file.sha1 and digest.hexdigest() != file.sha1:
        partial.unlink(missing_ok=True)
        raise ModError(f"{file.filename} failed its SHA-1 check; the download was corrupt.")

    try:
        partial.replace(destination)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ModError(f"Could not move {file.filename} into {target_dir}: {exc}") from exc

    emit(f"Installed {file.filename}", written, written)
    return destination


def install_project(
    project: str,
    game_version: str,
    directory: Path | str,
    loader: Optional[str] = None,
    allow_unstable: bool = False,
    project_type: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """Resolve a project to a file and download it -- the two steps in one call."""
    file = resolve_version(
        project,
        game_version,
        loader=loader,
        allow_unstable=allow_unstable,
        project_type=project_type,
    )
    return download_file(file, directory, on_progress=on_progress)
