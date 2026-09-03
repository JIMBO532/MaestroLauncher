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
