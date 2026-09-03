# MaestroLauncher v1 — Interface Contract and Design Plan

Frozen 2026-09-03. This document is the single source of truth every module is
implemented against. Later tasks reference it **by section number**; the numbering
below is fixed. Each section is self-contained: an implementer reads their section
plus `PLAN_1.md` and writes the module without guessing names, signatures, field
types, exceptions or file formats.

Conventions used throughout:

- Signatures are exact. Type hints are Python 3.12 syntax (`X | None`, `list[str]`).
  Keyword-only parameters after `*` are keyword-only in the implementation too.
- `Raises:` lists name classes from `errors.py` (section 2). Where a low-level helper
  deliberately lets stdlib exceptions through, the list says so explicitly.
- "Long operation" means any function that downloads, extracts, hashes many files or
  polls. Every long operation takes `progress: ProgressFn` and `cancel: CancelToken`
  (section 6) and checks `cancel.raise_if_cancelled()` at least once per file/chunk.
- Nothing in this document is an implementation body. Where behaviour is described
  in prose, that prose is normative.
- `Paths`, `Http`, `Config` are injected as parameters (ruling 3). No module-level
  singletons except `logsetup.REDACTOR` (logging is process-global by nature).

---

## 0. Amendments

Rows are appended by later tasks when they must deviate from a section. Never
edit a section silently; add a row here in the same commit and then change the
section.

| Date | Section | Amendment | Reason |
|---|---|---|---|
| 2026-09-03 | 1 | `core` and `ui` are **packages** (`core/*.py`, `ui/*.py`), not the single files `core.py`/`ui.py` listed in spec §0. `import core` / `import ui` still work through `core/__init__.py` and `ui/__init__.py`. Spec §0's chat delivery protocol (Responses 1–7) is replaced by the 17-task plan. | Controller ruling 1: ~2,000-line files are unreviewable. |
| 2026-09-03 | 15, 18, 19 | The Mojang version JSON `logging` block (`-Dlog4j.configurationFile=${path}`) is **not** passed to the JVM. | Controller ruling 4 / api-facts DECISION: that config makes the game emit XML log events which the plain-text log reader (spec §8) would render as XML soup. The game's bundled plain-text log4j config is used instead. |
| 2026-09-03 | 3, 19 | The launcher's stdout/stderr capture is written to `instances/{name}/logs/launcher-stdout.log`, not `logs/latest.log` as spec §8 says. `InstancePaths.latest_log` still names `logs/latest.log` (the game's own file, read-only for us). | Minecraft's bundled log4j config already writes `logs/latest.log` relative to the game directory, which is the instance directory. Two writers on one file corrupt it and break the game's log rotation on Windows. |
| 2026-09-03 | 8, 10, 22 | There is no constant default client ID for `auth_mode = "entra"` (spec §4.1 "constant fallback"): `ENTRA_DEFAULT_CLIENT_ID = ""`. An empty effective client ID is a `ConfigError`; the Account screen explains it and offers a one-click switch to `"live"`. | A valid Entra client ID only exists once the user registers their own app (Path A). Inventing or borrowing one is not possible. The `"live"` mode has the real constant `00000000402b5328`. |
| 2026-09-03 | 16, 22 | "One-click Install" (spec §12) and "show the full list of what will be installed before downloading" (spec §9) are reconciled: clicking Install resolves the plan in a task; when the plan contains only the requested mod it installs immediately; when it contains dependencies a confirm dialog lists every file first. | Both requirements are honoured; a confirm for a single file would be noise. |
| 2026-09-03 | 21 | `theme.py` defines seven colour constants: the six the spec allows plus `ACCENT_HOVER`, a darker shade of `ACCENT` with the same hue. `TEXT_ON_ACCENT` is an alias of `SURFACE`, not an eighth value. | `CTkButton` needs a distinct `hover_color`; a shade of the accent is a state, not a new colour. |
| 2026-09-03 | 22 | The running-game button reads **"Stop"** with a separate status label "Running", instead of a single button captioned "Running — Stop" (spec §8). | Spec §13: buttons name what happens; "Running" is a state, not an action. |
| 2026-09-03 | 15 | Versions whose JSON has no `arguments` block (pre-1.13, `minecraftArguments` string) are launched with `LEGACY_JVM_ARGS` plus the split `minecraftArguments`. Fabric does not exist for them, so `prepare_launch` stops with `ManifestError` ("Fabric doesn't support Minecraft {version}. Pick 1.14 or newer."). | The dropdown lists every release (spec §2); the launcher must fail clearly rather than crash on them. |

---

## 1. Module map

Import direction: a module may import only modules **above** it in this list
(and the stdlib / third-party packages). `core/__init__.py` re-exports the public
names of every `core` submodule. Nothing under `core/`, nor `auth.py`, nor
`process.py`, imports `tkinter`, `customtkinter`, `theme` or `ui`.

| # | Module | Responsibility (one line) | May import |
|---|---|---|---|
| 1 | `errors.py` | Exception hierarchy rooted at `LauncherError`; XErr message table. | stdlib |
| 2 | `paths.py` | `Paths`/`InstancePaths`, platform default root, atomic writes, hashing, chmod. | errors |
| 3 | `messages.py` | Frozen dataclasses put on the UI queue; task-id constants. | errors, paths |
| 4 | `logsetup.py` | Redactor, redacting filter, rotating file log. | ← above |
| 5 | `core/progress.py` | `ProgressFn`, `CancelToken`, `Reporter`, `format_bytes`. | ← above |
| 6 | `core/net.py` | `Http` wrapper: timeouts, retry, JSON, atomic verified downloads. | ← above |
| 7 | `core/config.py` | `config.json` schema, `Config`, load/save, memory cap, RAM probe. | ← above |
| 8 | `core/versions.py` | Mojang manifest and version JSON (cached, manifest-order comparisons). | ← above |
| 9 | `auth.py` | Microsoft device code (Entra/Live) → XBL → XSTS → Mojang → profile; account store. | ← above |
| 10 | `core/runtime.py` | Adoptium JRE query, atomic install, validity check. | ← above |
| 11 | `core/libraries.py` | Rules, Maven paths, library selection/download, client jar, natives, classpath. | ← above |
| 12 | `core/fabric.py` | Fabric meta, profile merge, `compare_versions` (libraries only). | ← above |
| 13 | `core/assets.py` | Asset index, parallel object download, virtual/map_to_resources. | ← above |
| 14 | `core/launch.py` | Argument evaluation, variable substitution, `LaunchPlan`. | ← above |
| 15 | `core/modrinth.py` | Modrinth client, dependency resolution, install, installed-mod management. | ← above |
| 16 | `core/instances.py` | Instances on disk, bundled mods (Fabric API + Sodium). | ← above |
| 17 | `core/pipeline.py` | `prepare_launch`: the ordered, weighted steps that produce a `LaunchPlan`. | ← above |
| 18 | `process.py` | `GameProcess`: spawn, log reader, supervisor, crash hints. | ← above |
| 19 | `tasks.py` | `TaskRunner`: thread pool → queue bridge with catch-everything callbacks. | ← above |
| 20 | `theme.py` | Design tokens, font resolution, `apply_theme()`. | ← above, customtkinter |
| 21 | `ui/widgets.py` | Focus ring, buttons, sidebar, empty state, banner, code label, icon cache, dialogs. | ← above |
| 22 | `ui/app.py`, `ui/account.py`, `ui/play.py`, `ui/mods.py` | `MaestroApp` and the three screens. Screens import each other **not at all**; `app.py` imports the screens. | ← above |
| 23 | `main.py` | Entry point: dependency check, `--home`, logging, config, bootstrap, mainloop. | everything |

Packages: `core/__init__.py` (re-exports), `ui/__init__.py` (exports `MaestroApp`).
Tests live in `tests/` with `tests/conftest.py` (section 24). Project files:
`requirements.txt` (section 25), `pytest.ini` (section 24), `README.md` (a later task).

Threading model in one paragraph: worker code (everything in rows 1–19) never
touches a widget, a `StringVar` or a `CTkImage`. Workers report through
`ProgressFn` callbacks and return values; `tasks.py` converts those into
`messages.py` dataclasses on one `queue.Queue`; `ui/app.py` drains that queue
every 50 ms on the Tk thread and is the only code that mutates widgets.

---

## 2. `errors.py`

```python
from typing import ClassVar

class LauncherError(Exception):
    """Root of every launcher error; `user_message` is shown, `technical` is logged."""
    default_user_message: ClassVar[str] = "Something went wrong. Check launcher.log for details."
    user_message: str
    technical: str
    def __init__(self, technical: str = "", *, user_message: str | None = None) -> None:
        """technical: for the log. user_message: for the dialog; defaults to the class default."""
    def __str__(self) -> str:
        """Returns `technical` if non-empty, else `user_message`."""
```

Subclasses. Every class keeps the base constructor unless a different one is
listed. `default_user_message` values are the exact interface copy.

| Class | Base | Extra fields / constructor | `default_user_message` |
|---|---|---|---|
| `ConfigError` | `LauncherError` | — | "The launcher settings couldn't be read or written. Check that the MaestroLauncher folder is writable." |
| `NetworkError` | `LauncherError` | — | "Couldn't reach the server. Check your connection and try again." |
| `HttpStatusError` | `NetworkError` | `status: int`, `body: str`, `url: str`. `__init__(self, status: int, body: str, url: str, *, user_message: str \| None = None)`; `technical` = `f"HTTP {status} from {url}: {body[:500]}"`. `body` is always the decoded response text (may be `""`), never `None`. | "The server answered with an error (HTTP {status}). Try again in a moment." (formatted with the status) |
| `ChecksumError` | `LauncherError` | `path: str`, `expected: str`, `actual: str`, `algorithm: str`. `__init__(self, path, expected, actual, algorithm="sha1")` | "A downloaded file was corrupted in transit. Try again; the launcher will re-download it." |
| `CancelledError` | `LauncherError` | `__init__(self, technical: str = "cancelled")` | "Cancelled." |
| `RuntimeProvisionError` | `LauncherError` | — | "Couldn't install the Java runtime the game needs. Try again; if it keeps failing, delete the runtimes folder." |
| `ManifestError` | `LauncherError` | — | "The version information from Mojang is missing or malformed. Try again in a moment." |
| `UnresolvedPlaceholderError` | `LauncherError` | `placeholders: tuple[str, ...]`. `__init__(self, placeholders: tuple[str, ...])` | "The game command line couldn't be built (unresolved placeholders). This is a launcher bug; check launcher.log." |
| `AuthError` | `LauncherError` | — | "Microsoft sign-in failed. Try signing in again." |
| `AuthPendingError` | `AuthError` | — (raised only internally when a caller wants an exception rather than `None` for a pending poll) | "Waiting for you to finish signing in." |
| `AuthSlowDownError` | `AuthError` | `interval: int` (the new interval, old + 5) `__init__(self, interval: int)` | "Microsoft asked the launcher to poll more slowly. Still waiting for you to sign in." |
| `AuthExpiredError` | `AuthError` | — | "The sign-in code expired before it was used. Start sign-in again to get a new code." |
| `AuthDeclinedError` | `AuthError` | — | "Sign-in was declined in the browser. Start again when you're ready." |
| `XboxAccountError` | `AuthError` | `xerr: int`, `redirect: str`. `__init__(self, xerr: int, redirect: str = "", technical: str = "")`; `user_message` = `XERR_MESSAGES[xerr]` if present, else `XERR_FALLBACK` formatted. | (from `XERR_MESSAGES`) |
| `NoJavaEditionError` | `AuthError` | `__init__(self, technical: str = "profile 404")` | "This Microsoft account doesn't own Minecraft: Java Edition. If you play through Game Pass, open the official Minecraft Launcher once with this account, then try again." |
| `TokenExpiredError` | `AuthError` | — | "Your sign-in has expired. Sign in again." |
| `ModrinthError` | `LauncherError` | — | "Couldn't reach Modrinth. Check your connection and try again." |
| `RateLimitedError` | `ModrinthError` | `retry_after: float` (seconds) `__init__(self, retry_after: float, technical: str = "")` | "Modrinth is rate-limiting the launcher. Wait a minute and try again." |
| `DependencyResolutionError` | `ModrinthError` | `project_id: str`, `game_version: str`. `__init__(self, project_id: str, game_version: str, technical: str = "")` | "One of the mods this needs isn't available for Minecraft {game_version}. Nothing was installed." |
| `NoCompatibleVersionError` | `ModrinthError` | `project: str` (slug or id), `game_version: str`. `__init__(self, project: str, game_version: str)` | "{project} isn't available for Minecraft {game_version} yet." |
| `InstanceError` | `LauncherError` | — | "That instance couldn't be created or changed. Check the name and try again." |
| `LaunchError` | `LauncherError` | — | "The game couldn't be started. Check launcher.log for the command that failed." |

Module constants:

```python
XERR_MESSAGES: dict[int, str] = {
    2148916233: "This Microsoft account has no Xbox profile yet. Sign in once at xbox.com to create one, then try again.",
    2148916235: "Xbox Live isn't available in this account's country, so it can't be used to sign in to Minecraft.",
    2148916236: "This account needs adult verification before it can use Xbox Live. Complete verification at xbox.com, then try again.",
    2148916237: "This account needs adult verification before it can use Xbox Live. Complete verification at xbox.com, then try again.",
    2148916238: "This account is a child account. Add it to a Microsoft Family group with an adult, then try again.",
}
XERR_FALLBACK = "Xbox sign-in was refused (XErr {xerr}). Details: {redirect}"   # redirect may be ""
```

The 404 profile explanation above (`NoJavaEditionError`) is the spec §4.2 step 5
text: the account does not own Minecraft: Java Edition, or is a Game Pass account
that has never opened the official launcher. It is **not** an authentication
failure and is never collapsed into `AuthError` handling.

Rule for every module: raise these classes, never bare `Exception`, for any
failure a user can see. Wrap stdlib errors (`OSError`, `json.JSONDecodeError`,
`zipfile.BadZipFile`, …) at the boundary where the user-facing meaning is known.

---

## 3. `paths.py`

Every path in the launcher comes from a `Paths` or `InstancePaths` instance passed
as a parameter. No module builds a path from `os.environ` or `Path.home()` itself.

Module constants:

```python
APP_NAME: Final[str] = "MaestroLauncher"          # Windows / macOS directory name
APP_DIR_POSIX: Final[str] = "maestrolauncher"     # Linux directory name (XDG data dir)
LAUNCHER_NAME: Final[str] = "MaestroLauncher"     # ${launcher_name} and the HTTP User-Agent
LAUNCHER_VERSION: Final[str] = "1.0"              # ${launcher_version}
HASH_CHUNK_SIZE: Final[int] = 1024 * 1024         # 1 MiB, used by every *_file hasher
MANIFEST_CACHE_NAME: Final[str] = "version_manifest_v2.json"
```

### 3.1 `Paths`

```python
@dataclass(frozen=True, slots=True)
class Paths:
    """Every launcher-owned directory and file, derived from one root."""
    root: Path
    config_json: Path
    accounts_json: Path
    launcher_log: Path
    runtimes: Path
    libraries: Path
    assets: Path
    assets_indexes: Path
    assets_objects: Path
    assets_virtual: Path
    versions: Path
    instances: Path
```

All twelve fields are required and are set by `for_root`; construct a `Paths`
only through `Paths.for_root()` or `Paths.default()`. Derivation from `root`:

| Field | Value |
|---|---|
| `config_json` | `root / "config.json"` |
| `accounts_json` | `root / "accounts.json"` |
| `launcher_log` | `root / "launcher.log"` |
| `runtimes` | `root / "runtimes"` |
| `libraries` | `root / "libraries"` |
| `assets` | `root / "assets"` |
| `assets_indexes` | `root / "assets" / "indexes"` |
| `assets_objects` | `root / "assets" / "objects"` |
| `assets_virtual` | `root / "assets" / "virtual"` |
| `versions` | `root / "versions"` |
| `instances` | `root / "instances"` |

```python
    @staticmethod
    def default_root(platform_name: str | None = None) -> Path:
        """The platform's launcher directory, resolved from the environment at call time."""

    @classmethod
    def default(cls) -> "Paths":
        """`for_root(default_root())`."""

    @classmethod
    def for_root(cls, root: Path | str) -> "Paths":
        """Build a Paths from an arbitrary root (used by `--home` and by tests)."""

    def ensure(self) -> None:
        """Create root and every directory field with `mkdir(parents=True, exist_ok=True)`.

        Raises:
            ConfigError: the directories cannot be created.
        """

    # Version-scoped paths
    def version_dir(self, version_id: str) -> Path: ...        # versions/{id}/
    def version_json(self, version_id: str) -> Path: ...       # versions/{id}/{id}.json
    def client_jar(self, version_id: str) -> Path: ...         # versions/{id}/client.jar
    def fabric_merged_json(self, version_id: str) -> Path: ...  # versions/{id}/fabric-merged.json
    def manifest_cache(self) -> Path: ...                      # versions/version_manifest_v2.json

    # Asset-scoped paths
    def asset_index_path(self, index_id: str) -> Path: ...     # assets/indexes/{index_id}.json
    def asset_object_path(self, sha1: str) -> Path: ...        # assets/objects/{sha1[:2]}/{sha1}
    def virtual_assets_dir(self, index_id: str) -> Path: ...   # assets/virtual/{index_id}/

    # Runtime- and instance-scoped paths
    def runtime_dir(self, major: int) -> Path: ...             # runtimes/java-{major}/
    def instance_dir(self, name: str) -> Path: ...             # instances/{name}/
    def instance_paths(self, name: str) -> "InstancePaths": ...
```

`default_root(platform_name)` uses `sys.platform` when `platform_name` is `None`;
it reads the environment on every call so tests can monkeypatch `sys.platform`,
`APPDATA` and `HOME`.

| `platform_name` | Root |
|---|---|
| `"win32"` | `Path(os.environ["APPDATA"]) / APP_NAME`; when `APPDATA` is unset or empty, `Path.home() / "AppData" / "Roaming" / APP_NAME` |
| `"darwin"` | `Path.home() / "Library" / "Application Support" / APP_NAME` |
| anything else (`"linux"`, BSDs) | `Path(os.environ["XDG_DATA_HOME"]) / APP_DIR_POSIX` when `XDG_DATA_HOME` is set and non-empty, else `Path.home() / ".local" / "share" / APP_DIR_POSIX` |

`runtime_dir(major)` is the single definition of the runtime directory name;
`core/runtime.runtime_dir(paths, major)` (section 11) returns exactly this.

### 3.2 `InstancePaths`

```python
@dataclass(frozen=True, slots=True)
class InstancePaths:
    """The directories and files inside one instance."""
    name: str
    root: Path
    mods: Path
    resourcepacks: Path
    shaderpacks: Path
    saves: Path
    logs: Path
    natives: Path
    resources: Path
    options_txt: Path
    instance_json: Path
    latest_log: Path
    launcher_stdout_log: Path
    mods_sidecar: Path

    @classmethod
    def for_dir(cls, name: str, root: Path) -> "InstancePaths": ...

    def ensure(self) -> None:
        """Create root, mods, resourcepacks, shaderpacks, saves, logs and natives.

        Raises:
            InstanceError: the directories cannot be created.
        """
```

| Field | Value | Notes |
|---|---|---|
| `mods` | `root / "mods"` | |
| `resourcepacks` | `root / "resourcepacks"` | shown as "Texture Packs" in the UI |
| `shaderpacks` | `root / "shaderpacks"` | |
| `saves` | `root / "saves"` | |
| `logs` | `root / "logs"` | |
| `natives` | `root / "natives"` | always created; passed as `-Djava.library.path` |
| `resources` | `root / "resources"` | only used by `map_to_resources` asset indexes (section 14); not created by `ensure()` |
| `options_txt` | `root / "options.txt"` | |
| `instance_json` | `root / "instance.json"` | schema in section 17 |
| `latest_log` | `root / "logs" / "latest.log"` | **the game writes this**; the launcher only reads it |
| `launcher_stdout_log` | `root / "logs" / "launcher-stdout.log"` | the launcher's own capture of the game's stdout/stderr (amendment, sections 3/19) |
| `mods_sidecar` | `root / "mods" / ".maestro-mods.json"` | installed-mod record, schema in section 16 |

### 3.3 Atomic writes and JSON

Every write in the launcher goes through one of these. The sequence is fixed:
write to `path.with_name(path.name + ".part")`, `flush()`, `os.fsync(fd)`, close,
then `os.replace(part, path)`. The parent directory is created first. A failed
write removes the `.part` file before propagating.

```python
def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write bytes to `path` atomically; `mode` is applied with os.chmod on POSIX only."""

def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", mode: int | None = None) -> None:
    """Write text to `path` atomically, with `\\n` line endings (newline="")."""

def atomic_write_json(path: Path, obj: Any, *, indent: int = 2, mode: int | None = None) -> None:
    """Serialise `obj` (sort_keys=False, ensure_ascii=False) and write it atomically."""

def read_json(path: Path) -> Any:
    """Read and decode a JSON file (UTF-8)."""
```

`Raises:` for all four: `OSError` and, for `read_json`, `json.JSONDecodeError` are
deliberately **not** wrapped — these are the low-level helpers named in the
conventions preamble. Every caller translates them into the launcher error class
that carries the user-facing meaning (`ConfigError`, `ManifestError`, `InstanceError`).

### 3.4 Hashing and permissions

```python
def hash_file(path: Path, algorithm: str = "sha1", *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Lowercase hex digest of a file, read in `chunk_size` blocks."""

def sha1_file(path: Path, *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Lowercase 40-character SHA-1 hex digest of a file."""

def sha256_file(path: Path, *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Lowercase 64-character SHA-256 hex digest of a file."""

def sha512_file(path: Path, *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Lowercase 128-character SHA-512 hex digest of a file."""

def file_matches(path: Path, expected_hash: str | None, *, algorithm: str = "sha1",
                 expected_size: int | None = None) -> bool:
    """True when `path` exists and matches the expected size and hash (skip-download test)."""

def posix_chmod_600(path: Path) -> None:
    """`os.chmod(path, 0o600)` on POSIX; a no-op on Windows."""

def posix_chmod_755(path: Path) -> None:
    """`os.chmod(path, 0o755)` on POSIX; a no-op on Windows."""
```

`hash_file` accepts `"sha1"`, `"sha256"` and `"sha512"`; any other value raises
`ValueError`. The four hashers raise `OSError` unwrapped (as above).

`file_matches` rules, in order: a missing file is `False`; a size mismatch (when
`expected_size` is given) is `False` **without hashing**; an `expected_hash` of
`None` or `""` means "no hash known", so the file matches on existence and size
alone; otherwise the digest is compared case-insensitively.

`posix_chmod_755` exists so `core/runtime.py` (section 11) does not re-implement
the `zipfile`-loses-the-executable-bit fix.

---

## 4. `messages.py`

Everything a worker thread wants to tell the UI is one of these frozen
dataclasses, put on the single `queue.Queue` owned by `tasks.TaskRunner`
(section 20). Workers construct them; only `ui/app.py` reads them. They hold
plain data — never a `Path` that has to be resolved on the UI thread, never a
widget, never a `CTkImage`.

```python
@dataclass(frozen=True, slots=True)
class Progress:
    """A determinate step of a long operation."""
    task_id: str
    label: str
    done: int
    total: int

@dataclass(frozen=True, slots=True)
class TaskFinished:
    """A task returned normally; `result` is whatever the worker function returned."""
    task_id: str
    result: object

@dataclass(frozen=True, slots=True)
class TaskFailed:
    """A task raised; `user_message` is display-ready, `exc` is for the log."""
    task_id: str
    exc: BaseException
    user_message: str

@dataclass(frozen=True, slots=True)
class LogLine:
    """One line of game output, already stripped of its trailing newline."""
    text: str

@dataclass(frozen=True, slots=True)
class AuthCode:
    """The Microsoft device code and the page the user must open."""
    code: str
    url: str

@dataclass(frozen=True, slots=True)
class GameStarted:
    """The game process is running."""
    task_id: str
    pid: int

@dataclass(frozen=True, slots=True)
class GameExited:
    """The game process ended; `hint` is a plain-English cause when one was recognised."""
    task_id: str
    exit_code: int
    log_tail: tuple[str, ...]
    hint: str | None

UIMessage: TypeAlias = (
    Progress | TaskFinished | TaskFailed | LogLine | AuthCode | GameStarted | GameExited
)
```

Normative notes:

- `Progress.total == 0` means "total not yet known"; the UI shows the label and
  leaves the bar at its previous value. It is never used as a licence to show a
  bare spinner for an operation whose total is knowable.
- `Progress.done` is never greater than `Progress.total` when `total > 0`.
- `TaskFinished.result` is typed `object` on purpose: each screen knows what its
  own task returns and casts locally.
- `GameExited.log_tail` is a tuple (frozen dataclasses hold immutables) of at most
  200 lines, oldest first.

Task-id constants. A task id identifies the *kind* of work so the UI can route a
message to the right widget; ids for per-item work append `":"` and the item key
(for example `f"{TASK_MOD_ICON}:{project_id}"`).

