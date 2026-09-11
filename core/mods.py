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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import requests

from core import __version__
from core.installer import Progress, ProgressCallback

API_ROOT = "https://api.modrinth.com/v2"

# Collections exist only on v3, which Modrinth still calls experimental. Every
# other call in this module stays on v2.
API_ROOT_V3 = "https://api.modrinth.com/v3"

# "Optimized Minecraft" -- the collection behind the launcher's one-click
# optimization button. Fetched live, so editing the collection on Modrinth
# changes what the button installs without a code change.
OPTIMIZATION_COLLECTION = "MzYTXwDl"

# Collections are mod lists, and this launcher is Fabric-only for now.
MOD_LOADER_DEFAULT = "fabric"

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


def _api_get(
    path: str,
    params: Optional[dict[str, Any]] = None,
    api_root: str = API_ROOT,
) -> Any:
    """GET a Modrinth endpoint and return parsed JSON, or raise ModError."""
    url = f"{api_root}{path}"
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
    prefer_newest: bool = False,
) -> ModFile:
    """Pick the file to download for a project on a given game version.

    ``project`` is a slug or a project ID. Prefers stable releases over betas and
    newer publish dates over older ones. Pass ``project_type`` when you already
    know it -- a search result carries one -- to save a request.

    ``prefer_newest`` drops the preference for the stable channel and takes the
    most recently published compatible build whatever it is labelled, which
    implies ``allow_unstable``. Mods that track a new Minecraft release often sit
    on beta for months while the stable build stays pinned to an older game
    version, so "newest" and "stable" genuinely disagree; this picks newest.
    """
    resolved_type = project_type or get_project_type(project)
    allow_unstable = allow_unstable or prefer_newest

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
    # ISO-8601 with a Z suffix compares correctly as a plain string. With
    # prefer_newest the second sort is skipped, so publish date decides alone.
    candidates.sort(key=lambda v: v.get("date_published") or "", reverse=True)
    if not prefer_newest:
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


@dataclass(frozen=True)
class Collection:
    """A Modrinth collection: a named, ordered bag of projects."""

    id: str
    name: str
    description: str
    project_ids: tuple[str, ...]


@dataclass(frozen=True)
class CollectionEntry:
    """What happened to one project when a collection was installed."""

    project_id: str
    title: str
    path: Optional[Path] = None
    filename: str = ""
    version_number: str = ""
    stable: bool = True
    error: str = ""

    @property
    def installed(self) -> bool:
        return self.path is not None


def fetch_collection(collection: str) -> Collection:
    """Look up a Modrinth collection by its ID.

    Collections live only on the v3 API, which Modrinth still labels
    experimental, so this is the one call here that does not go through v2. A
    shape change there surfaces as ``ModError`` like any other failure.
    """
    payload = _api_get(f"/collection/{collection}", api_root=API_ROOT_V3)
    if not isinstance(payload, dict):
        raise ModError(f"Modrinth returned an unexpected collection '{collection}'.")

    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise ModError(f"Modrinth collection '{collection}' listed no projects.")

    return Collection(
        id=str(payload.get("id", collection)),
        name=str(payload.get("name", collection)),
        description=str(payload.get("description", "")),
        project_ids=tuple(str(p) for p in projects),
    )


def project_titles(project_ids: Sequence[str]) -> dict[str, str]:
    """Human-readable names for a batch of project IDs, in one request.

    Used so a collection install can name what it is doing rather than reciting
    IDs. A project that cannot be looked up simply keeps its ID as its name.
    """
    if not project_ids:
        return {}

    payload = _api_get("/projects", {"ids": json.dumps(list(project_ids))})
    if not isinstance(payload, list):
        return {}

    titles: dict[str, str] = {}
    for project in payload:
        if not isinstance(project, dict):
            continue
        identifier = project.get("id")
        if identifier:
            titles[str(identifier)] = str(project.get("title") or identifier)
    return titles


@dataclass(frozen=True)
class FabricMod:
    """What a jar says about itself in its own ``fabric.mod.json``.

    This is the file Fabric reads at startup, so it is the only description of a
    mod that actually decides whether the game will boot. Modrinth's API is a
    catalogue on top of it and does not always agree: Sodium's jar has declared
    VulkanMod incompatible for years while Modrinth lists no dependencies for it
    at all. Anything that must match what the loader will do is read from here.
    """

    mod_id: str
    version: str
    minecraft: str
    breaks: dict[str, str]
    filename: str


