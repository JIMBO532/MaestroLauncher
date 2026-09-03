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