```python
TASK_VERSIONS: Final[str] = "versions"
TASK_SIGN_IN: Final[str] = "sign-in"
TASK_REFRESH: Final[str] = "refresh"
TASK_LAUNCH: Final[str] = "launch"
TASK_GAME: Final[str] = "game"
TASK_MOD_SEARCH: Final[str] = "mod-search"
TASK_MOD_INSTALL: Final[str] = "mod-install"
TASK_MOD_ICON: Final[str] = "mod-icon"
TASK_MOD_LIST: Final[str] = "mod-list"
TASK_MOD_UPDATES: Final[str] = "mod-updates"
TASK_MOD_DELETE: Final[str] = "mod-delete"
TASK_INSTANCE: Final[str] = "instance"
TASK_BUNDLED_MODS: Final[str] = "bundled-mods"

def task_key(task_id: str) -> str:
    """The part of a task id before the first ':' — the task kind."""

def task_item(task_id: str) -> str:
    """The part of a task id after the first ':' — the item key, or "" when there is none."""
```

---

## 5. `logsetup.py`

Logging is process-global by nature, so this module owns the one sanctioned
module-level singleton, `REDACTOR`. Nothing else in the launcher has one.

```python
REDACTION: Final[str] = "[redacted]"
MIN_SECRET_LENGTH: Final[int] = 12
LOGGER_NAME: Final[str] = "maestro"
LOG_MAX_BYTES: Final[int] = 2 * 1024 * 1024      # 2 MiB per file
LOG_BACKUP_COUNT: Final[int] = 3                 # launcher.log + .1 .2 .3
LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
```

### 5.1 `Redactor`

```python
class Redactor:
    """Removes secrets from strings before they reach a log file or the screen."""

    def __init__(self) -> None: ...

    def register(self, secret: str | None) -> None:
        """Remember a literal secret so every later `redact` call removes it."""

    def clear(self) -> None:
        """Forget every registered secret (used by tests and by sign-out)."""

    def redact(self, text: str) -> str:
        """Replace registered secrets and token-shaped substrings with `REDACTION`."""
```

`register` ignores `None`, `""` and any value shorter than `MIN_SECRET_LENGTH`.
The length floor exists because an offline placeholder account carries the access
token `"0"` (section 10) and registering it would blank every digit in the log.
Registered secrets are matched literally, longest first, so a token that contains
another registered token is fully removed.

`redact` then applies these patterns, in this order, to whatever remains. They are
module constants so tests can assert against them:

```python
PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*"),          # JWT
    re.compile(r"XBL3\.0\s+x=[^;\s]+;\S+"),                                          # Mojang identityToken
    re.compile(r"(?i)\bBearer\s+\S+"),                                               # Authorization header
    re.compile(r"(?i)\b(?:d|t)=[A-Za-z0-9._~+/-]{20,}"),                             # RpsTicket
    re.compile(
        r"(?i)(\"?\b(?:access_token|refresh_token|id_token|device_code|user_code"
        r"|identityToken|RpsTicket|Token)\b\"?\s*[:=]\s*\"?)([^\s\"',&}]+)"
    ),                                                                               # key=value / "key": "value"
)
```

The last pattern keeps group 1 and replaces group 2; the others replace the whole
match. `redact` never raises: a non-string argument is coerced with `str()`.

```python
REDACTOR: Final[Redactor] = Redactor()
```

### 5.2 Filter and setup

```python
class RedactingFilter(logging.Filter):
    """Runs every record's message and args through a Redactor before formatting."""

    def __init__(self, redactor: Redactor = REDACTOR) -> None: ...

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact `record.msg` and `record.args` in place; always returns True."""

def configure_logging(paths: Paths, level: int = logging.INFO, *, console: bool = True) -> logging.Logger:
    """Attach a redacted rotating file handler (and optionally a console handler) to the root logger."""

def get_logger(name: str) -> logging.Logger:
    """`logging.getLogger(f"{LOGGER_NAME}.{name}")` — the only way modules obtain a logger."""
```

`configure_logging` normative behaviour:

1. Creates `paths.root` if it does not exist, then a
   `logging.handlers.RotatingFileHandler(paths.launcher_log, maxBytes=LOG_MAX_BYTES,
   backupCount=LOG_BACKUP_COUNT, encoding="utf-8", delay=False)`.
2. If that raises `OSError` (read-only directory, locked file), it logs a warning
   to the console handler and continues **without** a file handler. It never
   raises: a launcher that cannot write its log still starts.
3. Adds a `logging.StreamHandler` on `sys.stderr` when `console` is True.
4. Installs a `RedactingFilter` on **every** handler it adds — the redaction is a
   handler filter, not a formatter, so it also covers `logging.exception` tracebacks.
5. Sets the level on the `LOGGER_NAME` logger and on the handlers; leaves the root
   logger's other handlers alone; sets `logging.getLogger("urllib3").setLevel(logging.WARNING)`.
6. Is idempotent: calling it twice removes the handlers it added the first time
   before adding new ones.
7. Returns the `LOGGER_NAME` logger.

`Raises:` nothing.

---

## 6. `core/progress.py`

```python
ProgressFn: TypeAlias = Callable[[str, int, int], None]

def null_progress(label: str, done: int, total: int) -> None:
    """A ProgressFn that discards everything — the default for optional progress."""

NULL_PROGRESS: Final[ProgressFn] = null_progress
```

Every long operation in this contract has `progress: ProgressFn = null_progress`
and `cancel: CancelToken | None = None` as keyword parameters. `None` for `cancel`
means "this call cannot be cancelled"; implementations must therefore use
`check_cancel(cancel)` rather than `cancel.raise_if_cancelled()` directly.

### 6.1 `CancelToken`

```python
class CancelToken:
    """A `threading.Event` in launcher clothing: one worker's cancellation flag."""

    def __init__(self, event: threading.Event | None = None) -> None: ...

    @property
    def is_cancelled(self) -> bool:
        """True once `cancel()` has been called."""

    def cancel(self) -> None:
        """Set the flag; safe to call from any thread, and safe to call twice."""

    def raise_if_cancelled(self) -> None:
        """Stop the current operation if cancellation was requested.

        Raises:
            CancelledError: the token is set.
        """

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or `timeout` elapses; True when cancelled. Used instead
        of `time.sleep` in polling loops so cancelling is immediate."""

def check_cancel(cancel: CancelToken | None) -> None:
    """`cancel.raise_if_cancelled()` when `cancel` is not None; a no-op otherwise.

    Raises:
        CancelledError: the token is set.
    """
```

### 6.2 `Reporter`

A `Reporter` is itself a `ProgressFn`, so it can be passed straight into any long
operation. It maps a child operation's `(done, total)` onto a slice of its parent's
0.0–1.0 range, which is how `core/pipeline.py` (section 18) gives each step a weight.

```python
@dataclass(slots=True)
class Reporter:
    """Scales a sub-task's progress into a fraction of a parent operation's range."""
    progress: ProgressFn
    label: str = ""
    start: float = 0.0
    end: float = 1.0
    total_units: int = 1000

    def __call__(self, label: str, done: int, total: int) -> None:
        """ProgressFn entry point: forward the child's fraction, remapped into [start, end]."""

    def sub(self, label: str, start: float, end: float) -> "Reporter":
        """A nested reporter covering the [start, end] fraction *of this reporter's* range."""

    def set(self, done: int, total: int, label: str | None = None) -> None:
        """Report progress directly, without a child operation."""

    def note(self, label: str) -> None:
        """Report a new label at this reporter's `start` fraction (step boundaries)."""
```

Mapping, normative:

- child fraction `f = done / total` when `total > 0`, else `0.0`; clamped to `[0.0, 1.0]`.
- forwarded call is `self.progress(text, round((start + (end - start) * f) * total_units), total_units)`.
- `text` is the child's `label` when it is non-empty, otherwise `self.label`.
- `sub(label, s, e)` returns `Reporter(self.progress, label, self.start + (self.end - self.start) * s,
  self.start + (self.end - self.start) * e, self.total_units)`, so nesting composes.
- `total_units` is 1000 everywhere: a `Progress` message therefore carries permille,
  and the UI divides by `total` rather than assuming a scale.

### 6.3 `format_bytes`

```python
def format_bytes(n: int | float) -> str:
    """Human byte count for a progress label: '512 B', '1.4 KB', '58.5 MB', '1.2 GB'."""
```

Base 1024. Units `("B", "KB", "MB", "GB", "TB")`. Bytes print as an integer with no
decimal; every larger unit prints one decimal place. Negative input is treated as 0.

---

## 7. `core/net.py`

One class owns every outbound HTTP request in the launcher. It is the only place
`timeout=` is written, the only place retries happen, and the only place a
`requests.Session` is created.

```python
TIMEOUT: Final[tuple[int, int]] = (10, 60)          # (connect, read) — spec section 11
USER_AGENT: Final[str] = "MaestroLauncher/1.0 (+https://github.com/<placeholder>/maestrolauncher)"
POOL_CONNECTIONS: Final[int] = 16
POOL_MAXSIZE: Final[int] = 32
RETRY_ATTEMPTS: Final[int] = 4                      # 1 initial try + 3 retries
RETRY_BASE_DELAY: Final[float] = 0.5                # seconds before the first retry
RETRY_FACTOR: Final[float] = 2.0                    # 0.5s, 1.0s, 2.0s ...
RETRY_MAX_DELAY: Final[float] = 8.0                 # ceiling before jitter
RETRY_JITTER: Final[float] = 0.25                   # +/- 25 %
RETRY_AFTER_CAP: Final[float] = 60.0                # honour Retry-After up to this
RETRY_STATUSES: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
DOWNLOAD_CHUNK_SIZE: Final[int] = 64 * 1024
```

Backoff, exactly: before retry number `n` (1-based) the helper sleeps
`min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * RETRY_FACTOR ** (n - 1))` multiplied by
`1 - RETRY_JITTER + 2 * RETRY_JITTER * rng.random()` — that is, a uniform ±25 %
around 0.5 s, 1.0 s, 2.0 s. When the failing response is a 429 (or any retryable
status) carrying a numeric `Retry-After` header, that value is used instead of the
computed delay, capped at `RETRY_AFTER_CAP`.

### 7.1 `Http`

```python
class Http:
    """The launcher's HTTP client: fixed timeouts, one retry policy, verified downloads."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        adapter: requests.adapters.BaseAdapter | None = None,
        user_agent: str = USER_AGENT,
        attempts: int = RETRY_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        """Build a client; pass `adapter` (a FakeAdapter) to run the whole stack offline."""

    def close(self) -> None:
        """Close the underlying session."""

    def __enter__(self) -> "Http": ...
    def __exit__(self, *exc: object) -> None: ...
```

Construction, normative: when `session` is `None` a new `requests.Session` is
created. When `adapter` is given it is mounted on both `"http://"` and
`"https://"`; otherwise a `requests.adapters.HTTPAdapter(pool_connections=POOL_CONNECTIONS,
pool_maxsize=POOL_MAXSIZE, max_retries=0)` is mounted on both. `max_retries=0` is
deliberate: retrying is this module's job, not urllib3's, because only this module
knows that 4xx must never be retried. The session's default headers are
`{"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}`. `rng` defaults to
a fresh `random.Random()`. `sleep` and `rng` are injected so retry tests are
instant and deterministic.

```python
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | bytes | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        stream: bool = False,
        raise_for_status: bool = True,
        retry: bool = True,
        cancel: CancelToken | None = None,
    ) -> requests.Response:
        """Issue one request with `timeout=TIMEOUT`, retrying transient failures.

        Raises:
            NetworkError: connection failure or timeout that survived every attempt.
            HttpStatusError: non-2xx response and `raise_for_status` is True.
            CancelledError: `cancel` was set before the request was issued.
        """
```

**No method in this module takes a `timeout` parameter.** `request` passes
`timeout=TIMEOUT` and every other method goes through `request`, so a test that
asserts `timeout == (10, 60)` on recorded adapter calls covers the whole launcher.

`raise_for_status=False` returns the `Response` whatever its status. This exists
for exactly one reason, named in the controller design notes: the Microsoft
device-code poll answers **HTTP 400** with `{"error": "authorization_pending"}`
while the user is still signing in, and that body must be readable without an
exception being the only path to it. When `raise_for_status=True`, a non-2xx
response raises `HttpStatusError(status, body, url)` where `body` is always the
decoded response text (possibly `""`, never `None`).

Retry decision table — this is the whole policy:

| Outcome | Retried? | After the last attempt |
|---|---|---|
| `requests.ConnectionError` | yes | `NetworkError` |
| `requests.Timeout` (connect or read) | yes | `NetworkError` |
| status in `RETRY_STATUSES` (408, 425, 429, 500, 502, 503, 504) | yes | `HttpStatusError` when `raise_for_status`, else the `Response` |
| any other 4xx (400, 401, 403, 404, 409, …) | **never** | `HttpStatusError` when `raise_for_status`, else the `Response` |
| 2xx / 3xx | n/a | the `Response` |
| `ChecksumError` raised inside a download | never | propagates |
| `CancelledError` | never | propagates |

`retry=False` disables retrying for one call (used by the device-code poll loop,
which owns its own pacing).

```python
    def retry(self, fn: Callable[[], T], *, attempts: int | None = None, what: str = "") -> T:
        """Run `fn` under the module retry policy; `what` names the operation in the log.

        Raises:
            NetworkError: every attempt failed with a transport error.
            HttpStatusError: every attempt failed with a retryable status.
        """

    def get_json(
        self, url: str, *, params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None, retry: bool = True,
        cancel: CancelToken | None = None,
    ) -> Any:
        """GET and decode a JSON body.

        Raises:
            NetworkError: transport failure, or a body that is not valid JSON.
            HttpStatusError: non-2xx response.
            CancelledError: `cancel` was set.
        """

    def post_json(
        self, url: str, payload: Any, *, headers: Mapping[str, str] | None = None,
        retry: bool = True, raise_for_status: bool = True,
        cancel: CancelToken | None = None,
    ) -> requests.Response:
        """POST a JSON body (Content-Type and Accept set to application/json).

        Raises:
            NetworkError, HttpStatusError, CancelledError.
        """

    def post_form(
        self, url: str, fields: Mapping[str, str], *, headers: Mapping[str, str] | None = None,
        retry: bool = True, raise_for_status: bool = True,
        cancel: CancelToken | None = None,
    ) -> requests.Response:
        """POST application/x-www-form-urlencoded fields.

        Raises:
            NetworkError, HttpStatusError, CancelledError.
        """

    def download(
        self,
        url: str,
        dest: Path,
        *,
        expected_hash: str | None = None,
        algorithm: str = "sha1",
        expected_size: int | None = None,
        headers: Mapping[str, str] | None = None,
        label: str | None = None,
        progress: ProgressFn = null_progress,
        cancel: CancelToken | None = None,
    ) -> Path:
        """Fetch `url` to `dest` atomically, verified, skipping a file that already matches.

        Raises:
            NetworkError: transport failure that survived every attempt.
            HttpStatusError: non-2xx response.
            ChecksumError: the finished file's digest is not `expected_hash`.
            CancelledError: `cancel` was set.
            OSError: the destination cannot be written.
        """

def decode_json(response: requests.Response) -> Any:
    """Decode a Response body as JSON.

    Raises:
        NetworkError: the body is not valid JSON.
    """
```

`download`, normative:

1. `check_cancel(cancel)`, then the section 3 helper `file_matches(dest, expected_hash,
   algorithm=algorithm, expected_size=expected_size)`. On a match the function
   reports `progress(label_or_name, size, size)` once and returns `dest`
   **without any network call**. This is what makes a relaunch take three seconds
   instead of three minutes.
2. Otherwise it streams into `dest.with_name(dest.name + ".part")` with
   `stream=True`, in `DOWNLOAD_CHUNK_SIZE` chunks, calling `check_cancel(cancel)`
   and `progress(label_or_name, bytes_so_far, total)` once per chunk. `total` is
   `expected_size` when given, else the `Content-Length` header, else `0`.
3. The digest is computed while streaming, not by re-reading the file.
4. `flush`, `os.fsync`, close, verify, then `os.replace(part, dest)`.
5. A digest mismatch deletes the `.part` file and raises `ChecksumError(str(dest),
   expected, actual, algorithm)`. **A checksum mismatch is never retried here** —
   the caller decides whether a second attempt is worthwhile.
6. A transport failure is retried by the standard policy; each attempt restarts
   the download from zero and truncates the `.part` file (no `Range` requests).
7. A `CancelledError` deletes the `.part` file before propagating.
8. `label` defaults to `dest.name` in progress calls.

---

## 8. `core/config.py`

### 8.1 `config.json`

Written at `paths.config_json`. Every key, its type and its default:

```json
{
  "auth_mode": "entra",
  "client_id": "",
  "clientid": "8b0c2f2e-2b0a-4a1e-9f3e-0d5c7a6b4e21",
  "memory_gb": 6,
  "selected_version": null,
  "selected_instance": "default",
  "include_snapshots": false,
  "window": {
    "width": 1040,
    "height": 680
  },
  "last_account": null
}
```

| Key | Type | Default | Meaning and validation |
|---|---|---|---|
| `auth_mode` | string | `"entra"` | `"entra"` or `"live"`; anything else is replaced by `"entra"`. Selects the endpoint family in section 10 — the two are never mixed. |
| `client_id` | string | `""` | The user's own Entra application id. Empty means "use the mode's default". |
| `clientid` | string | a fresh UUID4 | The stable per-install id substituted into `${clientid}`. Generated on first load and never changed afterwards. Not the OAuth client id — the confusing name is Mojang's. |
| `memory_gb` | integer | `6` | Heap size in GiB. Clamped on load to `[MIN_MEMORY_GB, max_memory_gb()]`. |
| `selected_version` | string \| null | `null` | `null` means "use `latest.release` from the manifest". |
| `selected_instance` | string | `"default"` | Name of the instance under `instances/`. |
| `include_snapshots` | boolean | `false` | Whether the version dropdown lists snapshots. |
| `window` | object | `{"width": 1040, "height": 680}` | Last window size. Both values are integers; each is clamped to at least the corresponding component of section 21's `MIN_WINDOW`, which must not exceed these defaults. |
| `last_account` | string \| null | `null` | The `uuid` of the account to select at startup, or `null`. |

Unknown keys are ignored and dropped on the next save. A key of the wrong type is
replaced by its default; the rest of the file is kept.

### 8.2 Constants

```python
AUTH_MODES: Final[tuple[str, str]] = ("entra", "live")
DEFAULT_AUTH_MODE: Final[str] = "entra"
LIVE_CLIENT_ID: Final[str] = "00000000402b5328"
ENTRA_DEFAULT_CLIENT_ID: Final[str] = ""          # see the section 0 amendment
DEFAULT_MEMORY_GB: Final[int] = 6
MIN_MEMORY_GB: Final[int] = 2
MEMORY_CAP_GB: Final[int] = 12
MEMORY_HEADROOM_GB: Final[int] = 4
DEFAULT_INSTANCE_NAME: Final[str] = "default"
DEFAULT_WINDOW_WIDTH: Final[int] = 1040
DEFAULT_WINDOW_HEIGHT: Final[int] = 680
```

`LIVE_CLIENT_ID` and `ENTRA_DEFAULT_CLIENT_ID` are defined **here**, not in
`auth.py`: `core/config.py` is module 7 and `auth.py` is module 9, so the import
can only go this way. `auth.py` re-exports both names
(`from core.config import ENTRA_DEFAULT_CLIENT_ID, LIVE_CLIENT_ID`) so that
`auth.LIVE_CLIENT_ID` is valid, as section 10 requires, without a second literal.

### 8.3 `Config`

```python
@dataclass(slots=True)
class Config:
    """The parsed contents of config.json. Passed as a parameter; never a global."""
    auth_mode: str = DEFAULT_AUTH_MODE
    client_id: str = ""
    clientid: str = ""
    memory_gb: int = DEFAULT_MEMORY_GB
    selected_version: str | None = None
    selected_instance: str = DEFAULT_INSTANCE_NAME
    include_snapshots: bool = False
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    last_account: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Config":
        """Build a Config from parsed JSON, replacing every invalid value with its default."""

    def to_dict(self) -> dict[str, Any]:
        """The exact config.json object, including the nested `window` object."""

    def effective_client_id(self) -> str:
        """`client_id` when set, otherwise the default for `auth_mode`. May be ""."""
```

`from_dict` never raises. `effective_client_id` never raises and may legitimately
return `""` (the Entra case), so the Account screen can detect the situation and
offer the one-click switch to `"live"` described in the section 0 amendment.

### 8.4 Functions

```python
def load_config(paths: Paths) -> Config:
    """Read config.json, repairing or creating it as needed. Never raises."""

def save_config(paths: Paths, config: Config) -> None:
    """Write config.json atomically.

    Raises:
        ConfigError: the file cannot be written.
    """

def require_client_id(config: Config) -> str:
    """The client id to sign in with.

    Raises:
        ConfigError: the effective client id is empty (Entra with no registered app).
    """

def max_memory_gb(*, total_ram_gb: float | None = None) -> int:
    """The largest heap the RAM slider may offer: min(total - 4, 12), floor 2."""

def system_ram_gb(*, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> float | None:
    """Total physical RAM in GiB, or None when it cannot be determined. Never raises."""
```

`load_config`, normative — the spec requires the app to start cleanly with a
corrupt or absent file, so this function has no failure path:

1. Missing file, unreadable file, invalid JSON, or a top-level value that is not a
   JSON object → start from `Config()`.
2. Otherwise `Config.from_dict(parsed)`.
3. If `clientid` is empty or not a 36-character UUID string, set it to
   `str(uuid.uuid4())`. This is the only time it changes.
4. Clamp `memory_gb` into `[MIN_MEMORY_GB, max_memory_gb()]`.
5. If anything in steps 1–4 changed the file's content, write it back with
   `save_config`. A failure to write is logged at WARNING and swallowed — an
   unwritable config must not stop the launcher.
6. `Raises:` nothing.

`max_memory_gb`: with `total_ram_gb` given, returns
`max(MIN_MEMORY_GB, min(int(total_ram_gb) - MEMORY_HEADROOM_GB, MEMORY_CAP_GB))`.
With it `None` it calls `system_ram_gb()`; if that also returns `None` the cap is
`DEFAULT_MEMORY_GB` (6). The result is always at least `MIN_MEMORY_GB`, so a 4 GiB
machine still gets a usable slider.

`system_ram_gb` reads total RAM per platform, dividing by `1024 ** 3` and returning
`None` on any exception:

| `sys.platform` | Source |
|---|---|
| `"win32"` | `ctypes`: a `MEMORYSTATUSEX` structure whose `dwLength` field is set to `ctypes.sizeof(...)`, passed to `ctypes.windll.kernel32.GlobalMemoryStatusEx`; read `ullTotalPhys`. |
| `"linux"` (and other non-Darwin POSIX) | `/proc/meminfo`, the `MemTotal:` line, which is in kB — divide by `1024 ** 2`. |
| `"darwin"` | `run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)`; the stdout is a byte count. |

`run` is injected so the macOS branch is testable on any platform.