def read_fabric_metadata(jar: Path | str) -> Optional[FabricMod]:
    """Read a mod jar's own metadata, or None if it has none we understand."""
    path = Path(jar)
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("fabric.mod.json").decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return None

    try:
        # Some mods ship a fabric.mod.json with trailing commas or comments;
        # those are not worth a parser, they are worth not crashing over.
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    depends = data.get("depends")
    depends = depends if isinstance(depends, dict) else {}
    declared_breaks: dict[str, str] = {}
    for key in ("breaks", "conflicts"):
        section = data.get(key)
        if isinstance(section, dict):
            for name, constraint in section.items():
                declared_breaks[str(name)] = str(constraint)

    return FabricMod(
        mod_id=str(data.get("id", "")),
        version=str(data.get("version", "")),
        minecraft=str(depends.get("minecraft", "")),
        breaks=declared_breaks,
        filename=path.name,
    )


def _is_exact_version(constraint: str) -> bool:
    """True when a Fabric dependency string names one version and nothing else.

    Ranges need a real predicate parser and are left to Modrinth's own
    compatibility tags. A bare literal like ``"1.21.11"`` needs no parser and is
    the case that actually bites -- VulkanMod pins exactly one game version, so a
    build for the wrong one is a guaranteed startup failure rather than a risk.
    """
    return bool(constraint) and not any(
        character in constraint for character in "<>=~^*| ,"
    )


def conflicts_between(metadata: Sequence[FabricMod]) -> list[tuple[str, str, str]]:
    """Find pairs that declare each other incompatible.

    Returns ``(mod_id, blocked_id, constraint)`` for every declared break where
    the blocked mod is actually present. Only ``"*"`` -- meaning every version --
    is treated as certain; a version-ranged break is reported by the caller as a
    possibility rather than acted on, because deciding it needs the version
    predicate parser this deliberately does not have.
    """
    present = {meta.mod_id: meta for meta in metadata if meta.mod_id}
    found: list[tuple[str, str, str]] = []
    for meta in metadata:
        for blocked_id, constraint in meta.breaks.items():
            if blocked_id in present:
                found.append((meta.mod_id, blocked_id, constraint))
    return found


def _install_projects(
    project_ids: Sequence[str],
    game_version: str,
    directory: Path | str,
    loader: Optional[str] = MOD_LOADER_DEFAULT,
    allow_unstable: bool = True,
    prefer_newest: bool = True,
    on_progress: Optional[ProgressCallback] = None,
) -> list[CollectionEntry]:
    """Install a list of projects into one directory under the pack's rules.

    Shared by the pack install and by catching up on mods that were skipped
    earlier, so a mod arriving late goes through exactly the same checks: the
    jar's own game-version pin, and the conflicts the jars declare.
    """
    wanted = list(project_ids)
    titles = project_titles(wanted)

    total = len(wanted)
    results: list[CollectionEntry] = []
    staged: list[tuple[int, FabricMod]] = []

    for index, project_id in enumerate(wanted):
        title = titles.get(project_id, project_id)

        if on_progress:
            on_progress(Progress(f"Installing {title}", index, total))

        file = None
        for unstable in ((False, True) if not prefer_newest else (True,)):
            try:
                file = resolve_version(
                    project_id,
                    game_version,
                    loader=loader,
                    allow_unstable=unstable or allow_unstable,
                    project_type="mod",
                    prefer_newest=prefer_newest,
                )
                break
            except ModError as exc:
                last_error = exc

        if file is None:
            results.append(
                CollectionEntry(
                    project_id=project_id,
                    title=title,
                    error=f"no build for Minecraft {game_version}",
                )
            )
            continue

        try:
            path = download_file(file, directory)
        except ModError as exc:
            results.append(
                CollectionEntry(project_id=project_id, title=title, error=str(exc))
            )
            continue

        entry = CollectionEntry(
            project_id=project_id,
            title=title,
            path=path,
            filename=file.filename,
            version_number=file.version_number,
            stable=file.is_stable,
        )

        # The jar's own pin beats Modrinth's tag when the two disagree, because
        # the jar's is the one Fabric enforces.
        meta = read_fabric_metadata(path)
        if meta and _is_exact_version(meta.minecraft) and meta.minecraft != game_version:
            _discard(path)
            results.append(
                CollectionEntry(
                    project_id=project_id,
                    title=title,
                    error=(
                        f"built for Minecraft {meta.minecraft}, not {game_version}"
                    ),
                )
            )
            continue

        results.append(entry)
        if meta:
            staged.append((len(results) - 1, meta))

    # Now that everything is on disk, let the mods themselves say what cannot sit
    # beside what. Whichever of a conflicting pair came later is the one dropped,
    # so the collection's own order decides and the result is reproducible.
    kept: dict[str, int] = {}
    order = {position: rank for rank, (position, _) in enumerate(staged)}
    metas = [meta for _, meta in staged]
    for blocker_id, blocked_id, constraint in conflicts_between(metas):
        if constraint != "*":
            # A ranged break needs a version predicate parser to settle. Left
            # alone rather than guessed at; the caller surfaces it as a warning.
            continue
        positions = {meta.mod_id: position for position, meta in staged}
        blocker_pos, blocked_pos = positions.get(blocker_id), positions.get(blocked_id)
        if blocker_pos is None or blocked_pos is None:
            continue
        loser_pos = max(blocker_pos, blocked_pos)
        winner_pos = min(blocker_pos, blocked_pos)
        loser = results[loser_pos]
        if not loser.installed:
            continue
        _discard(loser.path)
        results[loser_pos] = CollectionEntry(
            project_id=loser.project_id,
            title=loser.title,
            error=(
                f"conflicts with {results[winner_pos].title} -- they are mutually "
                "exclusive and only one can be installed"
            ),
        )
        staged = [(p, m) for p, m in staged if p != loser_pos]

    if on_progress:
        on_progress(Progress("Finished", total, total))

    return results




def install_collection(
    collection: str,
    game_version: str,
    directory: Path | str,
    loader: Optional[str] = MOD_LOADER_DEFAULT,
    allow_unstable: bool = True,
    prefer_newest: bool = True,
    extra_projects: Sequence[str] = (),
    on_progress: Optional[ProgressCallback] = None,
) -> list[CollectionEntry]:
    """Install a collection into one game directory, and report on every project.

    Three rules, each learned from a launch that failed:

    * **A mod with no build for this exact Minecraft version is skipped, never
      approximated.** Modrinth's per-version ``game_versions`` decides, not the
      filename. A jar that additionally pins one exact game version in its own
      ``fabric.mod.json`` is checked against that too and dropped if it
      disagrees, because that pin is what Fabric will enforce at startup.
    * **Mods that declare each other incompatible are never both kept.** The
      declaration is read from the jars, since Modrinth's dependency list does
      not carry it -- Sodium has broken VulkanMod for years with nothing on
      Modrinth to say so.
    * **``directory`` is expected to be per-version.** Builds for two Minecraft
      versions in one mods folder make Fabric refuse to start, so callers pass an
      isolated instance directory rather than a shared ``.minecraft``.

    ``extra_projects`` are installed after the collection and take part in the
    same checks, which is how an alternative renderer gets offered without
    risking it landing beside one it conflicts with.

    Whatever could not be installed is written to the instance's skip list, so a
    later session can re-check whether a build has appeared since.
    """
    found = fetch_collection(collection)
    wanted = list(found.project_ids) + [
        p for p in extra_projects if p not in found.project_ids
    ]
    results = _install_projects(
        wanted, game_version, directory,
        loader=loader, allow_unstable=allow_unstable,
        prefer_newest=prefer_newest, on_progress=on_progress,
    )
    record_skipped(directory, results)
    return results