The UI note the spec asks for ("more RAM is not faster for a Minecraft client;
large heaps increase GC pause time — 4–8 GB is right for Sodium plus a normal
modlist") is interface copy and belongs to section 22, not to this module.

---

## 9. `core/versions.py`

```python
MANIFEST_URL: Final[str] = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RELEASE_TYPE: Final[str] = "release"
SNAPSHOT_TYPE: Final[str] = "snapshot"
LISTED_TYPES: Final[tuple[str, str]] = ("release", "snapshot")
```

Minecraft moved to calendar versioning in 2026: `26.2` is newer than `1.21.11`,
which no string comparator and no semver parser gets right. **Ordering in this
module comes from the manifest's own order and nothing else.** `versions[0]` is
the newest. There is no version comparator here; `core/fabric.compare_versions`
exists only for Maven library versions and must never be applied to a game version.

### 9.1 Dataclasses

```python
@dataclass(frozen=True, slots=True)
class VersionEntry:
    """One entry of version_manifest_v2.json, plus its position in the list."""
    id: str
    type: str                  # "release" | "snapshot" | "old_beta" | "old_alpha"
    url: str
    time: str
    release_time: str          # JSON key "releaseTime"
    sha1: str                  # SHA-1 of the version JSON at `url`
    compliance_level: int      # JSON key "complianceLevel"
    index: int                 # 0 = newest

@dataclass(frozen=True, slots=True)
class VersionManifest:
    """The manifest, in manifest order."""
    latest_release: str
    latest_snapshot: str
    versions: tuple[VersionEntry, ...]

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "VersionManifest":
        """Parse a decoded version_manifest_v2.json, preserving list order.

        Raises:
            ManifestError: `latest` or `versions` is missing or malformed.
        """

    def by_id(self, version_id: str) -> VersionEntry | None:
        """The entry with this id, or None."""

    def get(self, version_id: str) -> VersionEntry:
        """The entry with this id.

        Raises:
            ManifestError: no such version.
        """

    def index_of(self, version_id: str) -> int:
        """Position in the manifest; 0 is the newest version published.

        Raises:
            ManifestError: no such version.
        """

    def is_newer(self, a: str, b: str) -> bool:
        """True when `a` was published after `b`, decided by manifest index.

        Raises:
            ManifestError: either id is unknown.
        """

    def releases(self, include_snapshots: bool = False) -> tuple[VersionEntry, ...]:
        """The entries for the version dropdown, still in manifest order."""

    def ids(self, include_snapshots: bool = False) -> tuple[str, ...]:
        """`releases(...)` as a tuple of ids — the dropdown's `values`."""

    def default_version(self) -> str:
        """`latest_release` — the version selected when config has none."""
```

`is_newer(a, b)` is `self.index_of(a) < self.index_of(b)`, because index 0 is the
newest. `releases(False)` keeps only `type == "release"`; `releases(True)` keeps
`type in LISTED_TYPES`. `old_beta` and `old_alpha` are never listed in either case.

### 9.2 Functions

```python
def fetch_manifest(http: Http, paths: Paths, *, cancel: CancelToken | None = None) -> VersionManifest:
    """Fetch the version manifest, falling back to the cached copy when offline.

    Raises:
        ManifestError: the response (or the cache) is not a usable manifest.
        NetworkError: the network failed and there is no cached copy.
        HttpStatusError: a non-retryable HTTP status and there is no cached copy.
        CancelledError: `cancel` was set.
    """

def fetch_version_json(
    http: Http, paths: Paths, entry: VersionEntry, *,
    progress: ProgressFn = null_progress, cancel: CancelToken | None = None,
) -> dict[str, Any]:
    """Fetch (or reuse) `versions/{id}/{id}.json`, verified against the manifest SHA-1.

    Raises:
        ManifestError: the file is not a JSON object.
        ChecksumError: the downloaded JSON does not match `entry.sha1`.
        NetworkError, HttpStatusError, CancelledError.
    """

def java_major(version_json: Mapping[str, Any]) -> int:
    """The Java major version this Minecraft version needs.

    Raises:
        ManifestError: `javaVersion.majorVersion` is missing or not an integer.
    """

def main_class(version_json: Mapping[str, Any]) -> str:
    """The version's `mainClass`.

    Raises:
        ManifestError: the key is missing or empty.
    """

def version_type(version_json: Mapping[str, Any]) -> str:
    """The version's `type`, substituted into `${version_type}`; "release" when absent."""

def has_modern_arguments(version_json: Mapping[str, Any]) -> bool:
    """True when the version JSON has an `arguments` object (1.13 and newer)."""
```

`fetch_manifest`, normative:

1. The network is always tried first; there is no time-to-live and no conditional
   request. `http.get_json(MANIFEST_URL, cancel=cancel)`.
2. On success the decoded object is written to `paths.manifest_cache()` with
   `atomic_write_json` before parsing, so the next offline start has a copy. A
   failure to write the cache is logged at WARNING and ignored.
3. On `NetworkError` or `HttpStatusError`, the cached file is read instead; a
   successful parse of the cache is returned and the failure is logged at WARNING.
   If there is no cache, or the cache does not parse, the original network
   exception is re-raised.
4. A response that parses as JSON but is not a manifest raises `ManifestError`
   without touching the cache.

`java_major` is the **only** source of the Java version anywhere in the launcher.
There is no constant default and no per-version table: 1.21.x asks for 21, 26.2
asks for 25, and a version released next year will ask for something else.

`fetch_version_json` uses `http.download(entry.url, paths.version_json(entry.id),
expected_hash=entry.sha1, algorithm="sha1", progress=progress, cancel=cancel)`,
which skips the request entirely when the cached file already matches, then reads
it with the section 3 helper `read_json` and wraps `json.JSONDecodeError` in
`ManifestError`.

---

## 10. `auth.py`

### 10.1 The comment block at the top of the module

Spec section 4.1 requires the client-id decision to be written down where the
implementer of the module reads it. The module begins with this comment, in these
words:

> **Path A (correct).** You register your own Microsoft Entra application:
> Azure portal → App registrations → New registration → "Mobile and desktop
> applications" as the platform, "Allow public client flows" = Yes, then apply for
> Minecraft API access through Microsoft's third-party launcher form. Put the
> application (client) id into `config.json` as `client_id`. This mode talks to
> `https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode` and
> `.../token` with the scope `XboxLive.signin offline_access`.
>
> **Path B (what most hobby launchers actually do).** The legacy Minecraft client
> id `00000000402b5328`. It is a **Live** app registration, not an Entra app, and
> it does **not** work against `login.microsoftonline.com/consumers/v2.0`. It has
> to be used with the Live endpoints `https://login.live.com/oauth20_connect.srf`
> and `https://login.live.com/oauth20_token.srf`, with the scope
> `service::user.auth.xboxlive.com::MBI_SSL`.
>
> Both are implemented. `config.json`'s `auth_mode` picks one, defaulting to
> `"entra"`. **The two endpoint families are never mixed**: no function in this
> module takes a bare URL, scope or ticket prefix. Every request resolves its
> endpoints through `endpoints_for(mode)` and uses the `AuthEndpoints` record it
> returns, so a Live client id can never reach an Entra URL.
>
> There is no usable constant fallback for Entra (see the section 0 amendment):
> `ENTRA_DEFAULT_CLIENT_ID` is `""`, because a valid Entra client id only exists
> once the user has registered their own app. An empty effective client id is a
> `ConfigError`, and the Account screen offers a one-click switch to `"live"`.

### 10.2 Endpoint constants — two families, kept apart

```python
# --- Entra (auth_mode == "entra"), Path A ---------------------------------
ENTRA_DEVICE_CODE_URL: Final[str] = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
ENTRA_TOKEN_URL: Final[str] = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
ENTRA_SCOPE: Final[str] = "XboxLive.signin offline_access"
ENTRA_RPS_PREFIX: Final[str] = "d="

# --- Live (auth_mode == "live"), Path B -----------------------------------
LIVE_DEVICE_CODE_URL: Final[str] = "https://login.live.com/oauth20_connect.srf"
LIVE_TOKEN_URL: Final[str] = "https://login.live.com/oauth20_token.srf"
LIVE_SCOPE: Final[str] = "service::user.auth.xboxlive.com::MBI_SSL"
LIVE_RPS_PREFIX: Final[str] = "t="

# Re-exported from core.config so there is exactly one literal for each (section 8.2)
from core.config import ENTRA_DEFAULT_CLIENT_ID, LIVE_CLIENT_ID

# --- Shared OAuth values ---------------------------------------------------
DEVICE_CODE_GRANT: Final[str] = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_GRANT: Final[str] = "refresh_token"

# --- Xbox and Mojang (identical in both modes) -----------------------------
XBL_AUTH_URL: Final[str] = "https://user.auth.xboxlive.com/user/authenticate"
XBL_RELYING_PARTY: Final[str] = "http://auth.xboxlive.com"
XSTS_AUTH_URL: Final[str] = "https://xsts.auth.xboxlive.com/xsts/authorize"
XSTS_RELYING_PARTY: Final[str] = "rp://api.minecraftservices.com/"
XSTS_SANDBOX_ID: Final[str] = "RETAIL"
MOJANG_LOGIN_URL: Final[str] = "https://api.minecraftservices.com/authentication/login_with_xbox"
MOJANG_PROFILE_URL: Final[str] = "https://api.minecraftservices.com/minecraft/profile"

# --- Polling and freshness -------------------------------------------------
DEFAULT_POLL_INTERVAL: Final[int] = 5          # seconds, when the server sends none
SLOW_DOWN_INCREMENT: Final[int] = 5            # spec section 4.2: slow_down adds 5 s
MAX_POLL_NETWORK_FAILURES: Final[int] = 3      # consecutive transport failures tolerated
REFRESH_MARGIN_SECONDS: Final[float] = 300.0   # refresh 5 minutes before expiry
ACCOUNTS_FILE_VERSION: Final[int] = 1
DPAPI_DESCRIPTION: Final[str] = "MaestroLauncher accounts"
```

```python
@dataclass(frozen=True, slots=True)
class AuthEndpoints:
    """One coherent OAuth endpoint family. The only way a URL enters this module."""
    mode: str
    device_code_url: str
    token_url: str
    scope: str
    rps_prefix: str
    default_client_id: str

ENTRA_ENDPOINTS: Final[AuthEndpoints] = AuthEndpoints(
    "entra", ENTRA_DEVICE_CODE_URL, ENTRA_TOKEN_URL, ENTRA_SCOPE,
    ENTRA_RPS_PREFIX, ENTRA_DEFAULT_CLIENT_ID,
)
LIVE_ENDPOINTS: Final[AuthEndpoints] = AuthEndpoints(
    "live", LIVE_DEVICE_CODE_URL, LIVE_TOKEN_URL, LIVE_SCOPE,
    LIVE_RPS_PREFIX, LIVE_CLIENT_ID,
)

def endpoints_for(mode: str) -> AuthEndpoints:
    """The endpoint family for an `auth_mode` value.

    Raises:
        ConfigError: `mode` is neither "entra" nor "live".
    """
```

The `rps_prefix` is the RpsTicket prefix used in step 2 of the chain: `"d="` for an
Entra-issued token, `"t="` for a Live (MBI_SSL) token. This is the documented
community convention and cannot be verified without a real interactive sign-in,
which is exactly why it lives in one named constant per mode: correcting it is a
one-line change, not a hunt.

Request bodies, per mode. These are `application/x-www-form-urlencoded` fields
posted with `Http.post_form`:

| Call | Entra fields | Live fields |
|---|---|---|
| Device code | `client_id`, `scope=XboxLive.signin offline_access` | `client_id`, `scope=service::user.auth.xboxlive.com::MBI_SSL`, `response_type=device_code` |
| Token poll | `grant_type=urn:ietf:params:oauth:grant-type:device_code`, `client_id`, `device_code` | `client_id`, `device_code`, `grant_type=urn:ietf:params:oauth:grant-type:device_code` |
| Refresh | `grant_type=refresh_token`, `refresh_token`, `client_id`, `scope=XboxLive.signin offline_access` | `grant_type=refresh_token`, `refresh_token`, `client_id`, `scope=service::user.auth.xboxlive.com::MBI_SSL` |

### 10.3 Dataclasses

```python
@dataclass(frozen=True, slots=True)
class DeviceCode:
    """What the device-code endpoint returned: what to show the user, and how to poll."""
    user_code: str
    verification_uri: str
    device_code: str
    interval: int
    expires_in: int
    expires_at: float          # absolute epoch seconds, clock() + expires_in
    message: str = ""          # Entra sends a ready-made sentence; Live does not

@dataclass(frozen=True, slots=True)
class MsaTokens:
    """Microsoft tokens from the device-code or refresh grant."""
    access_token: str
    refresh_token: str
    expires_at: float                    # absolute epoch seconds
    refresh_expires_at: float | None = None

@dataclass(frozen=True, slots=True)
class XblToken:
    """Xbox Live user token and its user hash."""
    token: str
    uhs: str

@dataclass(frozen=True, slots=True)
class XstsToken:
    """XSTS token, user hash and the XUID that ${auth_xuid} needs at launch."""
    token: str
    uhs: str
    xuid: str

    @property
    def identity_token(self) -> str:
        """`XBL3.0 x={uhs};{token}` — the body of the Mojang login request."""

@dataclass(frozen=True, slots=True)
class MojangToken:
    """The Minecraft services bearer token."""
    access_token: str
    expires_at: float                    # absolute epoch seconds

@dataclass(frozen=True, slots=True)
class Profile:
    """The Minecraft: Java Edition profile."""
    uuid: str                            # 32 hex characters, no dashes, exactly as returned
    name: str
```

```python
@dataclass(slots=True)
class Account:
    """A signed-in account as it is stored on disk and used at launch."""
    name: str = ""
    uuid: str = ""
    xuid: str = ""
    access_token: str = ""
    access_expires_at: float = 0.0
    refresh_token: str = ""
    refresh_expires_at: float | None = None
    auth_mode: str = "entra"

    def is_expired(self, *, now: float | None = None, within_seconds: float = 0.0) -> bool:
        """True when the Mojang token expires within `within_seconds` of `now`."""

    @property
    def uuid_dashed(self) -> str:
        """The uuid in 8-4-4-4-12 form. For display only — never for ${auth_uuid}."""

    def to_dict(self) -> dict[str, Any]:
        """The account's accounts.json object."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Account":
        """Build an Account from a stored object, defaulting every missing or mistyped field."""
```

Every field has a default and nothing is validated in the constructor: an
end-to-end test tool builds an offline placeholder with `Account(name="Player",
uuid="0" * 32, access_token="0")`, and that must work. `sign_in` and `refresh`
always populate every field.

`${auth_uuid}` is `Account.uuid` verbatim — 32 hex characters with no dashes, as
the profile endpoint returns it. `uuid_dashed` exists for the Account screen only.

### 10.4 `accounts.json`

Written at `paths.accounts_json`, `0o600` on POSIX. The file is always a JSON
object whose `encryption` key says how to read the rest. Plaintext form:

```json
{
  "version": 1,
  "encryption": "none",
  "accounts": [
    {
      "name": "Player",
      "uuid": "00000000000000000000000000000000",
      "xuid": "",
      "access_token": "",
      "access_expires_at": 0.0,
      "refresh_token": "",
      "refresh_expires_at": null,
      "auth_mode": "entra"
    }
  ]
}
```

DPAPI form — used whenever `dpapi_available()` is true, i.e. on Windows with
`pywin32` importable:

```json
{
  "version": 1,
  "encryption": "dpapi",
  "payload": "AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA...="
}
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `version` | integer | `1` | `ACCOUNTS_FILE_VERSION`. A higher value is treated as unreadable and the file is replaced on the next save. |
| `encryption` | string | `"none"` | `"none"` or `"dpapi"`. Any other value is treated as unreadable. |
| `accounts` | array of objects | `[]` | Present only when `encryption` is `"none"`. |
| `payload` | string | absent | Present only when `encryption` is `"dpapi"`: base64 (standard alphabet, with padding) of `CryptProtectData(json.dumps({"accounts": [...]}).encode("utf-8"))`. |

Account object fields — the same set in both forms:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | `""` | Profile name shown in the UI. |
| `uuid` | string | `""` | 32 hex characters, no dashes. The account's identity key in this file. |
| `xuid` | string | `""` | The XSTS `DisplayClaims.xui[0].xid`; becomes `${auth_xuid}`. |
| `access_token` | string | `""` | Mojang bearer token. |
| `access_expires_at` | number | `0.0` | Absolute epoch seconds, `clock() + expires_in` at receipt. |
| `refresh_token` | string | `""` | Microsoft refresh token. |
| `refresh_expires_at` | number \| null | `null` | Absolute epoch seconds, or `null` when the endpoint gave no `refresh_token_expires_in`. |
| `auth_mode` | string | `"entra"` | Which endpoint family issued these tokens; refresh must use the same one. |

Timestamps are absolute epoch seconds as floats, computed from `expires_in` at the
moment of receipt with an injectable clock — never a duration stored as-is.

### 10.5 `AccountStore`

```python
def dpapi_available() -> bool:
    """True on Windows when `win32crypt` imports. Evaluated at call time, never cached."""

def dpapi_protect(data: bytes) -> bytes:
    """`win32crypt.CryptProtectData(data, DPAPI_DESCRIPTION, None, None, None, 0)`.

    Raises:
        AuthError: pywin32 is unavailable or the call failed.
    """

def dpapi_unprotect(blob: bytes) -> bytes:
    """`win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]`.

    Raises:
        AuthError: pywin32 is unavailable or the blob cannot be decrypted.
    """

class AccountStore:
    """Reads and writes accounts.json, encrypting with DPAPI when it is available."""

    def __init__(
        self,
        paths: Paths,
        *,
        protect: Callable[[bytes], bytes] | None = None,
        unprotect: Callable[[bytes], bytes] | None = None,
    ) -> None:
        """`protect`/`unprotect` default to the DPAPI pair when available, else to None
        (plaintext). Tests inject a reversible pair to exercise the encrypted path
        on any platform."""

    @property
    def path(self) -> Path:
        """`paths.accounts_json`."""

    def load(self) -> list[Account]:
        """Every stored account, in file order. Never raises."""

    def save(self, accounts: Sequence[Account]) -> None:
        """Replace the file with these accounts, atomically, 0600 on POSIX.

        Raises:
            ConfigError: the file cannot be written.
        """

    def get(self, uuid: str) -> Account | None:
        """The stored account with this uuid, or None."""

    def upsert(self, account: Account) -> None:
        """Load, replace the entry with the same uuid (or append), save.

        Raises:
            ConfigError: the file cannot be written.
        """

    def remove(self, uuid: str) -> None:
        """Load, drop the entry with this uuid, save.

        Raises:
            ConfigError: the file cannot be written.
        """
```

`load`, normative — it has no failure path, because a launcher that cannot read
its token cache should ask the user to sign in again, not refuse to start:

1. Missing file, unreadable file, invalid JSON, a non-object top level, an
   unknown `version`, or an unknown `encryption` value → `[]` (logged at WARNING).
2. `encryption == "none"` → each object in `accounts` through `Account.from_dict`;
   entries that are not objects are skipped.
3. `encryption == "dpapi"` → base64-decode `payload`, `unprotect` it, parse the
   result as JSON and read its `accounts` array. A missing `unprotect` (the file
   was written on another machine, or `pywin32` is gone), a `binascii.Error`, an
   `AuthError` from DPAPI, or an undecodable inner document → `[]` (logged at
   WARNING, with no token material in the message).
4. Every non-empty `access_token` and `refresh_token` read is passed to
   `logsetup.REDACTOR.register` before the function returns.

`save`, normative: builds `{"version": ACCOUNTS_FILE_VERSION, "encryption": ...}`;
uses `"dpapi"` with a base64 `payload` when a `protect` callable is available,
otherwise `"none"` with an inline `accounts` array; writes it with
`atomic_write_json`; then calls `posix_chmod_600` on the file. Every token it
writes is registered with `REDACTOR` first.

### 10.6 Device-code flow

```python
class DeviceCodeSession:
    """One device-code sign-in attempt: request a code, then poll until it is used."""

    def __init__(
        self,
        mode: str,
        client_id: str,
        http: Http,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Resolve `mode` to an AuthEndpoints and keep it for every call.

        Raises:
            ConfigError: unknown `mode`, or `client_id` is empty.
        """

    @property
    def endpoints(self) -> AuthEndpoints:
        """The endpoint family this session is locked to."""

    def start(self, *, cancel: CancelToken | None = None) -> DeviceCode:
        """Ask the device-code endpoint for a user code.

        Raises:
            AuthError: the response is not a usable device-code document.
            NetworkError, HttpStatusError, CancelledError.
        """

    def poll_once(self, code: DeviceCode) -> MsaTokens | None:
        """One token-endpoint poll: tokens on success, None while the user hasn't finished.

        Raises:
            AuthSlowDownError: the server asked for a longer interval.
            AuthExpiredError: the code expired before it was used.
            AuthDeclinedError: the user declined in the browser.
            AuthError: any other OAuth error, or an unreadable response.
            NetworkError: transport failure that survived the retry policy.
        """

    def wait_for_token(
        self,
        *,
        on_code: Callable[[DeviceCode], None] | None = None,
        cancel: CancelToken | None = None,
    ) -> MsaTokens:
        """Start a flow, hand the code to `on_code`, then poll until tokens arrive.

        Raises:
            AuthExpiredError, AuthDeclinedError, AuthError, NetworkError,
            HttpStatusError, CancelledError.
        """
```

`start`, normative: posts the mode's device-code body (table in 10.2) to
`endpoints.device_code_url` with `raise_for_status=True`. It reads `device_code`,
`user_code`, `verification_uri`, `interval` (default `DEFAULT_POLL_INTERVAL` when
absent or not a positive integer), `expires_in` (default 900) and the optional
`message`; sets `expires_at = clock() + expires_in`; registers `device_code` with
`REDACTOR`; returns the `DeviceCode`. A missing `device_code` or `user_code` is an
`AuthError`. Note that Entra's `verification_uri` is
`https://microsoft.com/devicelogin` and Live's is
`https://www.microsoft.com/link` — the value is always taken from the response,
never assumed.

`poll_once`, normative. The poll uses `http.post_form(..., raise_for_status=False,
retry=False)`: a pending poll answers **HTTP 400**, which is a normal state of this
protocol and not a transport failure, and the loop owns its own pacing so the retry
helper must stay out of it. The response body is decoded as JSON; a body that is
not JSON is an `AuthError` naming the status.

| HTTP status | body `error` | Result |
|---|---|---|
| 200 | — | `MsaTokens(access_token, refresh_token, expires_at=clock() + expires_in, refresh_expires_at=clock() + refresh_token_expires_in when present else None)`; both tokens registered with `REDACTOR` |
| 400 or 401 | `authorization_pending` | returns `None` |
| 400 or 401 | `slow_down` | raises `AuthSlowDownError(code.interval + SLOW_DOWN_INCREMENT)` |
| 400 or 401 | `expired_token` | raises `AuthExpiredError` |
| 400 or 401 | `authorization_declined` | raises `AuthDeclinedError` |
| 400 or 401 | `bad_verification_code` | raises `AuthError` ("the device code was rejected; start sign-in again") |
| 400 or 401 | anything else, or absent | raises `AuthError` with `error` and `error_description` in `technical` |
| 408, 425, 429, or any 5xx | — | raises `NetworkError` — a transient server failure, which `wait_for_token` tolerates up to `MAX_POLL_NETWORK_FAILURES` times |
| any other status | — | raises `AuthError` naming the status; the body is included in `technical` only after `REDACTOR.redact` |

A 200 response missing `access_token` is an `AuthError`. A missing `refresh_token`
in a 200 response is stored as `""` and is not an error — the account simply cannot
be refreshed silently and will need a fresh sign-in.

`wait_for_token`, normative — the state machine:

1. `code = self.start(cancel=cancel)`; call `on_code(code)` exactly once,
   immediately, so the UI can show the code before any waiting happens.
2. `interval = max(code.interval, 1)`; `failures = 0`.
3. Loop:
   a. `check_cancel(cancel)`.
   b. Wait `interval` seconds using `cancel.wait(interval)` when a token was given
      (so Cancel is immediate) and `self.sleep(interval)` otherwise; then
      `check_cancel(cancel)` again. **The wait happens before the first poll** —
      the user cannot possibly have finished signing in yet.
   c. If `clock() >= code.expires_at`, raise `AuthExpiredError`.
   d. `tokens = self.poll_once(code)`; return them when they are not `None`,
      and reset `failures = 0`.
   e. `AuthSlowDownError` → `interval = err.interval`, continue.
   f. `NetworkError` → `failures += 1`; re-raise once `failures` reaches
      `MAX_POLL_NETWORK_FAILURES` (3), otherwise continue. This is the "network
      failure" case of spec section 4.2, distinct from every OAuth error because
      it surfaces `NetworkError`'s own message.
   g. `AuthExpiredError`, `AuthDeclinedError` and `AuthError` propagate immediately.
4. `CancelledError` propagates and ends the polling thread — the Account screen's
   Cancel button really does stop it.

### 10.7 The Xbox and Mojang chain

```python
def xbl_authenticate(
    http: Http, endpoints: AuthEndpoints, msa_access_token: str, *,
    cancel: CancelToken | None = None,
) -> XblToken:
    """Step 2: exchange a Microsoft token for an Xbox Live user token.

    Raises:
        AuthError: the response has no `Token` or no `DisplayClaims.xui[0].uhs`.
        NetworkError, HttpStatusError, CancelledError.
    """

def xsts_authorize(http: Http, xbl: XblToken, *, cancel: CancelToken | None = None) -> XstsToken:
    """Step 3: authorise the Xbox token for Minecraft services and read the XUID.

    Raises:
        XboxAccountError: HTTP 401 carrying an XErr code.
        AuthError: HTTP 401 with no XErr, or a response with no `Token`/`xid`.
        NetworkError, HttpStatusError, CancelledError.
    """

def login_with_xbox(
    http: Http, xsts: XstsToken, *, clock: Callable[[], float] = time.time,
    cancel: CancelToken | None = None,
) -> MojangToken:
    """Step 4: exchange the XSTS token for a Minecraft services bearer token.

    Raises:
        AuthError: the response has no `access_token`.
        NetworkError, HttpStatusError, CancelledError.
    """

def fetch_profile(http: Http, mojang: MojangToken, *, cancel: CancelToken | None = None) -> Profile:
    """Step 5: read the Minecraft: Java Edition profile.

    Raises:
        NoJavaEditionError: HTTP 404 — the account does not own Java Edition.
        TokenExpiredError: HTTP 401 — the bearer token has expired.
        AuthError: HTTP 403, or a 200 with no `id`/`name`.
        NetworkError, HttpStatusError, CancelledError.
    """
```

`xbl_authenticate` posts to `XBL_AUTH_URL`:

```json
{
  "Properties": {
    "AuthMethod": "RPS",
    "SiteName": "user.auth.xboxlive.com",
    "RpsTicket": "<endpoints.rps_prefix><msa_access_token>"
  },
  "RelyingParty": "http://auth.xboxlive.com",
  "TokenType": "JWT"
}
```

and reads `Token` and `DisplayClaims.xui[0].uhs`. The prefix comes from
`endpoints`, never from a literal at the call site.

`xsts_authorize` posts to `XSTS_AUTH_URL`:

```json
{
  "Properties": {"SandboxId": "RETAIL", "UserTokens": ["<xbl.token>"]},
  "RelyingParty": "rp://api.minecraftservices.com/",
  "TokenType": "JWT"
}
```

with `raise_for_status=False`, because the 401 body is the whole point. On a 401
the body is decoded and `XErr` is read (coerced with `int()` — it can arrive as a
string) together with `Redirect` (default `""`), and
`XboxAccountError(xerr, redirect)` is raised. Section 2's `XERR_MESSAGES` supplies
the user-facing sentence for every mapped code, and `XERR_FALLBACK` covers the
rest; this module maps **only** by constructing that exception and never writes an
XErr sentence of its own. A 401 whose body has no readable `XErr` is an
`AuthError`. Any other non-2xx status raises `HttpStatusError`. On success it reads
`Token`, `DisplayClaims.xui[0].uhs` and `DisplayClaims.xui[0].xid`; a missing `xid`
is an `AuthError`, because `${auth_xuid}` cannot be filled in without it.

| XErr | Meaning (message text lives in section 2's `XERR_MESSAGES`) |
|---|---|
| `2148916233` | The account has no Xbox profile yet. |
| `2148916235` | Xbox Live is unavailable in the account's country. |
| `2148916236` | Adult verification required. |
| `2148916237` | Adult verification required. |
| `2148916238` | The account is a child and needs a Family group. |
| anything else | `XERR_FALLBACK`, formatted with the raw code and the Redirect URL. |

`login_with_xbox` posts `{"identityToken": xsts.identity_token}` — that is
`XBL3.0 x={uhs};{token}` — to `MOJANG_LOGIN_URL`, reads `access_token` and
`expires_in` (86400 in practice), sets `expires_at = clock() + expires_in`, and
registers the token with `REDACTOR`.

`fetch_profile` sends `Authorization: Bearer {mojang.access_token}` to
`MOJANG_PROFILE_URL` with `raise_for_status=False` and dispatches on the status:

| Status | Result |
|---|---|
| 200 | `Profile(uuid=data["id"], name=data["name"])` |
| 401 | `TokenExpiredError` |
| 403 | `AuthError` |
| 404 | `NoJavaEditionError` |
| anything else | `HttpStatusError` |

**404 is not an authentication failure.** It means the Microsoft account does not
own Minecraft: Java Edition, or is a Game Pass account that has never opened the
official launcher once. It has its own error class with its own sentence
(section 2) and is never collapsed into the `AuthError` handler.

### 10.8 Top-level operations

```python
def sign_in(
    mode: str,
    client_id: str,
    http: Http,
    *,
    on_code: Callable[[DeviceCode], None] | None = None,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    clock: Callable[[], float] = time.time,
) -> Account:
    """Run the whole device-code → XBL → XSTS → Mojang → profile chain.

    Raises:
        ConfigError: unknown mode, or an empty client id.
        AuthExpiredError, AuthDeclinedError, XboxAccountError, NoJavaEditionError,
        TokenExpiredError, AuthError, NetworkError, HttpStatusError, CancelledError.
    """

def refresh_msa(
    http: Http, endpoints: AuthEndpoints, client_id: str, refresh_token: str, *,
    clock: Callable[[], float] = time.time, cancel: CancelToken | None = None,
) -> MsaTokens:
    """Exchange a Microsoft refresh token for a new one.

    Raises:
        TokenExpiredError: the endpoint answered `invalid_grant`.
        AuthError: any other OAuth error.
        NetworkError, HttpStatusError, CancelledError.
    """

def refresh(
    account: Account,
    client_id: str,
    http: Http,
    *,
    clock: Callable[[], float] = time.time,
    cancel: CancelToken | None = None,
) -> Account:
    """Renew an account silently with its Microsoft refresh token, re-running steps 2-5.

    Raises:
        ConfigError: empty client id, or an account with an unknown `auth_mode`.
        TokenExpiredError: the refresh token is empty, expired or rejected.
        XboxAccountError, NoJavaEditionError, AuthError, NetworkError,
        HttpStatusError, CancelledError.
    """

def ensure_fresh(
    account: Account,
    client_id: str,
    http: Http,
    *,
    within_seconds: float = REFRESH_MARGIN_SECONDS,
    store: AccountStore | None = None,
    clock: Callable[[], float] = time.time,
    cancel: CancelToken | None = None,
) -> Account:
    """Return the account, refreshing it first if its token expires within `within_seconds`.

    Raises:
        ConfigError, TokenExpiredError, XboxAccountError, NoJavaEditionError,
        AuthError, NetworkError, HttpStatusError, CancelledError.
    """
```

`sign_in`, normative. `client_id` is checked first: an empty string raises
`ConfigError` (`require_client_id` in section 8 is what callers use to produce it
from a `Config`). Step 1 is
`DeviceCodeSession(mode, client_id, http, clock=clock).wait_for_token(on_code=on_code,
cancel=cancel)`; steps 2 to 5 are `xbl_authenticate`, `xsts_authorize`,
`login_with_xbox` and `fetch_profile`, each given the endpoints or token the previous
step produced. The five steps report through `progress` as
`(label, step, 5)`, with these exact labels:

| Step | Label |
|---|---|
| 1 | `"Waiting for you to sign in"` |
| 2 | `"Signing in to Xbox Live"` |
| 3 | `"Checking your Xbox profile"` |
| 4 | `"Signing in to Minecraft"` |
| 5 | `"Loading your profile"` |

The returned `Account` carries `auth_mode=mode`, `xuid` from the XSTS `xid`,
`access_expires_at` from the Mojang token, and `refresh_token` /
`refresh_expires_at` from the Microsoft tokens. `sign_in` does **not** write to
`accounts.json`; the caller decides when to persist (the Account screen does it on
`TaskFinished`).

`refresh`, normative: `endpoints_for(account.auth_mode)` — the same family that
issued the tokens, never `config.auth_mode`, because switching modes in the config
must not silently reinterpret a stored refresh token. An empty `account.refresh_token`,
or a `refresh_expires_at` already in the past, raises `TokenExpiredError` without a
request. Otherwise: `refresh_msa`, then steps 2–5 again (a new XSTS token is needed
for a new XUID and a new Mojang token), and a new `Account` is returned with the
same `uuid` and the refreshed fields. The profile is re-fetched so a renamed
account shows its new name.

`ensure_fresh`, normative: returns `account` unchanged when
`not account.is_expired(now=clock(), within_seconds=within_seconds)`. Otherwise it
calls `refresh` and, when `store` is given, `store.upsert(refreshed)` before
returning. This is the proactive path from spec section 4.3 — the launcher refreshes
five minutes early rather than waiting for a 401 round-trip. The reactive path still
exists: a `TokenExpiredError` from `fetch_profile` or from the game-launch path is
handled by calling `refresh` once and retrying, and only then surfacing to the user.

### 10.9 Redaction

Every token this module handles is passed to `logsetup.REDACTOR.register` the
moment it is received or read from disk: the device code, both Microsoft tokens,
the XBL token, the XSTS token and the Mojang access token. No function in this
module logs a request or response body that has not been through
`REDACTOR.redact`. `Account.__repr__` is not customised — the dataclass repr does
contain tokens, so an account is never logged with `%r`; log `account.name` and
`account.uuid` instead.

---

## 11. `core/runtime.py`

The launcher installs its own JRE, so the whole thing runs on a clean machine with
no Java and no environment variables. The Java major version is a **parameter**,
taken from `core.versions.java_major(version_json)`; this module never decides it.

```python
ADOPTIUM_URL: Final[str] = "https://api.adoptium.net/v3/assets/feature_releases/{major}/ga"
ADOPTIUM_FIXED_QUERY: Final[dict[str, str]] = {
    "image_type": "jre",       # there is no "headless" image type; Minecraft needs AWT
    "vendor": "eclipse",
    "jvm_impl": "hotspot",
    "heap_size": "normal",
    "page_size": "1",
}
OS_MAP: Final[dict[str, str]] = {"win32": "windows", "linux": "linux", "darwin": "mac"}
ARCH_MAP: Final[dict[str, str]] = {
    "amd64": "x64", "x86_64": "x64", "x64": "x64",
    "arm64": "aarch64", "aarch64": "aarch64",
}
JAVA_VERSION_TIMEOUT: Final[float] = 15.0     # seconds for the `java -version` probe
```

All **seven** query parameters are sent on every call — `architecture`,
`image_type`, `os`, `vendor`, `jvm_impl`, `heap_size`, `page_size`. Omitting any of
them returns a huge paginated blob instead of the single binary this module wants.

```python
def adoptium_os(platform_name: str | None = None) -> str:
    """"windows" | "linux" | "mac" for the `os` query parameter.

    Raises:
        RuntimeProvisionError: the platform has no Adoptium name.
    """

def adoptium_arch(machine: str | None = None) -> str:
    """"x64" | "aarch64" for the `architecture` query parameter.

    Raises:
        RuntimeProvisionError: `platform.machine()` maps to no Adoptium architecture.
    """

def runtime_dir(paths: Paths, major: int) -> Path:
    """`runtimes/java-{major}/` — the same value as `paths.runtime_dir(major)`."""

def java_executable(paths: Paths, major: int) -> Path:
    """`runtimes/java-{major}/bin/java.exe` on Windows, `.../bin/java` elsewhere."""

def runtime_is_valid(
    paths: Paths, major: int, *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = JAVA_VERSION_TIMEOUT,
) -> bool:
    """True when the cached JRE exists and `java -version` exits 0. Never raises."""
```

`adoptium_os` uses `sys.platform` when `platform_name` is `None`; `adoptium_arch`
uses `platform.machine()` when `machine` is `None` and lower-cases it before the
lookup (`"AMD64"` on the dev machine → `"x64"`).

`runtime_is_valid`, normative: `java_executable(...)` must exist, then
`run([str(exe), "-version"], capture_output=True, text=True, timeout=timeout)` must
return code 0. Every exception (`OSError`, `subprocess.SubprocessError`,
`subprocess.TimeoutExpired`) is caught and returns `False`, because "the cached JRE
is unusable" is a normal outcome that triggers a reinstall, not an error to show.
`run` is injected so the check is testable without a JRE.

```python
@dataclass(frozen=True, slots=True)
class AdoptiumBinary:
    """The one JRE package the query selected."""
    name: str            # "OpenJDK25U-jre_x64_windows_hotspot_25.0.4.1_1.zip"
    link: str            # absolute download URL
    checksum: str        # 64 hex characters — SHA-256, not SHA-1
    size: int            # bytes
    release_name: str    # "jdk-25.0.4.1+1"

def query_adoptium(
    http: Http, major: int, *, os_name: str | None = None, arch: str | None = None,
    cancel: CancelToken | None = None,
) -> AdoptiumBinary:
    """Ask Adoptium for the current GA JRE for this Java major, OS and architecture.

    Raises:
        RuntimeProvisionError: no release, no matching binary, or a malformed response.
        NetworkError, HttpStatusError, CancelledError.
    """

def install_runtime(
    http: Http, paths: Paths, major: int, binary: AdoptiumBinary, *,
    progress: ProgressFn = null_progress, cancel: CancelToken | None = None,
) -> Path:
    """Download, verify, extract and atomically install a JRE into `runtimes/java-{major}/`.

    Raises:
        ChecksumError: the archive's SHA-256 does not match `binary.checksum`.
        RuntimeProvisionError: extraction failed, or the archive has no `bin/java`.
        NetworkError, HttpStatusError, CancelledError.
    """

def ensure_runtime(
    http: Http, paths: Paths, major: int, *,
    progress: ProgressFn = null_progress, cancel: CancelToken | None = None,
) -> Path:
    """The path to a working `java` for this major version, installing it if needed.

    Raises:
        RuntimeProvisionError, ChecksumError, NetworkError, HttpStatusError, CancelledError.
    """
```

`query_adoptium`, normative: `http.get_json(ADOPTIUM_URL.format(major=major),
params={**ADOPTIUM_FIXED_QUERY, "os": os_name or adoptium_os(), "architecture":
arch or adoptium_arch()})`. The response is a JSON **list**; an empty list raises
`RuntimeProvisionError` naming the major, OS and architecture. From element 0 it
takes `release_name` and scans `binaries` for the first entry whose `image_type`,
`os` and `architecture` all match the query, then reads that entry's `package`
object for `name`, `link`, `checksum` and `size`. A missing `package`, `link` or
`checksum` raises `RuntimeProvisionError`. **The `checksum` field is SHA-256**
(64 hex characters), not the SHA-1 used everywhere else in the launcher.

`install_runtime`, normative — every step of the atomicity requirement:

1. Progress is split with a `Reporter`: download `0.00–0.85`, extract `0.85–0.97`,
   install `0.97–1.00`.
2. Download the archive to `paths.runtimes / binary.name` (streamed through the
   usual `.part` file) via `http.download(binary.link, archive,
   expected_hash=binary.checksum, algorithm="sha256", expected_size=binary.size,
   progress=..., cancel=...)`. Verification therefore happens **before** anything
   is extracted, and a re-run reuses an already-downloaded archive.
3. Extract into a fresh temporary directory `paths.runtimes / f".java-{major}.tmp"`,
   deleting it first if a previous run left it behind. The extractor is chosen by
   the archive name: `.zip` → `zipfile.ZipFile`; `.tar.gz` or `.tgz` →
   `tarfile.open(mode="r:gz")`; anything else raises `RuntimeProvisionError`.
   Windows ships `.zip` and Linux/macOS ship `.tar.gz`, so both paths are real.
4. Every member name is checked before it is written: a member whose resolved
   destination is not inside the temporary directory (absolute paths, `..`
   segments, symlinks pointing outside) is skipped and logged at WARNING.
5. Flatten. Archives contain exactly one top-level directory (for example
   `jdk-25.0.4.1+1-jre/`). If the temporary directory has exactly one entry and it
   is a directory, that becomes the install root. Then, if
   `root / "Contents" / "Home"` exists, **that** becomes the install root — this is
   the macOS layout, where the real `bin/java` is at
   `<top>/Contents/Home/bin/java`.
6. Verify `root / "bin" / ("java.exe" if Windows else "java")` exists; if not,
   raise `RuntimeProvisionError`.
7. On POSIX, call `posix_chmod_755` on **every file in `root/"bin"`**. `zipfile`
   does not preserve the executable bit, so a JRE extracted from a `.zip` on Linux
   or macOS is unusable without this; the chmod runs for both archive kinds so
   there is one code path.
8. Install atomically: if `runtime_dir(paths, major)` exists, `os.replace` it to
   `paths.runtimes / f".java-{major}.old"` and delete that afterwards; then
   `os.replace(root, runtime_dir(paths, major))`. A half-extracted tree is never
   visible under the real name, so the next launch can never mistake one for a
   working JRE.
9. Clean up the temporary directory and the archive. A cleanup failure is logged
   at WARNING and ignored.
10. `OSError`, `zipfile.BadZipFile`, `tarfile.TarError` and `shutil.Error` are
    wrapped in `RuntimeProvisionError`. `ChecksumError` and `CancelledError`
    propagate unwrapped.

`ensure_runtime`, normative: when `runtime_is_valid(paths, major)` it reports
`progress(f"Java {major} is ready", 1, 1)` and returns `java_executable(...)`
without any network call. Otherwise it runs `query_adoptium` then `install_runtime`,
re-checks `runtime_is_valid`, and raises `RuntimeProvisionError` if the freshly
installed runtime still does not answer `java -version`.

---

## 12. `core/libraries.py`

```python
MAX_WORKERS: Final[int] = 16
LIBRARY_BASE_URL: Final[str] = "https://libraries.minecraft.net/"
NATIVE_CLASSIFIER_PREFIX: Final[str] = "natives-"
```

### 12.1 Platform and rules

```python
def current_os_name() -> str:
    """Mojang's OS name for this machine: "windows" | "linux" | "osx"."""

def current_arch() -> str:
    """Mojang's architecture name for this machine: "x64" | "x86" | "arm64"."""

def os_version_string() -> str:
    """The string an `os.version` rule regex is matched against (`platform.release()`)."""

def rules_allow(
    rules: Sequence[Mapping[str, Any]] | None,
    os_name: str,
    arch: str,
    os_version: str,
    features: Mapping[str, bool],
) -> bool:
    """Evaluate a Mojang `rules` array for this OS, architecture, OS version and feature set."""
```

`current_os_name` maps `sys.platform`: `"win32"` → `"windows"`, `"darwin"` →
`"osx"`, everything else → `"linux"`. `current_arch` maps a lower-cased
`platform.machine()`: `"amd64"`/`"x86_64"` → `"x64"`, `"arm64"`/`"aarch64"` →
`"arm64"`, `"i386"`/`"i686"`/`"x86"` → `"x86"`, anything else → `"x64"`.

`rules_allow`, normative — this is the algorithm, and getting it wrong either drops
LWJGL or leaks `--quickPlayPath ${quickPlayPath}` into argv:

1. `rules` that is `None` or empty → **allow**. This is the common case: most
   libraries and most argument strings have no rules at all.
2. Otherwise start from **deny** and walk the rules in order. Each rule that
   *applies* sets the result to `rule["action"] == "allow"`. The last applying rule
   wins. Rules present and none applying → **deny**.
3. A rule applies when every condition it carries matches:
   - `os.name` — equal to `os_name`.
   - `os.arch` — equal to `arch`.
   - `os.version` — `re.search(pattern, os_version)` finds a match.
   - `features` — for every key in the mapping, `features.get(key, False)` equals
     the rule's value. A feature the launcher does not know about is `False`, so a
     rule requiring it does not apply.
4. A rule carrying a condition key this function does not understand does **not**
   apply (fail closed).
5. A rule with no conditions at all applies unconditionally — this is how the
   `{"action": "allow"}` + `{"action": "disallow", "os": {...}}` pattern works.

`features` is always supplied; section 15's `Features` dataclass is the source, and
all six flags default to `False`.

### 12.2 Maven coordinates

```python
def maven_path(gav: str) -> str:
    """Repository-relative path for a Maven GAV, using "/" separators.

    Raises:
        ManifestError: `gav` has fewer than three colon-separated components.
    """

def maven_url(base: str, gav: str) -> str:
    """`base` (with a trailing "/" ensured) joined to `maven_path(gav)`."""

def is_native_classifier(name: str) -> bool:
    """True when a Maven GAV's classifier starts with "natives-"."""
```

`maven_path` normative: split `gav` on `":"`. The first three components are
group, artifact and version; a fourth, when present, is the classifier. If the last
component contains `"@"`, the text after it is the file extension and the text
before it stays part of that component; the extension defaults to `"jar"`. The
result is
`group.replace(".", "/") + "/" + artifact + "/" + version + "/" + artifact + "-" + version + ("-" + classifier if classifier else "") + "." + extension`.
So `org.ow2.asm:asm:9.10.1` → `org/ow2/asm/asm/9.10.1/asm-9.10.1.jar`, and
`com.mojang:jtracy:1.0.37:natives-linux` →
`com/mojang/jtracy/1.0.37/jtracy-1.0.37-natives-linux.jar`.

`is_native_classifier("com.mojang:jtracy:1.0.37:natives-linux")` is `True`;
`is_native_classifier("org.ow2.asm:asm:9.10.1")` is `False`.

### 12.3 `Library`

```python
@dataclass(frozen=True, slots=True)
class Library:
    """One resolved library: where it comes from, where it goes, and what it is for."""
    name: str                                   # the Maven GAV as written in the JSON
    path: str                                   # repository-relative, "/" separated
    url: str                                    # absolute download URL ("" when unknown)
    sha1: str = ""                              # "" means "hash not known yet"
    size: int = 0                               # 0 means "size not known"
    on_classpath: bool = True
    extract_to_natives: bool = False
    extract_exclude: tuple[str, ...] = ()

    @property
    def group_artifact(self) -> str:
        """"group:artifact" — the de-duplication key used by `core.fabric.merge_profile`."""
```

### 12.4 Selection

```python
def select_libraries(
    version_json: Mapping[str, Any],
    *,
    os_name: str | None = None,
    arch: str | None = None,
    os_version: str | None = None,
    features: Mapping[str, bool] | None = None,
) -> list[Library]:
    """Every library this machine needs, in version-JSON order.

    Raises:
        ManifestError: `libraries` is missing, or an entry has neither `downloads`
            nor a usable `name`.
    """

def library_local_path(paths: Paths, library: Library) -> Path:
    """`libraries/` joined with the library's repository-relative path."""
```

`select_libraries`, normative. Defaults: `os_name = current_os_name()`,
`arch = current_arch()`, `os_version = os_version_string()`, `features = {}`.
Entries are walked in order and each produces zero, one or two `Library` objects:

1. `rules_allow(entry.get("rules"), ...)` is `False` → the entry is skipped entirely.
2. **Legacy natives model.** The entry has both `downloads.classifiers` and a
   `natives` map, and `natives` has a key equal to `os_name`. The classifier key is
   `natives[os_name]` with `${arch}` replaced by `"32"` when `arch == "x86"` and
   `"64"` otherwise. `downloads.classifiers[key]` yields a `Library` with
   `on_classpath=False`, `extract_to_natives=True` and
   `extract_exclude=tuple(entry.get("extract", {}).get("exclude", []))`. If the
   same entry also has `downloads.artifact`, that artifact is emitted as well, as
   an ordinary classpath library.
3. **Modern model.** The entry has `downloads.artifact` → one ordinary
   `Library(on_classpath=True)` built from `path`, `url`, `sha1` and `size`.
   This is the branch that handles `natives-*` Maven classifiers on 1.19+ and every
   26.x version: they are ordinary libraries with a normal `downloads.artifact`,
   gated by an OS rule, and **they belong on the classpath**. There is no
   extraction and no `natives` map anywhere in a modern version JSON — 26.2 has
   131 libraries and zero `downloads.classifiers`.
4. **Fabric-style entry.** The entry has no `downloads` block at all, only `name`
   and (usually) `url`. The path is `maven_path(name)`, the URL is
   `maven_url(entry.get("url") or LIBRARY_BASE_URL, name)`, `sha1` is
   `entry.get("sha1", "")` and `size` is `entry.get("size", 0)`. Writing
   `entry["downloads"]["artifact"]["url"]` here raises `KeyError` on every Fabric
   library; this branch is why `fabric-merged.json` can be handed straight to
   `select_libraries`.

A `Library` whose `sha1` is `""` is legal and means "hash not known from the
metadata"; `download_libraries` resolves it through `sha1_lookup`.

### 12.5 Downloading

```python
def download_libraries(
    http: Http,
    paths: Paths,
    libraries: Sequence[Library],
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    max_workers: int = MAX_WORKERS,
    executor_factory: Callable[[int], concurrent.futures.Executor] | None = None,
    sha1_lookup: Callable[[Library], str] | None = None,
) -> list[Path]:
    """Fetch every library that is missing or whose SHA-1 does not match, in parallel.

    Raises:
        ChecksumError: a downloaded library does not match its published SHA-1.
        NetworkError, HttpStatusError, CancelledError, OSError.
    """

def download_client_jar(
    http: Http, paths: Paths, version_json: Mapping[str, Any], version_id: str, *,
    progress: ProgressFn = null_progress, cancel: CancelToken | None = None,
) -> Path:
    """Fetch (or reuse) `versions/{id}/client.jar`, verified against `downloads.client.sha1`.

    Raises:
        ManifestError: the version JSON has no `downloads.client`.
        ChecksumError, NetworkError, HttpStatusError, CancelledError.
    """
```

`download_libraries`, normative:

- The pool is a `concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers,
  MAX_WORKERS))`. `executor_factory(workers)` overrides construction so a test can
  assert the cap without spawning threads. The cap is 16 and pairs with the
  session's `pool_maxsize=32` (section 7): the default urllib3 pool of 10 would
  throttle 16 workers and emit warnings.
- Each job downloads one library to `library_local_path(paths, library)` with
  `http.download(library.url, dest, expected_hash=<sha1>, algorithm="sha1",
  expected_size=library.size or None, label=Path(library.path).name)`. Because
  `Http.download` skips a file whose hash already matches, a second launch does no
  network I/O at all.
- When `library.sha1` is `""` and `sha1_lookup` is given, the worker calls
  `sha1_lookup(library)` first and uses whatever it returns; `""` means "verify
  nothing", and then existence alone is the skip test. `core/pipeline.py` passes
  `core.fabric.library_sha1_lookup(http)` so Fabric's `.sha1` sidecars are fetched
  lazily and only for the libraries that actually need them.
- `progress` is called **only from the thread that called `download_libraries`**,
  as futures complete, never from a worker: `progress(name, completed, total)`
  where `total` is `len(libraries)`. `ProgressFn` implementations are not required
  to be thread-safe.
- `check_cancel(cancel)` runs before each submission and after each completion. On
  cancellation, pending futures are cancelled, the executor is shut down, and
  `CancelledError` propagates.
- The first worker exception is re-raised after the executor has been shut down;
  remaining futures are cancelled. Nothing is swallowed.
- Returns the local paths of every library in `libraries`, in input order,
  including the ones that were already present.

### 12.6 Natives and the classpath

```python
def extract_natives(
    paths: Paths,
    libraries: Sequence[Library],
    natives_dir: Path,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> Path:
    """Unpack every legacy natives jar into the instance's natives directory.

    Raises:
        LaunchError: a natives jar is missing or is not a readable zip.
        CancelledError, OSError.
    """

def build_classpath(
    paths: Paths,
    libraries: Sequence[Library],
    client_jar: Path,
    *,
    separator: str | None = None,
) -> str:
    """The `-cp` value: every classpath library in order, then the client jar last."""
```

`extract_natives`, normative:

1. `natives_dir.mkdir(parents=True, exist_ok=True)` runs **first and always**, even
   when no library needs extracting. Modern versions extract nothing, but the
   directory is still passed as `-Djava.library.path`, and a missing directory
   there is a launch failure.
2. For each library with `extract_to_natives=True`, open
   `library_local_path(paths, library)` with `zipfile.ZipFile` and write out every
   member except: directory entries; members whose name starts with any string in
   `library.extract_exclude` (this is the `extract.exclude` list, almost always
   `["META-INF/"]`); and members whose resolved destination would fall outside
   `natives_dir`, which are skipped and logged at WARNING.
3. Existing files are overwritten — a natives directory is disposable.
4. `progress(library name, completed, total)` per jar, from the calling thread.
5. `zipfile.BadZipFile` and a missing jar are wrapped in `LaunchError`.

`build_classpath`, normative: the entries are `library_local_path(paths, lib)` for
every library with `on_classpath=True`, in the order `select_libraries` produced
them — which, for a Fabric launch, is Fabric's libraries first and Mojang's after
(section 13). Duplicate paths are dropped, keeping the first occurrence. The client
jar is appended **last**. `separator` defaults to `";"` on Windows
(`sys.platform == "win32"`) and `":"` everywhere else, matching
`${classpath_separator}` in section 15.

---

## 13. `core/fabric.py`

```python
FABRIC_META: Final[str] = "https://meta.fabricmc.net/v2"
FABRIC_LOADER_URL: Final[str] = "https://meta.fabricmc.net/v2/versions/loader/{game_version}"
FABRIC_PROFILE_URL: Final[str] = (
    "https://meta.fabricmc.net/v2/versions/loader/{game_version}/{loader_version}/profile/json"
)
FABRIC_MAVEN: Final[str] = "https://maven.fabricmc.net/"
FABRIC_EXPECTED_MAIN_CLASS: Final[str] = "net.fabricmc.loader.impl.launch.knot.KnotClient"
FABRIC_MERGED_NAME: Final[str] = "fabric-merged.json"
```

### 13.1 Loader selection

```python
@dataclass(frozen=True, slots=True)
class LoaderEntry:
    """One entry of the Fabric loader list for a game version."""
    version: str                 # loader.version, e.g. "0.19.5"
    build: int                   # loader.build
    maven: str                   # loader.maven, e.g. "net.fabricmc:fabric-loader:0.19.5"
    stable: bool                 # loader.stable
    intermediary_version: str    # intermediary.version, "" when absent

def fetch_loader_versions(
    http: Http, game_version: str, *, cancel: CancelToken | None = None
) -> list[LoaderEntry]:
    """The Fabric loader list for a Minecraft version, newest first.

    Raises:
        ManifestError: the response is not a non-empty list of loader entries.
        NetworkError, HttpStatusError, CancelledError.
    """

def choose_loader(entries: Sequence[LoaderEntry]) -> LoaderEntry:
    """The first entry with `stable` true, falling back to entry 0.

    Raises:
        ManifestError: `entries` is empty.
    """

def fetch_profile(
    http: Http, game_version: str, loader_version: str, *, cancel: CancelToken | None = None
) -> dict[str, Any]:
    """The Fabric launcher profile JSON for one game/loader pair.

    Raises:
        ManifestError: the response is not a JSON object with `libraries` and `mainClass`.
        NetworkError, HttpStatusError, CancelledError.
    """
```

An empty loader list means Fabric has nothing for this Minecraft version;
`fetch_loader_versions` raises `ManifestError` with the user message
"Fabric doesn't support Minecraft {game_version} yet. Pick another version."

### 13.2 Fabric libraries have no `downloads` block

This is the single most common way a launcher crashes on Fabric. A profile library
entry looks like this — `name`, `url`, and inline hashes, with no `downloads`
anywhere:

```json
{
  "name": "org.ow2.asm:asm:9.10.1",
  "url": "https://maven.fabricmc.net/",
  "md5": "…",
  "sha1": "ada2141c0cc52ee8f5c48cd5fa4ce0e794f22236",
  "sha256": "…",
  "sha512": "…",
  "size": 126151
}
```

```python
def fabric_library_url(lib: Mapping[str, Any]) -> tuple[str, str]:
    """(jar URL, jar URL + ".sha1") built from the entry's `name` and `url`.

    Raises:
        ManifestError: the entry has no usable `name`.
    """

def fetch_sha1_sidecar(http: Http, jar_url: str, *, cancel: CancelToken | None = None) -> str:
    """GET `{jar_url}.sha1` and return the 40-character digest it contains, or "" on 404."""

def fabric_library_sha1(
    http: Http, lib: Mapping[str, Any], *, cancel: CancelToken | None = None
) -> str:
    """The entry's inline `sha1` when it has one, otherwise the `.sha1` sidecar."""

def library_sha1_lookup(http: Http) -> Callable[[Library], str]:
    """The `sha1_lookup` callable `core.libraries.download_libraries` expects."""
```

`fabric_library_url` builds the jar URL as
`maven_url(lib.get("url") or FABRIC_MAVEN, lib["name"])` — that is,
`{url}{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar` —
and appends `".sha1"` for the sidecar. `fetch_sha1_sidecar` requests the sidecar with
`raise_for_status=False`, strips the response text and takes its first
whitespace-separated field (some Maven repositories append a filename); a non-200
response or a value that is not 40 hex characters returns
`""` rather than raising, because an unverifiable library is still installable and
the failure mode of refusing to launch is worse. The returned callable from
`library_sha1_lookup` fetches `library.url + ".sha1"` and is called only for
libraries whose `sha1` is `""`.

### 13.3 Version comparison — libraries only

```python
def compare_versions(a: str, b: str) -> int:
    """-1, 0 or 1 comparing two Maven library versions (dotted-numeric, non-numeric fallback)."""
```

Normative: split each string on the regex `[._+\-]`. Compare component by
component; a component that is all digits compares as an integer, and a numeric
component sorts **above** a non-numeric one at the same position; two non-numeric
components compare as strings. A missing component (one version is shorter) is
treated as `0`. `9.10.1` > `9.7.1`; `0.19.5` > `0.19.5-beta.1`.

> **This function is for `group:artifact` de-duplication and nothing else.**
> Minecraft game versions are ordered by manifest index in `core/versions.py`
> (section 9). `26.2` is newer than `1.21.11`, and no dotted-numeric comparator
> gets that right. Never call `compare_versions` on a game version.

### 13.4 Merging

```python
def merge_profile(
    vanilla_json: Mapping[str, Any], fabric_json: Mapping[str, Any]
) -> dict[str, Any]:
    """Combine a Mojang version JSON and a Fabric profile into one launchable document.

    Raises:
        ManifestError: `vanilla_json` has no `arguments` block, or the profile has no
            `mainClass`.
    """

def write_merged_profile(paths: Paths, version_id: str, merged: Mapping[str, Any]) -> Path:
    """Write `versions/{version_id}/fabric-merged.json` atomically and return its path.

    Raises:
        ConfigError: the file cannot be written.
    """
```

`merge_profile`, normative:

1. The result starts as a deep copy of `vanilla_json`, so `assetIndex`, `assets`,
   `downloads`, `javaVersion`, `type` and `releaseTime` all come from Mojang.
   `inheritsFrom` is removed from the result — the merge has resolved it. The
   `logging` block is copied but never used (section 0 amendment).
2. `id` becomes `fabric_json["id"]` (for example `fabric-loader-0.19.5-26.2`).
   This is what `${version_name}` gets at launch.
3. `mainClass` comes from `fabric_json["mainClass"]`. When it differs from
   `FABRIC_EXPECTED_MAIN_CLASS` a warning is logged and **the profile's value is
   still used**. It is never hardcoded.
4. Libraries: the merged list is `fabric_json["libraries"]` first, then
   `vanilla_json["libraries"]`, de-duplicated by `group:artifact` — the first two
   colon-separated components of `name`. When both lists contain the same
   `group:artifact`, the entry whose version is higher per `compare_versions` wins;
   ties keep the Fabric entry, because Fabric intentionally overrides some Mojang
   libraries. The winner keeps the position of the first occurrence, so Fabric's
   libraries stay ahead of Mojang's and therefore come first on the classpath. An
   entry whose `name` has fewer than two components is keyed by the whole name.
5. `arguments`: `game` is vanilla's game list followed by the profile's, and `jvm`
   is vanilla's jvm list followed by the profile's. The profile's
   `"-DFabricMcEmu= net.minecraft.client.main.Main "` is **one argv element** and
   its unusual internal spacing is preserved verbatim — it is not split, stripped
   or normalised.
6. A `vanilla_json` with no `arguments` block (pre-1.13 versions, which carry a
   `minecraftArguments` string instead) raises `ManifestError` with the user
   message "Fabric doesn't support Minecraft {id}. Pick 1.14 or newer.", as the
   section 0 amendment requires. The version dropdown lists every release, so this
   is a real path and it must fail clearly rather than crash.

`write_merged_profile` writes to `paths.fabric_merged_json(version_id)`, where
`version_id` is the **vanilla** id (`26.2`), so the file lands at
`versions/26.2/fabric-merged.json` as spec section 10 requires. The merged document
is what `core.libraries.select_libraries` is then given, and its Fabric-style
entries are handled by branch 4 of section 12.4.

---

## 14. `core/assets.py`

```python
RESOURCES_BASE_URL: Final[str] = "https://resources.download.minecraft.net/"
MAX_WORKERS: Final[int] = 16
```

```python
@dataclass(frozen=True, slots=True)
class AssetObject:
    """One entry of an asset index."""
    name: str          # the index key, e.g. "icons/icon_128x128.png"
    hash: str          # 40-character SHA-1
    size: int

    @property
    def sub_path(self) -> str:
        """`{hash[:2]}/{hash}` — the layout under both `assets/objects/` and the CDN."""

    @property
    def url(self) -> str:
        """`RESOURCES_BASE_URL + sub_path`."""

def fetch_asset_index(
    http: Http, paths: Paths, version_json: Mapping[str, Any], *,
    progress: ProgressFn = null_progress, cancel: CancelToken | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch (or reuse) `assets/indexes/{id}.json` and return (index id, decoded index).

    Raises:
        ManifestError: `assetIndex` is missing, or the index is not a JSON object.
        ChecksumError, NetworkError, HttpStatusError, CancelledError.
    """

def parse_asset_index(index_json: Mapping[str, Any]) -> list[AssetObject]:
    """Every object in an asset index, sorted by name for a stable progress order.

    Raises:
        ManifestError: `objects` is missing or an entry has no `hash`.
    """

def asset_object_path(paths: Paths, obj: AssetObject) -> Path:
    """`assets/objects/{hash[:2]}/{hash}` — the same value as `paths.asset_object_path`."""

def download_assets(
    http: Http,
    paths: Paths,
    objects: Sequence[AssetObject],
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    max_workers: int = MAX_WORKERS,
    executor_factory: Callable[[int], concurrent.futures.Executor] | None = None,
) -> int:
    """Fetch every missing or mismatched asset object in parallel; returns bytes downloaded.

    Raises:
        ChecksumError, NetworkError, HttpStatusError, CancelledError, OSError.
    """

def is_virtual(index_json: Mapping[str, Any]) -> bool:
    """The index's `virtual` flag (absent means False)."""

def maps_to_resources(index_json: Mapping[str, Any]) -> bool:
    """The index's `map_to_resources` flag (absent means False)."""

def materialise_assets(
    paths: Paths,
    objects: Sequence[AssetObject],
    target_dir: Path,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> Path:
    """Copy hashed objects to their human names under `target_dir`, for virtual indexes.

    Raises:
        CancelledError, OSError.
    """

def game_assets_dir(
    paths: Paths,
    index_id: str,
    index_json: Mapping[str, Any],
    instance: InstancePaths,
) -> Path:
    """The directory `${game_assets}` points at for this index."""
```

`fetch_asset_index`, normative: reads `version_json["assetIndex"]` for `id`, `url`,
`sha1` and `size` (26.2: id `"32"`, 5,057 objects, `totalSize` 480 MB), downloads
it to `paths.asset_index_path(id)` with `http.download(..., expected_hash=sha1,
algorithm="sha1", expected_size=size)`, then reads it. The index id is a string —
`"32"` — and is never coerced to an integer; it becomes `${assets_index_name}`.

`download_assets`, normative:

- Same pool discipline as `download_libraries`: `ThreadPoolExecutor` capped at
  `MAX_WORKERS` (16), an injectable `executor_factory`, `check_cancel(cancel)`
  before each submission and after each completion, the first worker exception
  re-raised after shutdown, and `progress` called only from the calling thread.
- Skip test per object: the file exists **and** `st_size == obj.size` **and** its
  SHA-1 equals `obj.hash`. A size mismatch short-circuits to "re-download" without
  hashing. With ~5,000 objects this is the difference between three seconds and
  three minutes on every relaunch.
- Progress counts objects and bytes at once: `progress(label, completed_objects,
  len(objects))` where `label` is
  `f"Assets — {format_bytes(bytes_done)} of {format_bytes(total_bytes)}"` and
  `total_bytes` is the sum of the sizes of the objects that actually need
  downloading. The determinate bar therefore tracks files while the label stays
  honest about the ~400 MB first launch.
- Returns the number of bytes actually downloaded (0 on a warm cache).

`materialise_assets` and `game_assets_dir` handle the `virtual` and
`map_to_resources` flags. Current indexes set neither — 26.2's index has only
`objects` — but the flags are honoured anyway, per spec section 6.4:

| Index flags | `${game_assets}` | Extra work |
|---|---|---|
| neither | `paths.assets` (the assets root) | none |
| `virtual` true | `paths.virtual_assets_dir(index_id)` | `materialise_assets` into that directory |
| `map_to_resources` true | `instance.resources` | `materialise_assets` into that directory |

`materialise_assets` copies `assets/objects/{h[:2]}/{h}` to `target_dir / obj.name`,
creating parent directories, skipping any destination that already exists with the
same size, and writing through a `.part` file followed by `os.replace` so an
interrupted copy never leaves a truncated resource. `check_cancel(cancel)` runs once
per object and `progress(obj.name, completed, total)` is reported per object.
When both flags are set, `map_to_resources` wins.

---

## 15. `core/launch.py`

### 15.1 Features

```python
@dataclass(frozen=True, slots=True)
class Features:
    """The six feature flags a Mojang `features` rule can test. All default to False."""
    is_demo_user: bool = False
    has_custom_resolution: bool = False
    has_quick_plays_support: bool = False
    is_quick_play_singleplayer: bool = False
    is_quick_play_multiplayer: bool = False
    is_quick_play_realms: bool = False

    def as_mapping(self) -> dict[str, bool]:
        """The six flags as the mapping `rules_allow` expects."""

DEFAULT_FEATURES: Final[Features] = Features()
USER_TYPE: Final[str] = "msa"
PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\$\{([^}]*)\}")
LEGACY_JVM_ARGS: Final[tuple[str, ...]] = (
    "-Djava.library.path=${natives_directory}",
    "-Dminecraft.launcher.brand=${launcher_name}",
    "-Dminecraft.launcher.version=${launcher_version}",
    "-cp",
    "${classpath}",
)
```

Feature rules must be evaluated, not skipped. `arguments.game` contains entries
like `{"rules": [{"action": "allow", "features": {"has_quick_plays_support": true}}],
"value": ["--quickPlayPath", "${quickPlayPath}"]}`. A launcher that ignores
`features` rules puts `--quickPlayPath ${quickPlayPath}` on the command line and
the game fails to start. With all six flags `False`, every such entry is dropped
and no quick-play variable is ever needed.

### 15.2 Argument evaluation and substitution

```python
def evaluate_arguments(
    arguments: Sequence[Any],
    os_name: str,
    arch: str,
    os_version: str,
    features: Mapping[str, bool],
) -> list[str]:
    """Flatten one `arguments.jvm` or `arguments.game` array, keeping only allowed entries.

    Raises:
        ManifestError: an element is neither a string nor an object with a `value`.
    """

def substitute(args: Sequence[str], variables: Mapping[str, str]) -> list[str]:
    """Replace every `${name}` with its value.

    Raises:
        UnresolvedPlaceholderError: any `${…}` survives substitution.
    """
```

`evaluate_arguments`, normative: a `str` element is kept verbatim. An object
element is kept when `rules_allow(element.get("rules"), os_name, arch, os_version,
features)` is true, and its `value` is appended — a string as one element, a list
flattened in order. A rejected element contributes nothing. Any other element type
raises `ManifestError`.

`substitute`, normative: each argument has every `${name}` occurrence replaced by
`variables[name]`. A name that is **not** in `variables` is left in place, exactly
so the next step catches it. After all replacements, the result is scanned with
`PLACEHOLDER_PATTERN`; if any argument still contains a `${…}`, the distinct names
are collected, sorted, and `UnresolvedPlaceholderError(tuple(names))` is raised.
An unresolved placeholder is a guaranteed confusing crash several seconds later,
so the launcher refuses to spawn the process instead.

### 15.3 Variables

```python
def build_variables(
    *,
    account: Account,
    version_name: str,
    version_type: str,
    asset_index_id: str,
    game_dir: Path,
    assets_root: Path,
    game_assets: Path,
    natives_dir: Path,
    library_dir: Path,
    classpath: str,
    clientid: str,
    resolution: tuple[int, int] | None = None,
    launcher_name: str = LAUNCHER_NAME,
    launcher_version: str = LAUNCHER_VERSION,
    separator: str | None = None,
) -> dict[str, str]:
    """The complete substitution map from spec section 7. Every value is a string."""
```

The complete set — all twenty names, no more and no fewer:

| Variable | Value |
|---|---|
| `auth_player_name` | `account.name` |
| `version_name` | the launched version id: the vanilla id for a vanilla launch, the merged profile's `id` (`fabric-loader-0.19.5-26.2`) for Fabric |
| `game_directory` | `str(game_dir)` — the instance directory |
| `assets_root` | `str(assets_root)` — `paths.assets` |
| `game_assets` | `str(game_assets)` — from `core.assets.game_assets_dir` |
| `assets_index_name` | `asset_index_id`, the index id as a string (`"32"`) |
| `auth_uuid` | `account.uuid` — 32 hex characters, no dashes |
| `auth_access_token` | `account.access_token` |
| `auth_xuid` | `account.xuid` — the `xid` from XSTS `DisplayClaims` (section 10.7) |
| `clientid` | `config.clientid` — the stable per-install UUID from `config.json` |
| `user_type` | `USER_TYPE`, which is `"msa"`. Not `"mojang"`, not `"legacy"` |
| `version_type` | the version JSON's `type` (`"release"`, `"snapshot"`) |
| `classpath` | the joined classpath from `core.libraries.build_classpath` |
| `classpath_separator` | `";"` on Windows, `":"` elsewhere |
| `natives_directory` | `str(natives_dir)` — the instance's `natives/` |
| `library_directory` | `str(library_dir)` — `paths.libraries` |
| `launcher_name` | `LAUNCHER_NAME`, `"MaestroLauncher"` |
| `launcher_version` | `LAUNCHER_VERSION`, `"1.0"` |
| `resolution_width` | `str(resolution[0])` when `resolution` is given, else `""` |
| `resolution_height` | `str(resolution[1])` when `resolution` is given, else `""` |

`resolution` is `None` unless `Features.has_custom_resolution` is set, and the two
resolution variables only ever appear inside an argument gated by that feature.
`separator` overrides `${classpath_separator}`; `None` means `";"` on Windows and
`":"` everywhere else, which is the same rule `core.libraries.build_classpath` uses,
so the two can never disagree.

### 15.4 Memory and the plan

```python
def memory_flags(memory_gb: int) -> list[str]:
    """`["-XmxNG", "-XmsNG"]` — equal min and max, which avoids heap-resize stutter."""
```

`memory_gb` is clamped to at least 1; `core/config.py` (section 8) is what clamps
it to `[MIN_MEMORY_GB, max_memory_gb()]` when the slider moves. The default is 6,
so the default flags are `["-Xmx6G", "-Xms6G"]`.

```python
@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """Everything `process.GameProcess` needs to start the game, and nothing else."""
    java: Path
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    version_id: str = ""
    instance_name: str = ""

    def redacted_argv(self) -> tuple[str, ...]:
        """`argv` with tokens replaced by `[redacted]` — the only form that may be logged."""

def build_launch_plan(
    *,
    java: Path,
    version_json: Mapping[str, Any],
    main_class: str,
    variables: Mapping[str, str],
    memory_gb: int,
    game_dir: Path,
    version_id: str = "",
    instance_name: str = "",
    os_name: str | None = None,
    arch: str | None = None,
    os_version: str | None = None,
    features: Features = DEFAULT_FEATURES,
    extra_jvm_args: Sequence[str] = (),
    extra_game_args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> LaunchPlan:
    """Assemble the final argv from a (possibly Fabric-merged) version JSON.

    Raises:
        UnresolvedPlaceholderError: a `${…}` survived substitution anywhere in argv.
        ManifestError: the version JSON has neither `arguments` nor `minecraftArguments`.
    """
```

`build_launch_plan`, normative. argv is built in exactly this order:

1. `str(java)`.
2. `memory_flags(memory_gb)`.
3. The JVM arguments. When `core.versions.has_modern_arguments(version_json)` is
   true, that is `evaluate_arguments(version_json["arguments"]["jvm"], …)`;
   otherwise it is `list(LEGACY_JVM_ARGS)`. Either way the result goes through
   `substitute`.
4. `substitute(extra_jvm_args, variables)`.
5. `main_class` — from the Fabric profile for a Fabric launch (section 13), from
   `core.versions.main_class` for a vanilla one. Never hardcoded.
6. The game arguments: `evaluate_arguments(version_json["arguments"]["game"], …)`
   for a modern version, or `version_json["minecraftArguments"].split()` for a
   legacy one; then `substitute`.
7. `substitute(extra_game_args, variables)`.

The `logging` block's `-Dlog4j.configurationFile=${path}` argument is **never**
added. That configuration makes the game emit XML log events on stdout, which the
plain-text log reader in section 19 would render as XML soup; without it the game
uses its bundled plain-text log4j config. This is the section 0 amendment and it
is a deliberate omission, not an oversight.

After assembly the complete argv is scanned once more with `PLACEHOLDER_PATTERN`
and `UnresolvedPlaceholderError` is raised if anything survives — `substitute`
already guarantees it for the parts it processed, and this second pass covers
`main_class` and anything a caller injected.

`env` defaults to `dict(os.environ)`; when a mapping is given it is **merged over**
the inherited environment rather than replacing it, so the game keeps `PATH`,
`DISPLAY` and the user's locale.

`redacted_argv()` returns `tuple(REDACTOR.redact(a) for a in argv)`. The Mojang
access token is an ordinary element of argv (`--accessToken`), so the raw `argv` is
never written to the log, never shown in a crash panel and never copied by the
"copy log" button. Every log line that mentions the command uses this method.

---

## 16. `core/modrinth.py`

Everything the launcher knows about Modrinth lives here: search, version resolution,
transitive dependency planning, verified install, and the management of the jars that
end up in `instances/{name}/mods/`. This module returns **raw bytes** for icons and
plain dataclasses for everything else; it imports neither `PIL` nor `tkinter` nor
`customtkinter` (ruling 2).

```python
MODRINTH_API: Final[str] = "https://api.modrinth.com/v2"
SEARCH_URL: Final[str] = "https://api.modrinth.com/v2/search"
PROJECT_URL: Final[str] = "https://api.modrinth.com/v2/project/{project}"
PROJECT_VERSIONS_URL: Final[str] = "https://api.modrinth.com/v2/project/{project}/version"
VERSION_URL: Final[str] = "https://api.modrinth.com/v2/version/{version_id}"

USER_AGENT: Final[str] = core.net.USER_AGENT   # re-exported; see the note below

SEARCH_LIMIT: Final[int] = 20             # spec section 9: limit=20
SEARCH_MAX_LIMIT: Final[int] = 100        # Modrinth rejects a larger limit
SORT_RELEVANCE: Final[str] = "relevance"
SORT_DOWNLOADS: Final[str] = "downloads"
SORT_UPDATED: Final[str] = "updated"
SEARCH_SORTS: Final[tuple[str, str, str]] = (SORT_RELEVANCE, SORT_DOWNLOADS, SORT_UPDATED)

FABRIC_LOADER: Final[str] = "fabric"
KIND_MOD: Final[str] = "mod"
KIND_RESOURCEPACK: Final[str] = "resourcepack"
ProjectKind: TypeAlias = Literal["mod", "resourcepack"]

DEP_REQUIRED: Final[str] = "required"
DEP_OPTIONAL: Final[str] = "optional"
DEP_INCOMPATIBLE: Final[str] = "incompatible"
DEP_EMBEDDED: Final[str] = "embedded"
MAX_DEPENDENCY_DEPTH: Final[int] = 16

RATE_LIMIT_LIMIT_HEADER: Final[str] = "X-Ratelimit-Limit"
RATE_LIMIT_REMAINING_HEADER: Final[str] = "X-Ratelimit-Remaining"
RATE_LIMIT_RESET_HEADER: Final[str] = "X-Ratelimit-Reset"
RATE_LIMIT_THRESHOLD: Final[int] = 1      # sleep when Remaining <= this
RATE_LIMIT_MAX_SLEEP: Final[float] = 65.0 # the window is 60 s; never sleep longer
RATE_LIMIT_PAD_SECONDS: Final[float] = 1.0

FABRIC_MOD_JSON: Final[str] = "fabric.mod.json"
JAR_SUFFIX: Final[str] = ".jar"
DISABLED_SUFFIX: Final[str] = ".disabled"
MODS_SIDECAR_NAME: Final[str] = ".maestro-mods.json"
MODS_SIDECAR_FORMAT: Final[int] = 1
ICON_MAX_BYTES: Final[int] = 2 * 1024 * 1024

FABRIC_API_SLUG: Final[str] = "fabric-api"
SODIUM_SLUG: Final[str] = "sodium"
FABRIC_API_MOD_ID: Final[str] = "fabric-api"          # the `id` in its fabric.mod.json
PROTECTED_SLUGS: Final[frozenset[str]] = frozenset({FABRIC_API_SLUG})
PROTECTED_MOD_IDS: Final[frozenset[str]] = frozenset({FABRIC_API_MOD_ID, "fabric"})
PROTECTED_WARNING: Final[str] = (
    "Fabric API is what your other mods run on. Turning it off or removing it will stop "
    "them loading. Confirm that you want to do this."
)
```

`USER_AGENT` is `core.net.USER_AGENT` re-exported, exactly as `auth.py` re-exports
`LIVE_CLIENT_ID` (section 8.2): the literal
`"MaestroLauncher/1.0 (+https://github.com/<placeholder>/maestrolauncher)"` is written
once, in `core/net.py`. `Http` puts it in the session's default headers, so **every**
request this module makes already carries it — including the icon fetch and the CDN
download of a jar. Spec section 9 requires it on every request and this is how that is
guaranteed rather than remembered. No method here sets a `User-Agent` header of its own.

### 16.1 Facets

```python
def build_facets(kind: ProjectKind, game_version: str) -> str:
    """The `facets` query value: a JSON array of AND-ed facet groups, as a compact string."""

def build_version_filters(game_version: str, loader: str | None) -> dict[str, str]:
    """The `game_versions` (and, when `loader` is given, `loaders`) query values."""
```

`build_facets`, normative — the two shapes, and only these two:

| `kind` | facets value |
|---|---|
| `"mod"` | `[["project_type:mod"],["categories:fabric"],["versions:{game_version}"]]` |
| `"resourcepack"` | `[["project_type:resourcepack"],["versions:{game_version}"]]` |

A resource pack has **no loader**, so the `categories:fabric` group is absent from the
second shape. Adding it returns zero hits for every query, which looks like a broken
search box rather than a bug. Any other `kind` raises `ValueError`.

The value is produced with `json.dumps(groups, separators=(",", ":"))` and handed to
`Http` as an entry of the `params` mapping, so `requests` percent-encodes it. **The
facets JSON is never concatenated into the URL string**; a hand-built URL leaves the
`[`, `]`, `"` and `:` characters raw and Modrinth answers 400.

`build_version_filters` returns `{"game_versions": '["26.2"]'}` and, when `loader` is
not `None`, also `{"loaders": '["fabric"]'}` — both JSON arrays serialised the same way
and passed through `params`. `loader=None` means "send no loader filter", which is what
resource-pack queries need.

### 16.2 Data

```python
@dataclass(frozen=True, slots=True)
class ProjectHit:
    """One entry of a `/search` response."""
    project_id: str
    slug: str
    title: str
    description: str
    icon_url: str            # "" when the project has no icon; usually a .webp
    downloads: int
    author: str
    categories: tuple[str, ...]
    versions: tuple[str, ...]        # the game versions the project supports
    project_type: str                # "mod" | "modpack" | "resourcepack" | "shader"
                                     # | "datapack" | "plugin"
    client_side: str                 # "required" | "optional" | "unsupported"
    server_side: str
    date_modified: str               # ISO-8601 as returned
    latest_version: str = ""         # the newest game version, as Modrinth reports it

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ProjectHit":
        """Build a hit from one `hits[]` object, defaulting every missing field.

        Raises:
            ModrinthError: `project_id` is missing or empty.
        """

@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of search results and the numbers pagination needs."""
    hits: tuple[ProjectHit, ...]
    offset: int
    total_hits: int
    limit: int = SEARCH_LIMIT

    @property
    def has_more(self) -> bool:
        """True when `offset + len(hits)` is below `total_hits`."""

    @property
    def next_offset(self) -> int:
        """`offset + len(hits)` — the `offset` for the following page."""

@dataclass(frozen=True, slots=True)
class ModFile:
    """One downloadable file of a version."""
    url: str
    filename: str
    sha1: str
    sha512: str
    size: int
    primary: bool = False
    file_type: str | None = None

@dataclass(frozen=True, slots=True)
class Dependency:
    """One entry of a version's `dependencies` array."""
    dependency_type: str                 # "required" | "optional" | "incompatible" | "embedded"
    version_id: str | None = None
    project_id: str | None = None
    file_name: str | None = None

    @property
    def is_required(self) -> bool:
        """`dependency_type == DEP_REQUIRED` — the only kind that is ever installed."""

@dataclass(frozen=True, slots=True)
class ModVersion:
    """One version of a Modrinth project."""
    id: str
    project_id: str
    name: str
    version_number: str
    version_type: str                    # "release" | "beta" | "alpha"
    date_published: str                  # ISO-8601; string comparison is chronological
    game_versions: tuple[str, ...]
    loaders: tuple[str, ...]
    files: tuple[ModFile, ...]
    dependencies: tuple[Dependency, ...] = ()
    downloads: int = 0
    featured: bool = False

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ModVersion":
        """Build a version from a `/version` object.

        Raises:
            ModrinthError: `id` or `project_id` is missing.
        """

    @property
    def primary_file(self) -> ModFile:
        """The file marked `primary`, or the first file when none is.

        Raises:
            ModrinthError: the version has no files.
        """

    @property
    def required_dependencies(self) -> tuple[Dependency, ...]:
        """Only the `required` entries. Optional, incompatible and embedded are dropped here."""

@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Exactly what an Install click will write to disk, decided before anything downloads."""
    root: ModVersion
    versions_in_install_order: tuple[ModVersion, ...]
    already_installed: tuple[ModVersion, ...] = ()

    @property
    def is_single(self) -> bool:
        """True when the plan installs only `root` — the case that needs no confirm dialog."""

    @property
    def total_bytes(self) -> int:
        """Sum of `primary_file.size` over `versions_in_install_order`."""

    def describe(self) -> tuple[str, ...]:
        """One line per file to be installed: "{name} {version_number} ({size})"."""

@dataclass(frozen=True, slots=True)
class FabricModMeta:
    """The fields the launcher reads out of a jar's `fabric.mod.json`."""
    id: str
    name: str
    version: str
    description: str
    icon_path: str = ""      # the `icon` value: a path *inside* the jar, "" when absent

@dataclass(frozen=True, slots=True)
class InstalledMod:
    """One jar in an instance's mods directory, described by its own metadata."""
    name: str
    version: str
    description: str
    id: str                  # the fabric.mod.json id; "" when the jar has none
    path: Path               # the file on disk, including a `.disabled` suffix when disabled
    enabled: bool
    filename: str            # `path.name` with any `.disabled` suffix removed — the sidecar key
    icon_path: str = ""      # inside the jar; read on demand with `read_mod_icon`
    project_id: str = ""     # from the sidecar; "" for a hand-dropped jar
    version_id: str = ""     # from the sidecar; "" for a hand-dropped jar
    slug: str = ""           # from the sidecar
    protected: bool = False  # Fabric API: needs an explicit confirmation before change
    size: int = 0
```

`InstalledMod` deliberately does **not** carry icon bytes. A modlist of forty jars would
otherwise hold forty decoded images in memory for a list the user may never scroll;
`read_mod_icon` fetches one on demand and `ui/widgets.IconCache` (section 22) is what
keeps them.

### 16.3 The client

```python
class ModrinthClient:
    """Modrinth v2: search, version resolution, dependency planning and verified install."""

    http: Http           # public: `install` and section 17 reach the downloader through it

    def __init__(
        self,
        http: Http,
        *,
        api_base: str = MODRINTH_API,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Wrap an `Http`; `sleep` is injected so rate-limit tests run instantly."""

    def request_json(
        self, method: str, url: str, *,
        params: Mapping[str, Any] | None = None,
        cancel: CancelToken | None = None,
    ) -> Any:
        """One Modrinth request: pay any owed rate-limit debt, decode JSON, map the status.

        Raises:
            RateLimitedError: HTTP 429 survived the retry helper.
            ModrinthError: 404, any other non-2xx, or a body that is not valid JSON.
            NetworkError: transport failure that survived every attempt.
            CancelledError: `cancel` was set.
        """

    def search(
        self, query: str, *,
        kind: ProjectKind = KIND_MOD,
        game_version: str,
        offset: int = 0,
        limit: int = SEARCH_LIMIT,
        sort: str = SORT_RELEVANCE,
        cancel: CancelToken | None = None,
    ) -> SearchPage:
        """One page of `/search`, filtered by the facets for `kind` and `game_version`.

        Raises:
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def get_project(self, project: str, *, cancel: CancelToken | None = None) -> dict[str, Any]:
        """`GET /project/{slug-or-id}` — the decoded project object.

        Raises:
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def get_versions(
        self, project: str, game_version: str, *,
        loader: str | None = FABRIC_LOADER,
        cancel: CancelToken | None = None,
    ) -> list[ModVersion]:
        """`GET /project/{project}/version` filtered by game version and loader, newest first.

        Raises:
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def get_version(self, version_id: str, *, cancel: CancelToken | None = None) -> ModVersion:
        """`GET /version/{version_id}` — one exact version, whatever it targets.

        Raises:
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def resolve_version(
        self, project: str, game_version: str, *,
        loader: str | None = FABRIC_LOADER,
        cancel: CancelToken | None = None,
    ) -> ModVersion:
        """The newest usable build of `project` for this Minecraft version.

        Raises:
            NoCompatibleVersionError: the filtered list is empty, or no entry has a file.
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def resolve_install_plan(
        self, project: str, game_version: str, *,
        installed: Mapping[str, str] | None = None,
        loader: str | None = FABRIC_LOADER,
        progress: ProgressFn = null_progress,
        cancel: CancelToken | None = None,
    ) -> InstallPlan:
        """Every file an install of `project` will write, resolved transitively before any download.

        Raises:
            NoCompatibleVersionError: `project` itself has no build for `game_version`.
            DependencyResolutionError: a *required* dependency has no usable build.
            RateLimitedError, ModrinthError, NetworkError, CancelledError.
        """

    def install(
        self, plan: InstallPlan, dest_dir: Path, *,
        game_version: str = "",
        bundled: bool = False,
        progress: ProgressFn = null_progress,
        cancel: CancelToken | None = None,
    ) -> list[Path]:
        """Download every file in the plan, sha512-verified, and record it in the sidecar.

        Raises:
            ChecksumError: a downloaded jar's SHA-512 does not match the published hash.
            ModrinthError: a version in the plan has no file.
            InstanceError: the sidecar cannot be written.
            NetworkError, HttpStatusError, CancelledError, OSError.
        """

    def fetch_icon_bytes(self, url: str, *, cancel: CancelToken | None = None) -> bytes:
        """The raw bytes behind an `icon_url` — never a PIL image and never a CTkImage.

        Raises:
            ModrinthError: `url` is empty, the response is not 2xx, the body is empty,
                or the body is larger than `ICON_MAX_BYTES`.
            NetworkError, CancelledError.
        """
```

`dest_dir` is the directory the files land in: `instance.mods` for mods and
`instance.resourcepacks` for texture packs. The same call installs both, which is why
the parameter is not named `mods_dir`; the sidecar (16.5) is written inside whichever
directory is passed.

`search`, normative:

- `limit` is clamped to `[1, SEARCH_MAX_LIMIT]`; `offset` is clamped to `>= 0`;
  a `sort` outside `SEARCH_SORTS` falls back to `SORT_RELEVANCE`.
- Params: `{"query": query, "limit": limit, "offset": offset, "index": sort,
  "facets": build_facets(kind, game_version)}`.
- An empty `query` is legal and is what the Mods screen sends before the user types;
  paired with `sort=SORT_DOWNLOADS` it produces "the mods most people install for this
  version", which is the empty state's invitation rather than a blank panel.
- Pagination is `offset` / `total_hits` and nothing else. The response's `total_hits`
  is authoritative; `has_more` and `next_offset` are the only arithmetic the UI does.
  There is no cursor and no page number.
- A response that is not a JSON object, or whose `hits` is not a list, raises
  `ModrinthError`. A single malformed hit is skipped and logged at WARNING rather than
  failing the page.

`get_versions`, normative: params are `build_version_filters(game_version, loader)`.
The response is a JSON list ordered newest-first by Modrinth; that order is preserved
and never re-sorted locally. Entries that fail `ModVersion.from_json` are skipped and
logged at WARNING.

`resolve_version`, normative: `get_versions(...)`, then the **first** entry that has at
least one file. There is deliberately **no filter on `version_type`**: the current
Sodium build for 26.2 is `"mc26.2-0.9.2-beta.1-fabric"` with `version_type == "beta"`,
and a launcher that only accepts `"release"` reports Sodium as unavailable on a version
where it plainly works. An empty list, or a list where no entry has a file, raises
`NoCompatibleVersionError(project, game_version)` — the error whose message the bundled
installer (section 17) turns into the Sodium banner.

`fetch_icon_bytes`, normative: `http.request("GET", url, raise_for_status=False,
cancel=cancel)` and, on a 2xx, `response.content`; a non-2xx status becomes
`ModrinthError` so a missing icon can never raise an `HttpStatusError` into an icon task. Icons are `.webp`; decoding is `ui/widgets.py`'s job on the UI
thread (controller design note). A body over `ICON_MAX_BYTES` (2 MiB) raises rather
than being decoded — an icon that large is a mistake or an attack, not a thumbnail.

### 16.4 Dependency resolution

This is the part that decides whether one-click installs work. Spec section 9: a
one-click installer that ignores required dependencies produces crash-on-launch and is
worse than no installer.

`resolve_install_plan`, normative — the exact algorithm:

1. `installed` maps `project_id → version_id` for what is already on disk;
   `installed_index(dest_dir)` (16.5) builds it. `None` means `{}`.
2. `root = self.resolve_version(project, game_version, loader=loader, cancel=cancel)`.
3. Walk the graph depth-first from `root`, keeping two visited sets:
   `seen_versions: set[str]` of `ModVersion.id` and `seen_projects: set[str]` of
   `ModVersion.project_id`. A version whose `id` is in `seen_versions`, or whose
   `project_id` is in `seen_projects`, is not expanded again. **This is what stops
   cycles** — iris requires sodium, and a dependency graph is free to contain one.
4. For each version being expanded, iterate `version.required_dependencies` in order.
   Entries whose `dependency_type` is `optional`, `incompatible` or `embedded` are
   ignored completely: they are never resolved, never listed and never installed.
   An `embedded` dependency is already inside the jar; installing it a second time is
   how duplicate-mod crashes happen.
5. Resolve each required dependency, **preferring `version_id` over `project_id`**:
   - `dep.version_id` is a non-empty string → `self.get_version(dep.version_id)`. This
     is an exact pin and it wins whenever it is present. Modrinth frequently sends
     both: iris's `1.11.2+26.2-fabric` names sodium by `version_id` *and* `project_id`,
     and the pinned version is the one iris was built against.
   - otherwise `dep.project_id` is a non-empty string →
     `self.resolve_version(dep.project_id, game_version, loader=loader)`.
   - otherwise (both `None`) → `DependencyResolutionError("", game_version, technical=...)`.
     A required dependency that names nothing is unresolvable and the install stops.
6. A `NoCompatibleVersionError` raised while resolving a **dependency** is re-raised as
   `DependencyResolutionError(dep.project_id or dep.version_id or "", game_version,
   technical=str(exc))`, whose message is "One of the mods this needs isn't available
   for Minecraft {game_version}. Nothing was installed." The same error from the
   **root** propagates as `NoCompatibleVersionError`, because "Sodium isn't available
   yet" and "Sodium needs something that isn't available" read differently to a user.
7. A recursion depth over `MAX_DEPENDENCY_DEPTH` (16) raises
   `DependencyResolutionError`. The visited sets already make an infinite walk
   impossible; the cap is a second, cheap guarantee against a pathological graph.
8. Ordering. The result is a **post-order** walk: a version appears in
   `versions_in_install_order` only after every one of its required dependencies. `root`
   is therefore last. Nothing depends on install order for correctness on disk, but the
   confirm dialog reads top-down as "these first, then the mod you asked for", which is
   what a user expects to see.
9. Partitioning. A resolved version whose `project_id` is a key of `installed` **with
   the same version id** goes to `already_installed` and is left out of
   `versions_in_install_order` — it is already on disk and re-downloading it is waste.
   The same project at a *different* version stays in the install list: that is an
   upgrade, and `install` replaces the old file.
10. Progress: `progress(f"Checking {name}", resolved, resolved + pending)` after each
    resolution, where `pending` is the number of dependencies queued but not yet
    resolved. The total therefore grows as the graph is discovered, which is honest;
    `Progress.total` is never zero here.
11. `check_cancel(cancel)` runs before every HTTP call in the walk.
12. **Nothing is downloaded by this method.** It performs only `GET` requests against
    the metadata API. The full list reaches the UI as an `InstallPlan` and section 22
    shows it before `install` is ever called — spec section 9's "show the user the full
    list of what will be installed before downloading", and the section 0 amendment's
    reconciliation with one-click (`is_single` skips the dialog for a lone file).

`install`, normative:

1. `dest_dir.mkdir(parents=True, exist_ok=True)`.
2. Files are fetched **serially, in `versions_in_install_order`**. A modlist is a
   handful of files, order is what makes the plan readable, and serial requests keep
   the Modrinth rate limit comfortable. There is no worker pool here.
3. Per version: `file = version.primary_file`; `dest = dest_dir / file.filename`;
   `self.http.download(file.url, dest, expected_hash=file.sha512, algorithm="sha512",
   expected_size=file.size, label=file.filename, progress=<child reporter>,
   cancel=cancel)`. **SHA-512 is the verified hash**, from `files[].hashes.sha512`,
   because that is the hash Modrinth publishes for every file; `sha1` is recorded in
   the sidecar but is not what the download is checked against.
4. `file.filename` is used verbatim but is first rejected if it contains a path
   separator, a `..` segment, or a NUL — a filename from a remote API is untrusted
   input, and `ModrinthError` is raised rather than writing outside `dest_dir`.
5. After each successful file, `record_install(dest_dir, version, file, ...)` writes
   the sidecar entry, and any **other** filename the sidecar records for the same
   `project_id` is deleted (both `X.jar` and `X.jar.disabled`) and forgotten. That is
   the upgrade path: the new jar is on disk and verified before the old one goes.
6. Progress: a `Reporter` gives version *i* of *n* the slice
   `[i / n, (i + 1) / n]`, so the bar advances smoothly across a multi-file plan.
7. Cancellation leaves the files already installed in place, with their sidecar
   entries written. A half-installed modlist is recoverable; a half-written sidecar is
   not, which is why the sidecar is rewritten after every file rather than at the end.
8. Returns the destination paths in install order.

### 16.5 The installed-mod sidecar

`fabric.mod.json` tells the launcher what a jar *is*. It does not say where the jar came
from, so nothing in a jar can answer "is there a newer version of this on Modrinth?".
The sidecar records that link. It lives beside the jars, at
`InstancePaths.mods_sidecar` (`mods/.maestro-mods.json`) for mods and at
`resourcepacks/.maestro-mods.json` for texture packs — the same filename in whichever
directory `install` wrote to.

```json
{
  "format": 1,
  "mods": {
    "sodium-fabric-0.9.2-beta.1+mc26.2.jar": {
      "project_id": "AANobbMI",
      "version_id": "1kmSj7Jz",
      "slug": "sodium",
      "title": "Sodium",
      "version_number": "mc26.2-0.9.2-beta.1-fabric",
      "game_version": "26.2",
      "sha512": "b4c8…",
      "sha1": "3f1a…",
      "size": 1885574,
      "date_published": "2026-08-14T19:03:11Z",
      "installed_at": "2026-09-03T14:22:05Z",
      "bundled": true
    }
  }
}
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `format` | integer | `1` | `MODS_SIDECAR_FORMAT`. A file whose `format` is unknown is treated as absent and rewritten. |
| `mods` | object | `{}` | Filename → record. The key is the jar's name **without** any `.disabled` suffix, so toggling a mod never loses its record. |
| `mods[].project_id` | string | `""` | Modrinth project id — what `check_updates` queries. |
| `mods[].version_id` | string | `""` | The installed version's id — what "up to date" is compared against. |
| `mods[].slug` | string | `""` | Modrinth slug. Drives `PROTECTED_SLUGS`. |
| `mods[].title` | string | `""` | Project title, for the update badge's label. |
| `mods[].version_number` | string | `""` | Human version string, e.g. `"0.159.0+26.2"`. |
| `mods[].game_version` | string | `""` | The Minecraft version it was installed for. |
| `mods[].sha512` | string | `""` | The published SHA-512 the file was verified against. |
| `mods[].sha1` | string | `""` | The published SHA-1, recorded but not verified against. |
| `mods[].size` | integer | `0` | Bytes. |
| `mods[].date_published` | string | `""` | The version's `date_published`; ISO-8601 strings compare chronologically. |
| `mods[].installed_at` | string | `""` | When the launcher wrote the file, ISO-8601 UTC with a `Z` suffix. |
| `mods[].bundled` | boolean | `false` | True for files written by `install_bundled_mods` (section 17). |

Unknown keys are ignored and dropped on the next write. A record for a filename that no
longer exists is dropped by the next `write_sidecar`. A jar with no record is still
listed — the user is free to drop a jar into `mods/` by hand — it simply has no update
badge and no protection status from its slug.

```python
def sidecar_path(dest_dir: Path) -> Path:
    """`dest_dir / MODS_SIDECAR_NAME` — the same value as `InstancePaths.mods_sidecar`."""

def read_sidecar(dest_dir: Path) -> dict[str, dict[str, Any]]:
    """The `mods` map. Returns `{}` for a missing, unreadable, corrupt or unknown-format file."""

def write_sidecar(dest_dir: Path, records: Mapping[str, Mapping[str, Any]]) -> None:
    """Write the whole sidecar atomically, dropping records whose file no longer exists.

    Raises:
        InstanceError: the file cannot be written.
    """

def record_install(
    dest_dir: Path, version: ModVersion, file: ModFile, *,
    slug: str = "", title: str = "", game_version: str = "", bundled: bool = False,
    now: Callable[[], float] = time.time,
) -> None:
    """Add or replace one record and rewrite the sidecar.

    Raises:
        InstanceError: the file cannot be written.
    """

def forget_install(dest_dir: Path, filename: str) -> None:
    """Drop one record (keyed by the name without `.disabled`) and rewrite the sidecar.

    Raises:
        InstanceError: the file cannot be written.
    """

def installed_index(dest_dir: Path) -> dict[str, str]:
    """`project_id → version_id` for everything recorded — the `installed` argument of
    `resolve_install_plan`."""
```

`read_sidecar` never raises: a corrupt sidecar must degrade to "no update badges", not
to a mods screen that will not open.

### 16.6 Reading a jar

```python
def read_fabric_mod_json(jar_path: Path) -> FabricModMeta:
    """The mod's own metadata, read from `fabric.mod.json` inside the jar.

    Raises:
        ModrinthError: the file is not a readable zip, has no `fabric.mod.json`, or that
            entry is not a JSON object.
    """

def read_mod_icon(jar_path: Path, icon_path: str) -> bytes | None:
    """The bytes of an icon stored inside the jar, or None when there is no usable icon."""

def list_installed(dest_dir: Path) -> list[InstalledMod]:
    """Every jar in the directory, described by its own metadata rather than its filename.

    Raises:
        InstanceError: the directory exists but cannot be listed.
    """

def set_enabled(path: Path, enabled: bool, *, confirm_protected: bool = False) -> Path:
    """Enable or disable a mod by renaming between `.jar` and `.jar.disabled`.

    Raises:
        InstanceError: the target name is taken, the rename failed, or the mod is
            protected and `confirm_protected` is False.
    """

def delete_mod(path: Path, *, confirm_protected: bool = False) -> None:
    """Delete a mod jar and forget its sidecar record.

    Raises:
        InstanceError: the file cannot be deleted, or the mod is protected and
            `confirm_protected` is False.
    """

def is_protected_path(path: Path) -> bool:
    """True when this jar is Fabric API, which must not be changed without a warning."""

def base_filename(path: Path) -> str:
    """`path.name` with a trailing `.disabled` removed — the sidecar key for this file."""
```

`read_fabric_mod_json`, normative: open with `zipfile.ZipFile`, read the archive member
literally named `fabric.mod.json` at the root, decode it as UTF-8 JSON, and take
`id`, `name`, `version`, `description` and `icon`. `name` falls back to `id` and then to
the jar's stem; every other field falls back to `""`. The `icon` value may be a string
(a path inside the jar) or an object keyed by pixel size (`{"128": "assets/…/icon.png"}`),
in which case the largest numeric key wins. `zipfile.BadZipFile`, `KeyError`,
`json.JSONDecodeError`, `UnicodeDecodeError` and `OSError` are all wrapped in
`ModrinthError`.

`list_installed`, normative — this is spec section 9's "read `fabric.mod.json` from
inside each jar rather than showing filenames":

1. A missing `dest_dir` returns `[]`.
2. Only direct children whose name ends in `.jar` or `.jar.disabled` are considered.
   The sidecar (a dotfile), any `.part` leftover and any subdirectory are ignored.
3. `enabled = not path.name.endswith(DISABLED_SUFFIX)`.
4. `read_fabric_mod_json(path)` supplies `id`, `name`, `version`, `description` and
   `icon_path`. When it raises, the entry is still listed with
   `name = base_filename(path).removesuffix(".jar")`, `version = ""`, `id = ""` and
   `description = "Not a Fabric mod — no fabric.mod.json inside."`, and the failure is
   logged at WARNING. **One unreadable jar never empties the list**; a Forge jar or a
   half-copied download is exactly the case a user needs to see in order to delete it.
5. `project_id`, `version_id` and `slug` come from `read_sidecar(dest_dir)` keyed by
   `base_filename(path)`; `""` when there is no record.
6. `protected = is_protected_path(path)`.
7. Sorted by `name.casefold()`, then `filename`, so the list is stable across calls.

`is_protected_path`, normative, in order: the sidecar record's `slug` is in
`PROTECTED_SLUGS`; or the jar's `fabric.mod.json` `id` is in `PROTECTED_MOD_IDS`; or
`base_filename(path).casefold()` starts with `"fabric-api"`. Any one of the three is
enough, because a hand-dropped Fabric API jar has no sidecar record and must still be
protected.

`set_enabled` and `delete_mod`, normative: when `is_protected_path(path)` is true and
`confirm_protected` is False, both raise `InstanceError` with
`user_message=PROTECTED_WARNING` and change nothing. Spec section 9 requires that the
user is never allowed to disable or delete Fabric API without an explicit warning; making
the refusal live in this module rather than only in the dialog means no future screen,
context menu or keyboard shortcut can route around it. `ui/mods.py` catches the error,
shows the warning, and calls again with `confirm_protected=True`.

`set_enabled` toggles by renaming: `X.jar` ↔ `X.jar.disabled`. It returns the new path,
returns `path` unchanged when the file is already in the requested state, and raises
`InstanceError` when the target name already exists — overwriting the twin would destroy
a file. `delete_mod` unlinks the path (`missing_ok=True`) and calls
`forget_install(path.parent, base_filename(path))`; `OSError` becomes `InstanceError`.
Confirmation of an ordinary delete is the UI's job (spec section 9); the only refusal
this module makes is the protected one.

### 16.7 Updates

```python
def check_updates(
    client: ModrinthClient,
    installed: Sequence[InstalledMod],
    game_version: str,
    *,
    loader: str | None = FABRIC_LOADER,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> dict[str, ModVersion]:
    """Filename → the newer version available for it; absent means "up to date".

    Raises:
        RateLimitedError: Modrinth rate-limited the whole sweep.
        CancelledError: `cancel` was set.
    """
```

Normative:

- Mods with an empty `project_id` are skipped: a hand-dropped jar has nothing to query.
- For each remaining mod, `client.resolve_version(mod.project_id, game_version,
  loader=loader)`. Disabled mods are checked too — the badge is about the file, not
  about whether it is currently loading.
- An update exists when the candidate's `id` differs from `mod.version_id` **and** its
  `date_published` is greater than the `date_published` recorded in the sidecar. When
  the record has no `date_published` (a sidecar written before that key existed), the id
  comparison alone decides. The date guard is what stops a badge appearing when the user
  deliberately installed a newer build than the filtered list returns.
- `NoCompatibleVersionError` and `ModrinthError` for one project are caught, logged at
  WARNING, and produce no entry: a delisted project must not break the sweep.
  `RateLimitedError`, `NetworkError` and `CancelledError` propagate.
- `check_cancel(cancel)` before each request; `progress(mod.name, done, len(installed))`
  after each.
- The keys of the result are `InstalledMod.filename` values, so the Mods screen can look
  a badge up without re-deriving anything.

### 16.8 Rate limiting

Modrinth publishes `X-Ratelimit-Limit: 300`, `X-Ratelimit-Remaining: N` and
`X-Ratelimit-Reset: <seconds until the window resets>` on **every** response, success or
failure. Spec section 9 requires the launcher to read them and back off before it hits
the 300/min limit rather than after.

```python
def rate_limit_delay(
    headers: Mapping[str, str], *,
    threshold: int = RATE_LIMIT_THRESHOLD,
    max_sleep: float = RATE_LIMIT_MAX_SLEEP,
) -> float:
    """Seconds to wait before the next Modrinth request, read from the rate-limit headers."""
```

Normative:

- Missing, empty or unparseable headers return `0.0`. Nothing is ever guessed.
- `int(X-Ratelimit-Remaining) > threshold` returns `0.0`.
- Otherwise the delay is `min(max_sleep, float(X-Ratelimit-Reset) + RATE_LIMIT_PAD_SECONDS)`,
  clamped to `>= 0.0`. The one-second pad covers clock skew, and the 65-second ceiling
  means a bogus `Reset` header can never freeze a worker for longer than one window.
- The threshold is `1`, not `0`: at `Remaining == 0` the next request is already
  refused, so the launcher stops one request early.

`ModrinthClient.request_json` uses it like this, and this is the whole policy:

1. Before issuing a request, if a previous response left a debt, `self.sleep(debt)` and
   clear it. The wait happens on the calling worker thread; it is why `sleep` is
   injectable and why nothing here touches the UI.
2. Issue the request through `Http.request(..., raise_for_status=False)`. Passing
   `raise_for_status=False` is what makes the headers readable on a failure response as
   well as a successful one — `HttpStatusError` carries a status and a body but no
   headers. Retries still happen: `Http` retries `RETRY_STATUSES` (which includes 429,
   honouring `Retry-After`) regardless of `raise_for_status`, and only hands back the
   `Response` once every attempt is spent.
3. Record `rate_limit_delay(response.headers)` as the debt for the next call.
4. Map the status:
   - 2xx → `decode_json(response)`.
   - 404 → `ModrinthError` with `user_message` "That project isn't on Modrinth any more,
     or its address changed."
   - 429 → `RateLimitedError(retry_after)`, where `retry_after` is the numeric
     `Retry-After` header, else `X-Ratelimit-Reset`, else `RATE_LIMIT_MAX_SLEEP`. This
     is the "after the retry helper gives up" path: `Http` has already retried four
     times over roughly 3.5 seconds plus any `Retry-After` waits.
   - any other status → `ModrinthError` whose `technical` names the status, the URL and
     the first 500 characters of the body.
5. `requests.ConnectionError` and `requests.Timeout` have already become `NetworkError`
   inside `Http`; that propagates unchanged.

`ModrinthClient` holds its rate-limit debt on the instance, so one client shared by the
Mods screen serialises its own pacing. `Http.download` bypasses `request_json` — a file
download goes to Modrinth's CDN, not to the rate-limited API — so a large install does
not consume the request budget.

---

## 17. `core/instances.py`

An instance is a directory under `instances/` plus one JSON file describing it. Spec
section 10: instances are plural, they are created, renamed and deleted from the UI, and
`default` is hardcoded nowhere except the first-run bootstrap in `main.py`.

```python
INSTANCE_JSON_NAME: Final[str] = "instance.json"
INSTANCE_FORMAT: Final[int] = 1
NAME_MAX_LENGTH: Final[int] = 48
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
RESERVED_NAMES: Final[frozenset[str]] = frozenset({
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
})
BUNDLED_SLUGS: Final[tuple[str, str]] = (FABRIC_API_SLUG, SODIUM_SLUG)
BUNDLED_TITLES: Final[dict[str, str]] = {FABRIC_API_SLUG: "Fabric API", SODIUM_SLUG: "Sodium"}
MISSING_BANNER: Final[str] = "{name} isn't available for {version} yet."
```

`MISSING_BANNER.format(name="Sodium", version="26.2")` is
`"Sodium isn't available for 26.2 yet."` — the exact sentence spec section 9 requires,
written once so the Fabric API case reads the same way.

`DEFAULT_INSTANCE_NAME` is **not** redefined here; it comes from `core.config`
(section 8.2) and this module re-exports it
(`from core.config import DEFAULT_INSTANCE_NAME`) so there is one literal `"default"`.
`FABRIC_API_SLUG`, `SODIUM_SLUG` and `FABRIC_LOADER` come the same way, from
`core.modrinth` (section 16); `BUNDLED_SLUGS` is built from them rather than from two
new string literals.

### 17.1 `Instance` and `instance.json`

```python
@dataclass(slots=True)
class Instance:
    """One playable instance: its directory name, its Minecraft version, its pending notice."""
    name: str
    version_id: str
    created_at: str = ""     # ISO-8601 UTC with a Z suffix, e.g. "2026-09-03T14:22:05Z"
    banner: str = ""         # a sentence for the Play screen; "" means there is nothing to say

    def to_dict(self) -> dict[str, Any]:
        """The exact instance.json object."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, name: str) -> "Instance":
        """Build an Instance from a parsed instance.json, defaulting every missing field.

        The directory name always wins over a stale `name` inside the file."""
```

```json
{
  "format": 1,
  "name": "default",
  "version_id": "26.2",
  "created_at": "2026-09-03T14:22:05Z",
  "banner": ""
}
```

| Key | Type | Default | Meaning and validation |
|---|---|---|---|
| `format` | integer | `1` | `INSTANCE_FORMAT`. An unknown value is ignored and rewritten on the next save; the file is never rejected for it. |
| `name` | string | the directory name | Informational. The **directory name is authoritative** — if the two disagree, the directory wins and the file is corrected on the next save. |
| `version_id` | string | `""` | The Minecraft version this instance plays. `""` means "not decided yet"; `core/pipeline.py` then falls back to the config and the manifest. |
| `created_at` | string | `""` | ISO-8601 UTC, `Z` suffix. Display only. |
| `banner` | string | `""` | One sentence shown by the Play screen until the user dismisses it, which calls `clear_banner`. Persisted so the notice survives the restart after a first-run bundled install. |

`from_dict` never raises: a value of the wrong type is replaced by its default, because a
hand-edited `instance.json` must not make the instance disappear from the list.

### 17.2 Name validation

```python
def name_is_valid(name: str) -> bool:
    """True when `validate_name` would accept this name."""

def validate_name(name: str) -> str:
    """The trimmed, checked instance name — the exact string used as a directory name.

    Raises:
        InstanceError: the name is empty, too long, uses a forbidden character,
            ends with a dot or a space, or is a reserved Windows device name.
    """
```

Rules, applied in this order. Each failure raises `InstanceError` with the stated
`user_message`; the messages are interface copy and are exact.

| # | Rule | `user_message` |
|---|---|---|
| 1 | Strip leading and trailing whitespace. The trimmed value is what is stored and returned. | — |
| 2 | Not empty after trimming. | "Give the instance a name." |
| 3 | At most `NAME_MAX_LENGTH` (48) characters. | "Instance names can be up to 48 characters." |
| 4 | Matches `NAME_PATTERN`: the first character is a letter or digit, the rest are letters, digits, spaces, dots, dashes or underscores. | "Use letters, numbers, spaces, dots, dashes and underscores, and start with a letter or number." |
| 5 | Does not end with `.` or a space. | "Instance names can't end with a dot or a space." |
| 6 | The part before the first dot, case-folded, is not in `RESERVED_NAMES`. | "That name is reserved by Windows. Pick another one." |

Rule 4 is what keeps a name from escaping the instances directory: `/`, `\`, `:`, `*`,
`?`, `"`, `<`, `>`, `|` and every control character are excluded, and requiring an
alphanumeric first character rules out `.`, `..` and leading-dot hidden directories.
Rule 5 exists because Windows silently strips a trailing dot or space from a directory
name, so `"My pack "` and `"My pack"` would become the same directory while the launcher
believed they were two.

Uniqueness is checked by `InstanceManager`, not here, because it needs the directory
listing: `create` and `rename` reject a name that matches an existing instance
**case-insensitively** (`casefold`). Windows filesystems are case-insensitive and Linux
is not, so allowing `Default` beside `default` produces an instance list that works on
one machine and collides on another.

### 17.3 `InstanceManager`

```python
class InstanceManager:
    """Creates, lists, renames and deletes the instances under `instances/`."""

    def __init__(self, paths: Paths, *, clock: Callable[[], float] = time.time) -> None:
        """Manage the instances under `paths.instances`; `clock` fills `created_at`."""

    def list(self) -> list[Instance]:
        """Every instance directory, sorted by name (case-insensitively). Never raises."""

    def names(self) -> list[str]:
        """`[i.name for i in self.list()]` — the instance dropdown's `values`."""

    def exists(self, name: str) -> bool:
        """True when a directory for this name exists (compared case-insensitively)."""

    def get(self, name: str) -> Instance:
        """One instance by name.

        Raises:
            InstanceError: there is no such instance.
        """

    def paths_for(self, name: str) -> InstancePaths:
        """`paths.instance_paths(name)` — the directories inside that instance."""

    def create(self, name: str, version_id: str, *, banner: str = "") -> Instance:
        """Create the directory skeleton, a default options.txt and instance.json.

        Raises:
            InstanceError: invalid name, a name already in use, or the directories or
                files cannot be written.
        """

    def save(self, instance: Instance) -> None:
        """Write `instance.json` atomically.

        Raises:
            InstanceError: the file cannot be written.
        """

    def rename(self, instance: Instance, new_name: str) -> Instance:
        """Rename the directory and rewrite instance.json; returns the renamed Instance.

        Raises:
            InstanceError: invalid name, a name already in use, or the rename failed.
        """

    def delete(self, name: str) -> None:
        """Remove the instance directory and everything in it.

        Raises:
            InstanceError: there is no such instance, the path is not inside
                `paths.instances`, or the tree cannot be removed.
        """

    def clear_banner(self, instance: Instance) -> Instance:
        """Set `banner` to "" and save; what the banner's dismiss button calls.

        Raises:
            InstanceError: the file cannot be written.
        """

    def ensure_default(self, version_id: str) -> Instance:
        """The `default` instance, creating it when it is missing — the first-run bootstrap.

        Raises:
            InstanceError: the instance cannot be created.
        """

    def install_bundled_mods(
        self,
        instance: Instance,
        client: ModrinthClient,
        *,
        slugs: Sequence[str] = BUNDLED_SLUGS,
        progress: ProgressFn = null_progress,
        cancel: CancelToken | None = None,
    ) -> "BundledResult":
        """Install Fabric API and Sodium through the ordinary user-install path.

        Raises:
            ChecksumError: a bundled jar failed verification.
            RateLimitedError, ModrinthError, NetworkError, HttpStatusError,
            InstanceError, CancelledError, OSError.
        """
```

`list`, normative: every **direct subdirectory** of `paths.instances`, in
`name.casefold()` order. `instance.json` is read when present; when it is missing,
unreadable or corrupt, the entry is still produced as
`Instance(name=<directory name>, version_id="", created_at="", banner="")` and **nothing
is written**. A directory a user copied in by hand appears in the dropdown immediately.
A missing `paths.instances` returns `[]`. This method never raises — the instance
dropdown must always populate.

`create`, normative:

1. `validate_name(name)`, then the case-insensitive uniqueness check against `names()`.
   A duplicate raises `InstanceError` with "There's already an instance called {name}."
2. `self.paths_for(name).ensure()` — creates `root`, `mods`, `resourcepacks`,
   `shaderpacks`, `saves`, `logs` and `natives` (section 3.2).
3. `options.txt` is written with `atomic_write_text(ip.options_txt, DEFAULT_OPTIONS_TXT)`
   **only when it does not already exist**. Overwriting a user's settings when they
   re-create an instance over an existing directory would be data loss.
4. `instance.json` is written with `save()`. `created_at` is
   `datetime.fromtimestamp(self._clock(), tz=timezone.utc)` formatted as
   `"%Y-%m-%dT%H:%M:%SZ"`.
5. Any `OSError` becomes `InstanceError`. A partially created directory is **left in
   place**: deleting a directory the launcher did not fully create is how a user loses
   a `saves/` folder.

`rename`, normative: `validate_name(new_name)`; a rename to the same trimmed string is a
no-op returning `instance` unchanged; a case-only rename of the *same* instance
(`"Default"` → `"default"`) is allowed and skips the uniqueness check; any other
collision raises. The move is `os.replace(old_dir, new_dir)`, then `instance.json` is
rewritten with the new name. `InstanceManager` **never reads or writes `config.json`** —
`ui/app.py` is what updates `Config.selected_instance` after a rename or a delete, and
`main.py` is what saves it.

`delete`, normative: the instance must exist; its resolved directory must be a direct
child of `paths.instances.resolve()` or `InstanceError` is raised without touching the
filesystem (a name that escaped validation must still not delete an arbitrary tree). The
tree goes with `shutil.rmtree(dir, onexc=<handler>)`, where the handler clears the
read-only bit with `os.chmod(path, stat.S_IWRITE)` and retries the operation once —
Windows marks files read-only often enough that a plain `rmtree` fails on a mods
directory. Deleting the last instance is allowed; the empty state belongs to `ui/app.py`.
Confirmation is the UI's job.

`DEFAULT_OPTIONS_TXT`, the file written into a fresh instance:

```
lang:en_us
fullscreen:false
enableVsync:true
guiScale:0
renderDistance:12
simulationDistance:10
maxFps:120
pauseOnLostFocus:true
```

Every key here has been accepted by the game since 1.14, and the game ignores keys it
does not know and supplies its own default for keys that are absent, so this file can
never stop the game from starting. There is deliberately **no `version:` line**: without
one the game runs its options data-fixer over the file, which is harmless for these
eight keys and safe on every version the dropdown offers. `guiScale:0` means "auto".
The game rewrites the whole file when it quits, so this is a starting point, not a
setting the launcher owns.

### 17.4 Bundled mods

```python
@dataclass(frozen=True, slots=True)
class BundledResult:
    """What the bundled install managed to do, and what it could not."""
    installed: tuple[str, ...]     # slugs installed or already present, in attempt order
    missing: tuple[str, ...]       # one banner sentence per slug that has no build
    files: tuple[Path, ...]        # every jar written, in install order

    @property
    def banner(self) -> str:
        """`missing` joined with a single space — what `Instance.banner` is set to."""
```

`install_bundled_mods`, normative:

1. `game_version` is `instance.version_id`; there is no separate parameter, because a
   bundled mod for a version the instance does not play is meaningless. An empty
   `version_id` raises `InstanceError`.
2. `mods_dir = self.paths_for(instance.name).mods`, created if needed.
3. For each slug in `slugs`, **in order** — `fabric-api` first, then `sodium`:
   - `installed = core.modrinth.installed_index(mods_dir)`, recomputed before each slug
     so the second slug sees what the first one wrote and never re-downloads a shared
     dependency.
   - `plan = client.resolve_install_plan(slug, instance.version_id, installed=installed,
     loader=FABRIC_LOADER, progress=<child>, cancel=cancel)`.
   - `files = client.install(plan, mods_dir, game_version=instance.version_id,
     bundled=True, progress=<child>, cancel=cancel)`.
   - The slug is appended to `installed`; the paths are appended to `files`. A plan whose
     `versions_in_install_order` is empty (everything already on disk at the right
     version) still counts as installed.
4. `NoCompatibleVersionError` or `DependencyResolutionError` for one slug is caught: that
   slug is skipped, `MISSING_BANNER.format(name=BUNDLED_TITLES.get(slug, slug),
   version=instance.version_id)` is appended to `missing`, and the loop continues with
   the next slug. Spec section 9: if Sodium has no build for the selected version, the
   instance is **not** failed — it stays vanilla-Fabric and the user is told, in those
   exact words. The same treatment covers a required dependency of a bundled mod having
   no build, because the outcome for the user is identical: that mod is not available
   today.
5. `ChecksumError`, `RateLimitedError`, `NetworkError`, `HttpStatusError`, `OSError` and
   `CancelledError` **propagate**. Those mean "try again", not "not available", and
   turning a dropped connection into a permanent "Sodium isn't available" banner would
   be a lie.
6. When `missing` is non-empty, `instance.banner` is set to `result.banner` and
   `self.save(instance)` persists it, so the Play screen shows the sentence after the
   task finishes and again after a restart, until the user dismisses it.
7. Progress: a `Reporter` gives slug *i* of *n* the slice `[i / n, (i + 1) / n]`, and
   within a slug resolution takes `[0.00, 0.15]` and downloading `[0.15, 1.00]`.
8. The caller runs this as a task under `TASK_BUNDLED_MODS` (section 4).

**No special-casing.** This method calls exactly the two public methods a user's Install
click calls — `ModrinthClient.resolve_install_plan` then `ModrinthClient.install`. It
contains no hardcoded dependency list, no hardcoded version number, no hardcoded
filename and no branch that treats `sodium` differently from any other slug except for
the title in the banner. Sodium's dependency set is whatever the API returns on the day
it is asked; today `/project/sodium/version` reports `dependencies: []` for 26.2, and the
code must not encode that. Fabric API is installed first only because installing it
first means Sodium's resolution finds it already present — an ordering choice, not a
special case.

---

## 18. `core/pipeline.py`

One function turns "the user pressed Play" into a `LaunchPlan`. It is the only place
that knows the order of the steps, and the only place that decides how much of the
progress bar each step owns.

```python
STEP_MANIFEST: Final[int] = 0
STEP_VERSION_JSON: Final[int] = 1
STEP_RUNTIME: Final[int] = 2
STEP_CLIENT_JAR: Final[int] = 3
STEP_LIBRARIES: Final[int] = 4
STEP_FABRIC_PROFILE: Final[int] = 5
STEP_FABRIC_LIBRARIES: Final[int] = 6
STEP_ASSETS: Final[int] = 7
STEP_NATIVES: Final[int] = 8
STEP_ARGV: Final[int] = 9

STEP_WEIGHTS: Final[tuple[tuple[str, float, float], ...]] = (
    ("Checking versions",          0.00, 0.02),
    ("Reading the version file",   0.02, 0.04),
    ("Installing Java",            0.04, 0.24),
    ("Downloading the game",       0.24, 0.34),
    ("Downloading libraries",      0.34, 0.49),
    ("Setting up Fabric",          0.49, 0.52),
    ("Downloading Fabric",         0.52, 0.60),
    ("Downloading assets",         0.60, 0.96),
    ("Unpacking natives",          0.96, 0.99),
    ("Building the command",       0.99, 1.00),
)

def step_reporter(progress: ProgressFn, step: int) -> Reporter:
    """A `Reporter` covering exactly the `STEP_WEIGHTS` slice of one step."""
```

The ten weights, and the reason each is the size it is. A cold first launch moves about
580 MB: ~480 MB of assets, ~58 MB of JRE, ~39 MB of client jar and a few tens of MB of
libraries. The weights are those proportions rounded, so the bar moves at roughly a
constant rate instead of sitting at 4 % through the entire asset download.

| Step | Constant | Label | Range | Weight |
|---|---|---|---|---|
| 1 | `STEP_MANIFEST` | "Checking versions" | 0.00 – 0.02 | 0.02 |
| 2 | `STEP_VERSION_JSON` | "Reading the version file" | 0.02 – 0.04 | 0.02 |
| 3 | `STEP_RUNTIME` | "Installing Java" | 0.04 – 0.24 | 0.20 |
| 4 | `STEP_CLIENT_JAR` | "Downloading the game" | 0.24 – 0.34 | 0.10 |
| 5 | `STEP_LIBRARIES` | "Downloading libraries" | 0.34 – 0.49 | 0.15 |
| 6 | `STEP_FABRIC_PROFILE` | "Setting up Fabric" | 0.49 – 0.52 | 0.03 |
| 7 | `STEP_FABRIC_LIBRARIES` | "Downloading Fabric" | 0.52 – 0.60 | 0.08 |
| 8 | `STEP_ASSETS` | "Downloading assets" | 0.60 – 0.96 | 0.36 |
| 9 | `STEP_NATIVES` | "Unpacking natives" | 0.96 – 0.99 | 0.03 |
| 10 | `STEP_ARGV` | "Building the command" | 0.99 – 1.00 | 0.01 |

`0.02 + 0.02 + 0.20 + 0.10 + 0.15 + 0.03 + 0.08 + 0.36 + 0.03 + 0.01 = 1.00` exactly.
Every range starts where the previous one ended, so the bar never jumps backwards and
never stalls at a value it will later exceed. A test asserts both facts directly against
`STEP_WEIGHTS`.

Step 8 is split further inside its own slice: the index download takes `0.60 – 0.62`,
the objects `0.62 – 0.92`, and `materialise_assets` (only for a `virtual` or
`map_to_resources` index) `0.92 – 0.96`. Step 3's internal split is section 11's
(download 0.85, extract 0.12, install 0.03 of its own range); `Reporter.sub` composes
the two so no module needs to know another's arithmetic.

```python
def resolve_version_id(
    manifest: VersionManifest, config: Config, instance: Instance,
    override: str | None = None,
) -> str:
    """Which Minecraft version this launch uses.

    Raises:
        ManifestError: the chosen id is not in the manifest.
    """

def prepare_launch(
    http: Http,
    paths: Paths,
    config: Config,
    instance: Instance,
    account: Account,
    *,
    version_id: str | None = None,
    use_fabric: bool = True,
    features: Features = DEFAULT_FEATURES,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> LaunchPlan:
    """Everything between the Play button and a runnable command line, in order.

    Raises:
        ManifestError: the version is unknown, its JSON is malformed, or Fabric has no
            loader for it.
        RuntimeProvisionError: the JRE could not be installed.
        ChecksumError: a downloaded file failed verification.
        UnresolvedPlaceholderError: a `${…}` survived substitution.
        LaunchError: natives could not be unpacked.
        ConfigError: the merged Fabric profile could not be written.
        InstanceError: the instance directories could not be created.
        NetworkError, HttpStatusError, CancelledError, OSError.
    """
```

`resolve_version_id`, normative — first non-empty of: `override`, `instance.version_id`,
`config.selected_version`, `manifest.latest_release`. The result must exist in the
manifest or `ManifestError` is raised; this is the only place the fallback order is
written down, and `ui/play.py` calls it to label the Play button.

`prepare_launch`, normative. `check_cancel(cancel)` runs at every step boundary, so a
cancelled launch stops within one file rather than at the end.

**Step 1 — manifest** (`step_reporter(progress, STEP_MANIFEST)`).
`ip = paths.instance_paths(instance.name)`, then `ip.ensure()` so a hand-edited or
partially copied instance is repaired before anything else. `paths.ensure()` likewise.
`manifest = core.versions.fetch_manifest(http, paths, cancel=cancel)`;
`vid = resolve_version_id(manifest, config, instance, version_id)`;
`entry = manifest.get(vid)`.

**Step 2 — version JSON.** `version_json = core.versions.fetch_version_json(http, paths,
entry, progress=…, cancel=cancel)`. Then `major = core.versions.java_major(version_json)`
and `modern = core.versions.has_modern_arguments(version_json)`. When `use_fabric` is
true and `modern` is false, raise `ManifestError` with the user message
"Fabric doesn't support Minecraft {vid}. Pick 1.14 or newer." — the section 0 amendment.
The version dropdown lists every release, so this is a reachable path and it fails here,
clearly, rather than crashing later.

**Step 3 — Java runtime.** `java = core.runtime.ensure_runtime(http, paths, major,
progress=…, cancel=cancel)`. `major` comes from the version JSON and from nothing else;
there is no default and no table.

**Step 4 — client jar.** `client_jar = core.libraries.download_client_jar(http, paths,
version_json, vid, progress=…, cancel=cancel)`. The id is always the **vanilla** id, so
the file is `versions/26.2/client.jar` and never
`versions/fabric-loader-0.19.5-26.2/client.jar`.

**Step 5 — vanilla libraries.** `vanilla_libs = core.libraries.select_libraries(
version_json, features=features.as_mapping())`, then
`core.libraries.download_libraries(http, paths, vanilla_libs, progress=…, cancel=cancel)`.

**Step 6 — Fabric profile and merge** (skipped when `use_fabric` is false).
`entries = core.fabric.fetch_loader_versions(http, vid, cancel=cancel)`;
`loader = core.fabric.choose_loader(entries)`;
`profile = core.fabric.fetch_profile(http, vid, loader.version, cancel=cancel)`;
`merged = core.fabric.merge_profile(version_json, profile)`;
`core.fabric.write_merged_profile(paths, vid, merged)`.
A `ManifestError` from `fetch_loader_versions` ("Fabric doesn't support Minecraft {v}
yet") **propagates**. `prepare_launch` never silently falls back to a vanilla launch:
the instance's `mods/` directory would then be ignored and the user would be told
nothing, which is the worst possible outcome of a mod launcher.

**Step 7 — Fabric libraries** (skipped when `use_fabric` is false).
`libraries = core.libraries.select_libraries(merged, features=features.as_mapping())` —
called on the **merged** document, so Fabric's `downloads`-less entries go through
branch 4 of section 12.4. The download set is only what is new:
`new_libs = [lib for lib in libraries if library_local_path(paths, lib) not in
{library_local_path(paths, v) for v in vanilla_libs}]`. Those are fetched with
`core.libraries.download_libraries(http, paths, new_libs,
sha1_lookup=core.fabric.library_sha1_lookup(http), progress=…, cancel=cancel)`, so the
`.sha1` sidecars are fetched lazily and only for entries whose inline `sha1` was absent.

When `use_fabric` is false, steps 6 and 7 report their label once at their `start`
fraction and immediately report their `end`; `libraries` stays `vanilla_libs`,
`launch_json` stays `version_json`, `main_class` is
`core.versions.main_class(version_json)` and `version_name` is `vid`. When `use_fabric`
is true, `launch_json` is `merged`, `main_class` is `merged["mainClass"]` (from the
profile, never hardcoded — section 13.4) and `version_name` is `merged["id"]`, for
example `"fabric-loader-0.19.5-26.2"`.

**Step 8 — assets.** `index_id, index_json = core.assets.fetch_asset_index(http, paths,
launch_json, progress=…, cancel=cancel)`;
`objects = core.assets.parse_asset_index(index_json)`;
`core.assets.download_assets(http, paths, objects, progress=…, cancel=cancel)`;
`game_assets = core.assets.game_assets_dir(paths, index_id, index_json, ip)`. When the
index sets `virtual` or `map_to_resources`, `core.assets.materialise_assets(paths,
objects, game_assets, progress=…, cancel=cancel)` runs in the last slice of the step.
`index_id` is a string (`"32"`) and is passed to `build_variables` as one.

**Step 9 — natives.** `core.libraries.extract_natives(paths, libraries, ip.natives,
progress=…, cancel=cancel)`. This runs on **every** launch including modern versions
that extract nothing, because `extract_natives` is what guarantees the directory exists
and it is passed as `-Djava.library.path`.

**Step 10 — variables and argv.**
`classpath = core.libraries.build_classpath(paths, libraries, client_jar)`;
`variables = core.launch.build_variables(account=account, version_name=version_name,
version_type=core.versions.version_type(version_json), asset_index_id=index_id,
game_dir=ip.root, assets_root=paths.assets, game_assets=game_assets,
natives_dir=ip.natives, library_dir=paths.libraries, classpath=classpath,
clientid=config.clientid)`; then
`core.launch.build_launch_plan(java=java, version_json=launch_json,
main_class=main_class, variables=variables, memory_gb=config.memory_gb,
game_dir=ip.root, version_id=vid, instance_name=instance.name, features=features)`,
which is returned.

Three things `prepare_launch` deliberately does **not** do:

- It never signs in and never refreshes a token. It takes an `Account` that is already
  fresh; `ui/play.py` calls `auth.ensure_fresh` before submitting the launch task, so a
  sign-in dialog can never appear from inside a download loop. `prepare_launch` does not
  import `auth` for anything but the `Account` type.
- It never writes `config.json` and never mutates `config`. The version the user picked
  is saved by `ui/app.py`.
- It never starts a process. `process.GameProcess` (section 19) receives the
  `LaunchPlan` and the `InstancePaths`, and the caller already has both.

---

## 19. `process.py`

Spec section 8 opens with the trap: "non-blocking" and "detached" are not the same thing,
and detaching is the wrong choice here because it loses crash detection entirely. This
module spawns the game as an ordinary **child** process whose output the launcher reads
and whose exit code the launcher waits for, while keeping the launcher window fully
usable.

```python
LOG_TAIL_LINES: Final[int] = 200          # spec section 8: the crash panel shows the last 200
READER_ENCODING: Final[str] = "utf-8"
READER_ERRORS: Final[str] = "replace"
STOP_GRACE_SECONDS: Final[float] = 5.0    # terminate(), then kill() after this long
JOIN_TIMEOUT_SECONDS: Final[float] = 5.0  # supervisor waits this long for the reader
READER_THREAD_NAME: Final[str] = "game-reader"
SUPERVISOR_THREAD_NAME: Final[str] = "game-supervisor"
STDOUT_LOG_BACKUP_SUFFIX: Final[str] = ".1"   # launcher-stdout.log.1, one generation
CREATE_NO_WINDOW: Final[int] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
```

`CREATE_NO_WINDOW` is read through `getattr` because the attribute does not exist on
POSIX; the literal `0x08000000` is the documented Windows value and keeps the constant
importable everywhere. It is passed **only** when `sys.platform == "win32"`.

Ruling 2 names this module explicitly: `process.py` imports neither `tkinter` nor
`customtkinter` nor `theme` nor `ui`. It is handed a `queue.Queue` and puts
`messages.py` dataclasses on it, and that is its entire relationship with the interface.

### 19.1 Crash hints

```python
CRASH_HINTS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"UnsupportedClassVersionError|has been compiled by a more recent version of the Java"),
        "The game needs a newer Java than the one that started it. Delete the `runtimes` "
        "folder inside your MaestroLauncher folder and press Play again — the launcher "
        "will install the right version.",
    ),
    (
        re.compile(r"OutOfMemoryError|GC overhead limit exceeded|Could not reserve enough space for .* object heap"),
        "The game ran out of memory. Raise the Memory slider on the Play screen, or "
        "remove a few mods, and try again.",
    ),
    (
        re.compile(r"Mixin apply failed|MixinApplyError|MixinTransformerError|org\.spongepowered\.asm\.mixin"),
        "Two mods are trying to change the same part of the game. Turn off the mods you "
        "added most recently, one at a time, until the game starts.",
    ),
    (
        re.compile(r"requires any version of fabric-api|fabric-api[^\n]{0,120}\bis missing\b|Missing mod fabric-api"),
        "A mod needs Fabric API and it isn't installed. Install Fabric API from the Mods "
        "screen, then press Play again.",
    ),
)

def crash_hint(lines: Sequence[str]) -> str | None:
    """The plain-English cause of a crash, or None when nothing in the tail is recognised."""
```

`crash_hint`, normative: the lines are joined with `"\n"` and each pattern is tried in
**tuple order**; the first that matches supplies the hint and the scan stops. The order
matters — an out-of-memory crash inside a mixin prints both signatures, and "the game
ran out of memory" is the actionable one, so it is listed before the mixin pattern. No
match returns `None`, and the crash panel then shows the tail with no hint rather than a
guess. Each hint is a full sentence that names the next action, per spec section 13's
copy rule; none of them mentions a stack trace or a class name.

The table covers exactly the four causes spec section 8 names: wrong Java, out of
memory, mod conflict, missing Fabric API. Adding a fifth is an amendment.

### 19.2 `GameProcess`

```python
class GameProcess:
    """Runs the game as a child process, streams its output, and reports how it ended."""

    def __init__(
        self,
        plan: LaunchPlan,
        instance: InstancePaths,
        queue: "queue.Queue[UIMessage]",
        task_id: str = TASK_GAME,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        tail_lines: int = LOG_TAIL_LINES,
    ) -> None:
        """Hold everything needed to start the game; `popen` is injected for tests."""

    def start(self) -> int:
        """Spawn the game, start the reader and supervisor threads, and return the pid.

        Raises:
            LaunchError: the process could not be spawned, or it is already running.
            InstanceError: the instance or its `logs/` directory cannot be created.
        """

    def stop(self, *, grace: float = STOP_GRACE_SECONDS) -> None:
        """Ask the game to quit, then kill it if it has not exited within `grace`. Never raises."""

    def wait(self, timeout: float | None = None) -> int | None:
        """Block until the game exits; its exit code, or None when `timeout` elapsed first."""

    @property
    def is_running(self) -> bool:
        """True between a successful `start()` and the process exiting."""

    @property
    def pid(self) -> int | None:
        """The child's process id, or None before `start()`."""

    @property
    def returncode(self) -> int | None:
        """The exit code once the process has ended, else None."""

    @property
    def stopped(self) -> bool:
        """True when `stop()` was called — the UI uses it to skip the crash panel."""

    @property
    def log_tail(self) -> tuple[str, ...]:
        """The last `tail_lines` lines of output, oldest first. Safe to read from any thread."""
```

`start`, normative — the spawn, exactly:

1. Calling `start()` twice raises `LaunchError`; one `GameProcess` runs one game.
2. `instance.ensure()`, then the log file is prepared: if
   `instance.launcher_stdout_log` exists it is moved to
   `launcher-stdout.log.1` with `os.replace` (one generation is kept, so the run before
   last is discarded), and a fresh file is opened for appending. The reader appends to
   it line by line for the life of the process. Rotating once per launch bounds the file
   and still leaves the previous crash readable.
3. **The launcher writes `logs/launcher-stdout.log`, never `logs/latest.log`.** The game
   itself writes `latest.log` through its bundled log4j config, relative to the game
   directory, which *is* the instance directory. Two writers on one file corrupt it and
   break the game's own rotation on Windows. `InstancePaths.latest_log` exists so the UI
   can *read* the game's file; nothing in this module opens it for writing. (Section 0
   amendment, rows for sections 3 and 19.)
4. The process is spawned with `self._popen(argv, **kwargs)` where `argv` is
   `list(plan.argv)` — **a list, never a string** — and the keyword arguments are exactly:

   | Argument | Value | Why |
   |---|---|---|
   | `cwd` | `str(plan.cwd)` | the instance directory; the game resolves `saves/`, `mods/`, `logs/` and `options.txt` relative to it |
   | `env` | `dict(plan.env)` when non-empty, else `None` | section 15 already merged it over `os.environ` |
   | `stdout` | `subprocess.PIPE` | one stream to read |
   | `stderr` | `subprocess.STDOUT` | merged, so the crash tail keeps stdout and stderr interleaved in real order |
   | `stdin` | `subprocess.DEVNULL` | the game never reads stdin; an inherited console handle can block it |
   | `shell` | `False` | no shell, ever: a path with a space or an `&` would otherwise be re-parsed |
   | `bufsize` | `-1` | default buffering on a binary pipe; the reader decodes lines itself |
   | `close_fds` | `True` | the default, stated so nobody removes it |
   | `creationflags` | `CREATE_NO_WINDOW`, **Windows only** | no flashing console window behind the launcher |
   | `start_new_session` | `True`, **POSIX only** | a Ctrl+C in the terminal that started the launcher does not also kill the game |

   Neither `DETACHED_PROCESS` nor `CREATE_NEW_CONSOLE` nor `os.setsid()`-style
   detachment is used. `start_new_session=True` puts the child in its own session but
   leaves it a **child** of the launcher, so `wait()` still returns its exit code. That
   is the entire point of this module.
5. `OSError` — including the `FileNotFoundError` a missing `java` produces — is wrapped
   in `LaunchError` whose `technical` is `" ".join(plan.redacted_argv())`. The raw argv
   is never logged: `--accessToken` is an ordinary element of it (section 15.4).
6. `GameStarted(task_id, pid)` is put on the queue.
7. Two `threading.Thread(daemon=True)` objects are started, named
   `READER_THREAD_NAME` and `SUPERVISOR_THREAD_NAME`. They are daemons so a launcher
   that is closing never blocks on them; the game itself is a separate process and keeps
   running regardless.
8. `start()` returns the pid and does not block.

**Reader thread**, normative:

- Iterates lines from `proc.stdout` until EOF. The pipe is **binary**; each line is
  decoded with `READER_ENCODING` and `READER_ERRORS` (`utf-8`, `replace`) and its
  trailing `\r\n` or `\n` is stripped. Decoding is done here rather than by asking
  `Popen` for text mode because mod authors print in every encoding there is, and a
  `UnicodeDecodeError` on this thread would silently end all logging for the session.
- Each line is passed through `logsetup.REDACTOR.redact` **once**, and the redacted text
  is what is both written to the file and put on the queue. Some versions echo launch
  arguments on the first line, and the access token must reach neither the log file nor
  the crash panel nor the "copy log" clipboard.
- The redacted line is appended to the open log file followed by `"\n"`, and the file is
  flushed after every line. A crash panel opened the instant the game dies must show the
  lines that caused it.
- The line is appended to a `collections.deque(maxlen=tail_lines)` guarded by a
  `threading.Lock`, because `log_tail` is read from the UI thread.
- `queue.put(LogLine(text))` — the only thing this thread ever tells the UI. It never
  touches a widget, a `StringVar` or a `CTkImage`.
- Every exception is caught, logged at ERROR, and ends the loop; the thread never
  raises. On EOF the log file is closed.

**Supervisor thread**, normative:

1. `code = proc.wait()` — the blocking call that makes crash detection possible.
2. `reader.join(JOIN_TIMEOUT_SECONDS)`, so the tail is complete before it is read. A
   reader that has not finished in five seconds is abandoned and the tail is taken as it
   stands; a hung pipe must not stop the exit from being reported.
3. `tail = self.log_tail` — at most `LOG_TAIL_LINES` (200) lines, oldest first, matching
   `GameExited.log_tail` in section 4.
4. `hint = crash_hint(tail) if code != 0 else None`.
5. `queue.put(GameExited(task_id, code, tail, hint))`.

Exactly **one** `GameExited` is posted per `start()`, whatever ended the process. A
user-requested stop still reports its code (`1` on Windows, `-15` on POSIX for a
`SIGTERM`); the UI decides not to show a crash panel by reading `stopped`, not by
guessing from the number. Spec section 8's crash panel — last 200 lines, a "copy log"
button, and the hint — is built by `ui/play.py` from this one message.

`stop`, normative:

1. Sets `stopped = True` **first**, so the supervisor is already in the right state when
   it wakes.
2. No process, or one that has already exited, is a no-op.
3. `proc.terminate()`, then `proc.wait(timeout=grace)`. On `subprocess.TimeoutExpired`,
   `proc.kill()` and `wait()` again with no timeout.
4. `OSError` and `ProcessLookupError` from a process that exited during the call are
   logged at WARNING and swallowed. `stop()` never raises.
5. It does **not** join the supervisor thread. `ui/play.py` calls `stop()` on the Tk
   thread, and joining there would freeze the window for the duration of the shutdown —
   the exact failure this module exists to avoid. The supervisor posts `GameExited` when
   it is ready and the UI reacts to that message like any other.

The launcher window stays usable the whole time the game runs and the launcher does not
exit when the game starts; both follow from `start()` returning immediately and from
every blocking call living on a daemon thread.

---

## 20. `tasks.py`

The single bridge between worker threads and the Tk thread. Spec section 5 is
non-negotiable: workers push plain dataclasses onto one `queue.Queue`, the UI drains it
on a timer, and **every** `Future` gets an `add_done_callback` that catches everything so
an unhandled exception inside a worker can never vanish silently.

```python
DEFAULT_MAX_WORKERS: Final[int] = 4
THREAD_NAME_PREFIX: Final[str] = "maestro-task"
DRAIN_BATCH: Final[int] = 200
GENERIC_FAILURE_MESSAGE: Final[str] = LauncherError.default_user_message
```

`GENERIC_FAILURE_MESSAGE` is the re-exported class default from section 2, so the
sentence exists once. Its literal value is
`"Something went wrong. Check launcher.log for details."` — that is what the user sees
when a worker raises something that is not a `LauncherError`, which by definition means
the launcher has no better explanation to give.

`DEFAULT_MAX_WORKERS` is 4 because this pool runs **tasks**, not files. A single launch
task opens its own 16-worker download pool inside `core/libraries` and `core/assets`
(section 12.5), so four here means four *activities* at once — a launch, a mod search, a
batch of icon fetches and a sign-in poll — not four sockets. Keeping it small also paces
the Modrinth icon fetches, which would otherwise burn the 300/min budget on a fast
scroll.

`DRAIN_BATCH` is 200 because the game's startup burst can print thousands of lines in a
second. At 200 messages per 50 ms tick the UI keeps up with 4,000 lines a second and the
Tk thread never spends an unbounded amount of time inside one drain; anything left over
is handled on the next tick.

### 20.1 `TaskRunner`

```python
class TaskRunner:
    """A thread pool whose every outcome — value, error or cancellation — arrives on one queue."""

    queue: "queue.Queue[UIMessage]"

    def __init__(
        self,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
        queue: "queue.Queue[UIMessage] | None" = None,
        executor: concurrent.futures.Executor | None = None,
    ) -> None:
        """Build the pool and the queue; pass either to run the whole thing synchronously in tests."""

    def submit(
        self, task_id: str, fn: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future[Any]:
        """Run `fn(*args, **kwargs)` on the pool; its outcome always reaches the queue.

        Raises:
            RuntimeError: `shutdown()` has already been called.
        """

    def progress_fn(self, task_id: str) -> ProgressFn:
        """A `ProgressFn` that posts `Progress(task_id, label, done, total)`. Never raises."""

    def token(self, task_id: str) -> CancelToken:
        """The cancel token for this task id, created on first use."""

    def cancel(self, task_id: str) -> None:
        """Set that task's cancel token; the worker stops at its next `check_cancel`."""

    def cancel_all(self) -> None:
        """Set every live cancel token."""

    def is_running(self, task_id: str) -> bool:
        """True while any future submitted under this exact task id is unfinished."""

    def post(self, message: UIMessage) -> None:
        """Put a message on the queue from any thread. Never raises."""

    def drain(self, max_messages: int = DRAIN_BATCH) -> list[UIMessage]:
        """Pop up to `max_messages` messages without blocking — what `_drain_queue` calls."""

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        """Cancel everything, stop the pool, and refuse further work. Never raises."""
```

Construction, normative: `queue` defaults to a fresh **unbounded** `queue.Queue()` — no
`maxsize`, so `put` can never block a worker or a reader thread. `executor` defaults to
`concurrent.futures.ThreadPoolExecutor(max_workers=max_workers,
thread_name_prefix=THREAD_NAME_PREFIX)`; passing one in is how a test substitutes an
executor that runs the callable inline. Live futures are held in a
`dict[str, set[concurrent.futures.Future[Any]]]` keyed by task id and guarded by a
`threading.Lock`; the done-callback discards its own future from that set. Cancel tokens
live in a `dict[str, CancelToken]` under the same lock.

`submit`, normative — the guarantee this whole module exists for:

1. **Every submitted task produces exactly one terminal message**: a `TaskFinished` or a
   `TaskFailed`, never both and never neither. A screen can therefore always turn its
   spinner off in one place.
2. `future.add_done_callback(cb)` is attached before `submit` returns.
3. The body of `cb` is wrapped in its own `try` / `except BaseException`. This is the
   outermost net: an exception escaping a done-callback is only printed by
   `concurrent.futures` to stderr and is otherwise lost, which is precisely the silent
   disappearance spec section 5 forbids. The outer handler logs at ERROR and, if it can,
   posts a `TaskFailed` with `GENERIC_FAILURE_MESSAGE`.
4. Inside, the outcome is classified in this order:

   | Outcome | Message posted | `user_message` |
   |---|---|---|
   | `future.cancelled()` | `TaskFailed(task_id, CancelledError(), …)` | `CancelledError.default_user_message` — "Cancelled." |
   | `future.exception()` is `None` | `TaskFinished(task_id, future.result())` | — |
   | the exception is a `LauncherError` (including `CancelledError` and every subclass in section 2) | `TaskFailed(task_id, exc, exc.user_message)` | the exception's own `user_message` |
   | any other `BaseException` — `KeyError`, `OSError`, `MemoryError`, `KeyboardInterrupt`, `SystemExit` | `TaskFailed(task_id, exc, GENERIC_FAILURE_MESSAGE)` | the generic sentence above |

   `future.exception()` is used rather than `future.result()` so an exception is
   inspected without being re-raised inside the callback.
5. Before posting a failure, the callback logs it with
   `logger.error("task %s failed", task_id, exc_info=exc)`, so the traceback lands in
   `launcher.log` with tokens redacted by `RedactingFilter` (section 5.2). The user gets
   one sentence; the log gets everything.
6. The future is removed from the live set, whichever branch ran, in a `finally`.
7. A failure inside `queue.put` itself is logged and swallowed. A callback must never
   propagate.
8. **`submit` does not inject `progress` or `cancel` into `fn`.** Only the caller knows
   the parameter names, so the call site is explicit:
   `runner.submit(TASK_LAUNCH, prepare_launch, http, paths, config, instance, account,
   progress=runner.progress_fn(TASK_LAUNCH), cancel=runner.token(TASK_LAUNCH))`.
   There is no magic and nothing to discover by reading this module's source.
9. Submitting a second future under an id that already has one is allowed; both run and
   `is_running` stays true until the last one finishes. Per-item work uses distinct ids
   anyway (`f"{TASK_MOD_ICON}:{project_id}"`, section 4).
10. After `shutdown()`, `submit` raises `RuntimeError` — the stdlib's own behaviour,
    deliberately not wrapped in a `LauncherError`, because submitting work to a closed
    runner is a launcher bug and not something to show a user.

`progress_fn`, normative: the returned callable puts `Progress(task_id, label, done,
total)` on the queue and returns `None`. It is safe to call from any thread (`queue.put`
is), and it **never raises**: a failure to post is logged at DEBUG and swallowed, because
a dropped progress tick is not worth aborting a 480 MB download for. It performs no
throttling — the sub-second cadence comes from the `Reporter` scale (1000 units,
section 6.2) and from the UI's 50 ms drain.

`token` / `cancel` / `cancel_all`, normative: `token` creates the `CancelToken` on first
request and returns the same object afterwards, so the UI's Cancel button and the worker
share one flag. `cancel(task_id)` sets it; the worker stops at its next
`check_cancel(cancel)` and raises `CancelledError`, which the done-callback turns into a
`TaskFailed` carrying "Cancelled." — a cancelled sign-in and a cancelled download report
through exactly the same path as any other failure. A token is **not** reset by
`submit`; a screen that wants a fresh one after a cancel calls `cancel` and then
`reset_token`:

```python
    def reset_token(self, task_id: str) -> CancelToken:
        """Replace this id's cancel token with a fresh one and return it."""
```

`drain`, normative: pops with `queue.get_nowait()` until the queue is empty or
`max_messages` have been taken, ignoring `queue.Empty`, and returns them in order. It is
called only from the Tk thread and returns a plain list, so `ui/app.py._drain_queue`
iterates a snapshot rather than holding the queue while it mutates widgets.

`shutdown`, normative: `cancel_all()` first, so running workers begin unwinding, then
`executor.shutdown(wait=wait, cancel_futures=cancel_futures)`. The default `wait=False`
means closing the window is instant. One caveat implementers must know:
`ThreadPoolExecutor` threads are **not** daemons and are joined at interpreter exit, so a
worker blocked on a socket keeps the process alive. That is bounded here, not hoped away:
every long operation checks its `CancelToken` at least once per file or chunk (section 6)
and `Http` fixes the read timeout at 60 seconds (section 7), so the worst case after
`shutdown()` is roughly one read timeout. `shutdown()` is idempotent and never raises;
calling it twice is a no-op.

Nothing in this module imports `tkinter`, `customtkinter`, `theme` or `ui` — it is
module 19 in the map and the UI is above it. It also does not import `process`: a
`GameProcess` is handed the `TaskRunner`'s `queue` object directly (section 19), which is
why the queue is a public attribute.

---