def _discard(path: Optional[Path]) -> None:
    """Remove a jar we decided not to keep. Failing to is not worth raising over."""
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def ranged_conflict_warnings(directory: Path | str) -> list[str]:
    """Possible conflicts in a mods folder that need a version range to settle.

    Separate from the certain ones because these are not acted on. A mod saying
    it breaks *some* versions of another is common and usually already satisfied;
    reporting it is useful, silently deleting on a guess is not.
    """
    folder = Path(directory).expanduser() / SUBDIRECTORY["mod"]
    try:
        jars = sorted(folder.glob("*.jar"))
    except OSError:
        return []

    metas = [meta for meta in (read_fabric_metadata(jar) for jar in jars) if meta]
    by_id = {meta.mod_id: meta for meta in metas}

    warnings: list[str] = []
    for blocker, blocked, constraint in conflicts_between(metas):
        if constraint == "*":
            continue
        other = by_id.get(blocked)
        warnings.append(
            f"{blocker} declares it breaks {blocked} {constraint}"
            + (f" (you have {other.version})" if other else "")
        )
    return warnings

# Where an instance remembers what could not be installed for it.
SKIPPED_FILENAME = "maestro-skipped.json"


@dataclass(frozen=True)
class SkippedMod:
    """A project that had no usable build when the pack was installed."""

    project_id: str
    title: str
    reason: str


def skipped_path(directory: Path | str) -> Path:
    """Where the skip list for an instance directory lives."""
    return Path(directory).expanduser() / SKIPPED_FILENAME


def record_skipped(directory: Path | str, entries: Sequence[CollectionEntry]) -> Path:
    """Remember which projects were skipped, so they can be retried later.

    Written even when nothing was skipped, because an empty list is the
    difference between "nothing to catch up on" and "never installed here".
    """
    path = skipped_path(directory)
    payload = [
        {"project_id": entry.project_id, "title": entry.title, "reason": entry.error}
        for entry in entries
        if not entry.installed
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ModError(f"Could not record skipped mods in {path}: {exc}") from exc
    return path


def load_skipped(directory: Path | str) -> list[SkippedMod]:
    """Read back what was skipped. Missing or unreadable means nothing known."""
    try:
        payload = json.loads(skipped_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []

    skipped: list[SkippedMod] = []
    for item in payload:
        if isinstance(item, dict) and item.get("project_id"):
            skipped.append(
                SkippedMod(
                    project_id=str(item["project_id"]),
                    title=str(item.get("title") or item["project_id"]),
                    reason=str(item.get("reason") or ""),
                )
            )
    return skipped


def recheck_skipped(
    directory: Path | str,
    game_version: str,
    loader: Optional[str] = MOD_LOADER_DEFAULT,
    prefer_newest: bool = True,
) -> list[SkippedMod]:
    """Which previously skipped projects now have a build for this version.

    Asks Modrinth again for each one. A mod with no build for a brand-new
    Minecraft version usually gets one within weeks, and nothing else would ever
    notice -- the pack install already happened and will not run again by itself.

    Returns only the ones that would now install. Nothing is downloaded here;
    deciding to install is the caller's, and the caller is expected to ask first.
    """
    available: list[SkippedMod] = []
    for entry in load_skipped(directory):
        try:
            resolve_version(
                entry.project_id,
                game_version,
                loader=loader,
                allow_unstable=True,
                project_type="mod",
                prefer_newest=prefer_newest,
            )
        except ModError:
            continue
        available.append(entry)
    return available


def install_skipped(
    directory: Path | str,
    game_version: str,
    projects: Sequence[str],
    loader: Optional[str] = MOD_LOADER_DEFAULT,
    on_progress: Optional[ProgressCallback] = None,
) -> list[CollectionEntry]:
    """Install specific projects into an instance and refresh its skip list.

    Goes through the same checks as a pack install -- the jar's own game-version
    pin and its declared conflicts -- because a mod arriving late is no more
    trustworthy than one that arrived on time.
    """
    results = _install_projects(
        list(projects), game_version, directory, loader=loader,
        prefer_newest=True, on_progress=on_progress,
    )

    # Anything still not installable stays on the list, and anything that made it
    # comes off; otherwise the same mod is offered every session forever.
    remaining = [item for item in load_skipped(directory)]
    installed_ids = {entry.project_id for entry in results if entry.installed}
    still_skipped = [item for item in remaining if item.project_id not in installed_ids]
    for entry in results:
        if not entry.installed and entry.project_id not in {s.project_id for s in still_skipped}:
            still_skipped.append(
                SkippedMod(entry.project_id, entry.title, entry.error)
            )

    path = skipped_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {"project_id": s.project_id, "title": s.title, "reason": s.reason}
                    for s in still_skipped
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    return results
