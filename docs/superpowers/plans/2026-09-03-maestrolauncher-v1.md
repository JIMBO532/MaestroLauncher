# MaestroLauncher v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MaestroLauncher v1, a zero-config Minecraft: Java Edition launcher (Python 3.12+, CustomTkinter) that provisions its own Java runtime, installs Fabric + Fabric API + Sodium automatically, and offers one-click Modrinth mod and resource-pack installation with recursive dependency resolution.

**Architecture:** A frozen interface contract (`contract.md`) is written first; every module is then implemented against it by a fresh subagent and reviewed. Pure-Python core code (`core/` package, `auth.py`, `process.py`) does all network and disk work in worker threads and talks to the CustomTkinter UI (`ui/` package) only through plain dataclass messages on one `queue.Queue`. All HTTP goes through one injectable `Http` wrapper (single `requests.Session`, mandatory `timeout=(10, 60)`, one retry helper), so every module is unit-testable offline through a fake transport adapter.

**Tech Stack:** Python 3.12-compatible source (dev machine runs 3.14.7 with Tk 9.0), customtkinter 6.0.0, requests 2.34.2, Pillow 12.3.0, pytest 9.1.1, pywin32 312 (Windows only, optional at runtime).

**Spec:** `PLAN_1.md` at the repo root is the binding authority. `docs/superpowers/plans/api-facts-2026-09-03.md` records the live data shapes verified on 2026-09-03 and travels with the spec. Every implementer reads both.

## Global Constraints

Copied from PLAN_1.md; every task's requirements implicitly include all of these.

- Write real, fully implemented code. No pseudocode, no `// TODO`, no `pass  # implement later`, no abridged functions.
- Python 3.12-compatible syntax and stdlib only. Dependencies: `customtkinter`, `requests`, `Pillow` (plus optional `pywin32` on Windows). No external launcher libraries (`minecraft-launcher-lib` etc.).
- Every module must match `contract.md` exactly. If the contract is wrong, say so explicitly at the top of the report, record the amendment in the "Amendments" section at the top of `contract.md` in the same commit, and never silently diverge.
- **Every** `requests` call passes `timeout=(10, 60)`. One retry helper with exponential backoff + jitter, retrying on 5xx, 429, and connection errors; never on 4xx.
- All file writes atomic: write `.part`, `fsync`, `os.replace`. Downloads atomic (`.part` then rename). Hash-check before downloading; skip when the on-disk hash already matches.
- Exception hierarchy rooted at `LauncherError`, with `user_message` (shown in a dialog) separate from the technical string (logged).
- Never log a token, refresh token, or device code. Redact them in every log path.
- Rotating file log at `MaestroLauncher/launcher.log`, tokens redacted. The app must start cleanly with a corrupt or absent `config.json` — validate and rewrite it with defaults rather than crashing.
- Directory layout (spec section 10): Windows `%APPDATA%/MaestroLauncher/`, Linux `~/.local/share/maestrolauncher/`, macOS `~/Library/Application Support/MaestroLauncher/`; subfolders `config.json`, `accounts.json` (0600 on POSIX), `runtimes/java-{major}/`, `libraries/`, `assets/{indexes,objects}/`, `versions/{id}/` (client.jar, `{id}.json`, `fabric-merged.json`), `instances/{name}/` (`mods/ resourcepacks/ shaderpacks/ saves/ logs/ natives/`, `options.txt`). Instances are plural: create, rename, delete from the UI; never hardcode `default` outside the first-run bootstrap.
- Version ordering comes from manifest order (newest first), never string sorting. `latest.release` is the default. Java major version comes from the version JSON `javaVersion.majorVersion`, never hardcoded.
- Thread safety (spec section 5): worker threads never touch a widget, a `StringVar`, or a `CTkImage`. Workers push plain dataclass messages onto a single `queue.Queue`. The UI runs `self.after(50, self._drain_queue)` and is the only code that mutates widgets. Every `Future` gets an `add_done_callback` that catches everything and posts `TaskFailed`.
- `${user_type}` is `msa`. `${auth_xuid}` is the XSTS `xid`. `${clientid}` is a stable per-install random UUID stored in `config.json`. `${classpath_separator}` is `;` on Windows and `:` elsewhere. After substitution, assert no `${` remains in the final argv and raise rather than launch.
- Default memory `-Xmx6G -Xms6G`; slider capped at `min(system_ram_gb - 4, 12)`.
- Modrinth `User-Agent: MaestroLauncher/1.0 (+https://github.com/<placeholder>/maestrolauncher)` on every request; respect the 300 req/min limit by reading `X-Ratelimit-Remaining` and backing off.
- Visual design (spec section 13): all colour, spacing, type and radius values are named constants in `theme.py`; no raw hex and no magic padding numbers anywhere else. Spacing scale 4, 8, 12, 16, 24, 32 only. Three type sizes, two weights, monospace only for the device code and log output. Two radii maximum. One accent colour, used on the primary action only. No tracked-out ALL-CAPS section labels, no emoji as icons, no middle-dot metadata joins, no arrows glued to button text, not every screen chopped into identical cards. Text contrast 4.5:1 or better; clickable targets at least 32x32 px; visible keyboard focus on every control; `minsize()` set.
- Interface copy: active voice, sentence case, buttons name what happens ("Install Sodium"), errors say what broke and the next action, empty states are invitations, player vocabulary ("Mods", "Texture Packs", "Memory").
- Tests: `pytest`, offline by default. HTTP is faked with the `FakeAdapter` transport defined in `contract.md` (mounted on the `Http` wrapper), never by patching `requests` globally. Tests that need the network are marked `@pytest.mark.live` and are deselected by default (`-m "not live"` in `pytest.ini`). Tests that need a display are skipped automatically when Tk cannot open a window.
- Commits: one or more per task, conventional prefixes (`feat:`, `test:`, `docs:`, `fix:`), trailer lines as given in the dispatch.

## Controller rulings already made (binding on every task)

1. **`core` and `ui` are packages, not single files.** Spec section 0 lists `core.py` and `ui.py` as delivery chunks for a chat interface; at roughly 2,000 lines each they would be unreviewable. `import core` / `import ui` still work. This amendment is stated in `contract.md` and `README.md`. Everything else keeps the spec's flat module names: `errors.py`, `paths.py`, `auth.py`, `process.py`, `theme.py`, `main.py`, plus three small support modules the spec implies but does not name: `messages.py` (queue message dataclasses), `logsetup.py` (rotating redacted log), `tasks.py` (thread pool to queue bridge).
2. **Module map and allowed import direction** (a module may import only modules above it):
   `errors.py` → `paths.py` → `messages.py` → `logsetup.py` → `core/progress.py` → `core/net.py` → `core/config.py` → `core/versions.py` → `auth.py` → `core/runtime.py` → `core/libraries.py` → `core/fabric.py` → `core/assets.py` → `core/launch.py` → `core/modrinth.py` → `core/instances.py` → `core/pipeline.py` → `process.py` → `tasks.py` → `theme.py` → `ui/widgets.py` → `ui/app.py`, `ui/account.py`, `ui/play.py`, `ui/mods.py` → `main.py`. `core/__init__.py` re-exports the public names of its submodules. Nothing under `core/`, `auth.py`, or `process.py` imports `tkinter`, `customtkinter`, `theme`, or `ui`.
3. **Dependency injection, no globals.** Functions receive an `Http` instance, a `Paths` instance and a `Config` instance as parameters. Long operations receive a progress callback `(label: str, done: int, total: int) -> None` and a `CancelToken`; they never import `queue` or the UI.
4. **The Mojang `logging` block is not used** (see api-facts file, "Version JSON", DECISION).
5. **Dev environment:** code is tested on Python 3.14.7 / Tk 9.0 / customtkinter 6.0.0 but must remain 3.12-compatible. Runtime dependencies are installed in the machine's global Python; `python -m pytest -q` runs the suite from the repo root.
6. **Not a worktree.** The repo was created for this build; work happens on branch `feature/maestrolauncher-v1` in the project folder itself, because the folder is the deliverable.

---

### Task 1: Freeze the interface contract and the design plan

**Files:**
- Create: `contract.md`
- Create: `requirements.txt`
- Create: `pytest.ini`

**Interfaces:**
- Consumes: `PLAN_1.md` (spec), `docs/superpowers/plans/api-facts-2026-09-03.md`, the rulings above.
- Produces: `contract.md`, the single source of truth every later task implements against. Later tasks reference it by section number, so the section order below is mandatory.

- [ ] **Step 1: Read the inputs completely.** Read `PLAN_1.md` end to end, then `docs/superpowers/plans/api-facts-2026-09-03.md`, then the "Global Constraints" and "Controller rulings" sections of this plan. Check the installed CustomTkinter API where a widget capability matters (`python -c "import customtkinter, inspect; print(customtkinter.__file__)"`).

- [ ] **Step 2: Write `contract.md` with exactly these numbered sections, in this order.** Every public class lists its fields with types; every public function and method has its exact signature with type hints, a one-line docstring, and a `Raises:` list naming `errors.py` classes. Constants (URLs, timeouts, limits, filenames) are listed with their values. Private helpers are not part of the contract.

  0. **Amendments** — a dated table, initially containing one row for the `core`/`ui` package ruling. Later tasks append rows here when they must deviate.
  1. **Module map** — the module list and import direction from ruling 2, plus a one-line responsibility per module.
  2. **`errors.py`** — hierarchy rooted at `LauncherError(Exception)` with `user_message: str` and `technical: str`; at minimum: `ConfigError`, `NetworkError`, `HttpStatusError(NetworkError)` carrying `status: int` and `body: str`, `ChecksumError`, `CancelledError`, `RuntimeProvisionError`, `ManifestError`, `UnresolvedPlaceholderError`, `AuthError` with subclasses `AuthPendingError`, `AuthSlowDownError`, `AuthExpiredError`, `AuthDeclinedError`, `XboxAccountError` (field `xerr: int`, `redirect: str`), `NoJavaEditionError`, `TokenExpiredError`, `ModrinthError`, `RateLimitedError(ModrinthError)`, `DependencyResolutionError(ModrinthError)`, `InstanceError`, `LaunchError`. State the plain-English `user_message` for each XErr code from spec section 4.2 and the exact 404 explanation from section 4.2 step 5.
  3. **`paths.py`** — `Paths` dataclass (root and every directory/file from spec section 10, `default()` per platform, `for_root(root)`, `ensure()`), `InstancePaths` dataclass (mods, resourcepacks, shaderpacks, saves, logs, natives, options_txt, latest_log), atomic write helpers (`atomic_write_bytes`, `atomic_write_text`, `atomic_write_json`, `read_json`), `sha1_file`, `sha256_file`, `sha512_file`, `posix_chmod_600`.
  4. **`messages.py`** — frozen dataclasses `Progress(task_id, label, done, total)`, `TaskFinished(task_id, result)`, `TaskFailed(task_id, exc, user_message)`, `LogLine(text)`, `AuthCode(code, url)`, `GameStarted(task_id, pid)`, `GameExited(task_id, exit_code, log_tail, hint)`, and the `UIMessage` union alias. Field types stated.
  5. **`logsetup.py`** — `Redactor` (register secret values; `redact(text)` replaces registered values and token-shaped strings such as JWTs, `access_token=`, `refresh_token=`, `device_code=`, `Bearer …`, `XBL3.0 x=…`), `RedactingFilter(logging.Filter)`, `configure_logging(paths, level) -> logging.Logger` using `RotatingFileHandler` (state maxBytes and backupCount).
  6. **`core/progress.py`** — `ProgressFn` type alias, `CancelToken` (threading.Event based; `cancel()`, `is_cancelled`, `raise_if_cancelled()` raising `CancelledError`), `Reporter` helper that scales sub-task progress into a parent range.
  7. **`core/net.py`** — `TIMEOUT = (10, 60)`, `USER_AGENT`, `Http` class (constructor accepts an optional `requests.adapters.BaseAdapter` to mount for tests, `pool_connections=16`, `pool_maxsize=32`, injectable `sleep` and `rng`), `request`, `get_json`, `post_json`, `post_form`, `download` (atomic, verifies sha1/sha256/sha512/size, skips when existing file matches, streams with progress and cancel), `retry` helper semantics (base delay, factor, jitter, max attempts, which failures retry). State that 4xx responses are returned to callers (or raised as `HttpStatusError` with the body available) and never retried.
  8. **`core/config.py`** — the exact `config.json` JSON schema as a fenced JSON block with every key, type and default: `auth_mode` ("entra"|"live", default "entra"), `client_id` (default constant per mode), `clientid` (per-install UUID), `memory_gb` (default 6), `selected_version` (null means latest release), `selected_instance`, `include_snapshots` (false), `window` (width/height), `last_account`. `Config` dataclass, `load_config(paths) -> Config` (corrupt or absent file: rewrite defaults, never raise), `save_config`, `max_memory_gb()` using `min(system_ram_gb - 4, 12)` with a floor of 2, and how total RAM is read on Windows (`ctypes` `GlobalMemoryStatusEx`), Linux (`/proc/meminfo`) and macOS (`sysctl hw.memsize`).
  9. **`core/versions.py`** — `VersionEntry`, `VersionManifest` (ordered list, `latest_release`, `latest_snapshot`, `releases(include_snapshots)`, `index_of(id)`, `is_newer(a, b)` by manifest order), `fetch_manifest(http, paths)` (cached copy written to `versions/version_manifest_v2.json`, used when offline), `fetch_version_json(http, paths, entry)` (cached under `versions/{id}/{id}.json`, sha1-verified), `java_major(version_json) -> int`.
  10. **`auth.py`** — the comment block describing Path A and Path B; constants for both endpoint families, scopes, `LIVE_CLIENT_ID = "00000000402b5328"`, RpsTicket prefixes per mode; `Account` dataclass (name, uuid, xuid, access_token, access_expires_at, refresh_token, refresh_expires_at or null, auth_mode); `AccountStore` (`load`, `save` with DPAPI when `win32crypt` imports and plaintext fallback, 0600 on POSIX; file format documented, including how DPAPI-wrapped content is marked); `DeviceCodeSession` (`start(mode, client_id, http) -> DeviceCode(user_code, verification_uri, device_code, interval, expires_in)`, `poll_once`, `wait_for_token(on_code, cancel) -> MsaTokens`) with exactly how `authorization_pending`, `slow_down` (+5 s), `expired_token`, `authorization_declined` and network failure are distinguished; `xbl_authenticate`, `xsts_authorize` (XErr mapping), `login_with_xbox`, `fetch_profile` (404 → `NoJavaEditionError`, 401 → `TokenExpiredError`, 403 → `AuthError`); `sign_in(mode, client_id, http, on_code, cancel) -> Account`; `refresh(account, client_id, http) -> Account`; `ensure_fresh(account, ..., within_seconds=300)`; the `accounts.json` schema as a fenced JSON block.
  11. **`core/runtime.py`** — `adoptium_os()`, `adoptium_arch()` (map AMD64/x86_64 → x64, arm64/aarch64 → aarch64), `runtime_dir(paths, major)`, `java_executable(paths, major)`, `runtime_is_valid(paths, major)` (exists and `java -version` exits 0, with `subprocess.run` injectable for tests), `query_adoptium(http, major) -> AdoptiumBinary(name, link, checksum, size, release_name)` with the full query-parameter set, `install_runtime(...)` (download to a temp file, SHA-256 verify, extract to a temp dir, flatten the single top-level directory and macOS `Contents/Home`, chmod 0o755 everything in `bin/` on POSIX, `os.replace` into place), `ensure_runtime(http, paths, major, progress, cancel) -> Path`.
  12. **`core/libraries.py`** — `current_os_name()` ("windows"|"linux"|"osx"), `current_arch()` ("x64"|"x86"|"arm64"), `os_version_string()`, `rules_allow(rules, os_name, arch, os_version, features) -> bool` (no rules → allow; rules present and none match → deny; `features` dict evaluated), `maven_path(gav) -> str`, `Library` dataclass, `select_libraries(version_json, ...)`, `library_local_path`, `download_libraries(...)` (SHA-1 verify, skip when matching, 16-worker pool), `download_client_jar(...)`, `extract_natives(...)` (classifier path honouring `extract.exclude`) and the classpath rule for `natives-*` Maven classifiers, `is_native_classifier(name)`.
  13. **`core/fabric.py`** — `fetch_loader_versions(http, game_version)`, `choose_loader(entries)` (first `stable`, else index 0), `fetch_profile(http, game_version, loader_version)`, `fabric_library_url(lib) -> tuple[str, str]` (jar URL, `.sha1` URL), `fabric_library_sha1(http, lib)` (inline `sha1` first), `FABRIC_EXPECTED_MAIN_CLASS`, `merge_profile(vanilla_json, fabric_json) -> dict` (Fabric libraries first, then Mojang's, dedupe by `group:artifact` keeping the higher version via `compare_versions`, mainClass from the profile with a warning if it differs, `arguments` concatenated), `compare_versions(a, b) -> int` (dotted-numeric with non-numeric fallback), write `fabric-merged.json`.
  14. **`core/assets.py`** — `fetch_asset_index`, `AssetObject`, `download_assets(...)` (16-worker pool, hash-check first, `Progress` counts in objects and bytes), handling of `virtual` and `map_to_resources` (copy into `assets/virtual/{id}/` or the instance `resources/` directory), `game_assets_dir(...)`.
  15. **`core/launch.py`** — `Features` dataclass (all six flags default False), `evaluate_arguments(arguments, os_name, arch, os_version, features) -> list[str]`, `substitute(args, variables) -> list[str]` raising `UnresolvedPlaceholderError` when any `${` survives, `build_variables(...)` producing the complete variable set from spec section 7, `memory_flags(memory_gb)`, `LaunchPlan` dataclass (java, argv, cwd, env), `build_launch_plan(...)`.
  16. **`core/modrinth.py`** — constants (`MODRINTH_API`, `USER_AGENT`, `SEARCH_LIMIT = 20`), `ProjectKind` ("mod"|"resourcepack"), `ProjectHit`, `SearchPage(hits, offset, total_hits)`, `ModVersion`, `ModFile`, `Dependency`, `InstallPlan(root, versions_in_install_order, already_installed)`, `InstalledMod` (name, version, description, id, path, enabled, project_id if recorded), `ModrinthClient(http)` with `search(query, kind, game_version, offset)`, `get_project`, `get_versions(project, game_version, loader)`, `get_version(version_id)`, `resolve_version(project, game_version)`, `resolve_install_plan(project, game_version, installed) -> InstallPlan` (recursive required deps, visited set, by `version_id` or `project_id`), `install(plan, mods_dir, progress, cancel)` (sha512 verify, atomic), `fetch_icon_bytes(url) -> bytes`, rate-limit behaviour (`X-Ratelimit-Remaining` ≤ 1 → sleep until `X-Ratelimit-Reset`; 429 → `RateLimitedError` after the retry helper gives up); `read_fabric_mod_json(jar_path)`, `list_installed(mods_dir)`, `set_enabled(path, enabled)`, `delete_mod(path)`, `check_updates(client, installed, game_version)`, the installed-mods sidecar file `mods/.maestro-mods.json` recording project_id/version_id per filename, `FABRIC_API_SLUG = "fabric-api"`, `SODIUM_SLUG = "sodium"`, `PROTECTED_SLUGS` (Fabric API warning).
  17. **`core/instances.py`** — `Instance` dataclass (name, version_id, created_at, banner), `instance.json` schema, `InstanceManager(paths)` with `list`, `get`, `create(name, version_id) -> Instance` (skeleton dirs, default `options.txt`), `install_bundled_mods(instance, client, progress, cancel) -> BundledResult(installed, missing)` (Fabric API and Sodium through the normal resolution path; Sodium missing → instance stays vanilla-Fabric and `missing` carries the banner text "Sodium isn't available for {version} yet."), `rename`, `delete`, name validation rules.
  18. **`core/pipeline.py`** — `prepare_launch(http, paths, config, instance, account, progress, cancel) -> LaunchPlan` with the exact step order: manifest → version JSON → runtime → client jar + libraries → Fabric profile + libraries + merge → assets → natives → variables → argv. Weighted progress ranges per step.
  19. **`process.py`** — `CRASH_HINTS` table (pattern → plain-English hint for `UnsupportedClassVersionError`, `OutOfMemoryError`, `Mixin apply failed`, missing Fabric API), `GameProcess(plan, instance_paths, queue, task_id)` with `start()`, `stop()`, `is_running`, `pid`, `returncode`; reader thread appends to `logs/latest.log` and posts `LogLine`; supervisor thread posts `GameExited(exit_code, log_tail (last 200 lines), hint)`; `creationflags=CREATE_NO_WINDOW` on Windows, `start_new_session=True` on POSIX, `shell=False`, `cwd` = instance dir.
  20. **`tasks.py`** — `TaskRunner(max_workers=4)` with `queue: queue.Queue`, `submit(task_id, fn, *args, **kwargs) -> Future` (done callback catches everything and posts `TaskFinished` or `TaskFailed`, mapping `LauncherError.user_message` or a generic fallback sentence), `progress_fn(task_id) -> ProgressFn`, `shutdown()`.
  21. **`theme.py` and the design plan.** First the design plan required by spec section 13: the palette rationale (grounded in the performance pitch, with the reason stated), the token block (5–6 colours with contrast ratios computed against their backgrounds, spacing scale, three type sizes and two weights, two radii, font fallback lists using only fonts known to exist on Windows 11 plus Linux/macOS fallbacks), one ASCII wireframe per screen (Account, Play, Mods with its Installed pane and Texture Packs view), the anti-defaults checklist with a pass/fail per item, and "what I changed and why". Then the module constants: colour names, `SPACE_*`, `FONT_*`, `RADIUS_*`, `MIN_WINDOW`, `resolve_font_family(candidates) -> str` verified against `tkinter.font.families()`, `make_fonts(root)` returning a small dataclass of `CTkFont` objects. State that the mod browser is the one place that carries visual weight.
  22. **`ui/` package** — `ui/widgets.py` (focus-ring behaviour, `PrimaryButton`, `SecondaryButton`, `Sidebar`, `EmptyState`, `Banner`, `CodeLabel`, `IconCache` LRU keyed by project id holding `CTkImage` built on the UI thread), `ui/app.py` `MaestroApp(ctk.CTk)` (constructor signature, screens, `_drain_queue` every 50 ms, `dispatch(message)` routing, `show_error`, `show_banner`, `confirm`, `minsize`), `ui/account.py` `AccountScreen`, `ui/play.py` `PlayScreen` and `CrashPanel`, `ui/mods.py` `ModsScreen` (browser, installed pane, texture packs view, 300 ms debounce). For each: constructor signature, public methods called by `app.py`, and which messages it handles.
  23. **`main.py`** — `main(argv=None) -> int`: `--home PATH` override, dependency-import check that prints `pip install -r requirements.txt` guidance and exits 1 when a dependency is missing, logging setup, config load, first-run bootstrap (create the `default` instance skeleton and schedule bundled-mod install as a task), start the app.
  24. **Test conventions** — `tests/conftest.py` fixtures: `FakeAdapter(requests.adapters.BaseAdapter)` routing `(METHOD, url-without-query)` to a canned response, a callable, or a list consumed in order; it records every call with its kwargs so tests can assert `timeout == (10, 60)`; `make_response(status, json=None, content=b"", headers=None)`; `http` fixture returning `Http(adapter=FakeAdapter(...))`; `tmp_paths` fixture (`Paths.for_root(tmp_path)`). Markers: `live` (network), `display` (needs Tk). `pytest.ini` content.
  25. **`requirements.txt`** — pinned exactly: `customtkinter==6.0.0`, `requests==2.34.2`, `Pillow==12.3.0`, `pytest==9.1.1`, `pywin32==312; sys_platform == "win32"`.

- [ ] **Step 3: Self-check the contract against the spec.** Walk PLAN_1.md section by section (1 through 14) and confirm each requirement maps to a named symbol. Specifically confirm: no function reads `lib["downloads"]["artifact"]` for Fabric libraries; version ordering is by manifest index; features rules are evaluated; the `${` assertion exists; XErr codes are all mapped; the 404 profile case has its own error; both auth modes have their own endpoint constants; natives handle both models; `timeout=(10, 60)` is enforced in one place; every long operation takes `progress` and `cancel`. Fix gaps before committing.

- [ ] **Step 4: Write `requirements.txt` and `pytest.ini`** (`[pytest]`, `testpaths = tests`, `addopts = -m "not live"`, `markers = live: needs network`, `display: needs a Tk display`).

- [ ] **Step 5: Commit.**

```bash
git add contract.md requirements.txt pytest.ini
git commit -m "docs: freeze interface contract and design plan"
```

---

### Task 2: Foundations — errors, paths, messages, logging, progress, test fixtures

**Files:**
- Create: `errors.py`, `paths.py`, `messages.py`, `logsetup.py`, `core/__init__.py`, `core/progress.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_errors.py`, `tests/test_paths.py`, `tests/test_logsetup.py`, `tests/test_progress.py`

**Interfaces:**
- Consumes: `contract.md` sections 2, 3, 4, 5, 6, 24.
- Produces: everything later tasks import for errors, paths, messages, logging and cancellation; the `FakeAdapter`, `make_response` and `tmp_paths` fixtures every later test uses. The `http` fixture from contract section 24 is NOT created here (it needs `core/net.py`, which Task 3 creates); Task 3 adds it to `tests/conftest.py`.

- [ ] **Step 1: Read `PLAN_1.md` sections 5, 10, 11 and `contract.md` sections 2–6 and 24.**
- [ ] **Step 2: Write the tests first** (they fail on import):
  - `test_errors.py`: every class in contract section 2 exists, inherits from `LauncherError`, exposes `user_message` and `technical`; `XboxAccountError(2148916233)` has the "no Xbox profile" message and each other XErr code maps to its own message; unknown codes include the raw code and redirect URL; `NoJavaEditionError.user_message` contains the exact section 4.2 explanation.
  - `test_paths.py`: `Paths.default()` on each platform (monkeypatch `sys.platform` and env/home) yields the section 10 roots; `for_root` builds every subpath; `ensure()` creates the tree; `atomic_write_*` leaves no `.part` file and replaces existing content; `read_json` on a corrupt file raises `ConfigError`; hash helpers match `hashlib`; `posix_chmod_600` is a no-op on Windows and sets 0o600 on POSIX (skip when not POSIX).
  - `test_logsetup.py`: `Redactor` replaces a registered secret everywhere, redacts JWT-shaped strings, `access_token=…`, `refresh_token=…`, `device_code=…`, `Bearer …`, `XBL3.0 x=…`; `configure_logging(tmp_paths)` writes to `launcher.log` and a logged token never appears in the file.
  - `test_progress.py`: `CancelToken.raise_if_cancelled()` raises `CancelledError` only after `cancel()`; `Reporter` maps a child's (done, total) into the parent's range correctly at 0 %, 50 % and 100 %.
- [ ] **Step 3: Run `python -m pytest tests -q` and confirm the failures are import errors.**
- [ ] **Step 4: Implement the modules exactly per contract.**
- [ ] **Step 5: Run `python -m pytest tests -q`; all pass; output pristine.**
- [ ] **Step 6: Commit** (`feat: foundations — errors, paths, messages, logging, progress`).

---

### Task 3: HTTP wrapper, config, version manifest

**Files:**
- Create: `core/net.py`, `core/config.py`, `core/versions.py`
- Modify: `tests/conftest.py` (add the `http` fixture from contract section 24)
- Create: `tests/test_net.py`, `tests/test_config.py`, `tests/test_versions.py`

**Interfaces:**
- Consumes: Task 2 modules; `contract.md` sections 7, 8, 9.
- Produces: `Http`, `Config`, `VersionManifest` used by every later core task.

- [ ] **Step 1: Read `PLAN_1.md` sections 2, 6.4 (session pool), 7 (memory), 11 and `contract.md` sections 7–9.**
- [ ] **Step 2: Tests first:**
  - `test_net.py`: every call reaches the adapter with `timeout == (10, 60)`; `User-Agent` header is set; 500 then 200 retries and succeeds with injected `sleep` recording exponential delays with jitter; 429 retries; `ConnectionError` retries; 404 does not retry and raises `HttpStatusError` with the body; `download` writes atomically (no `.part` left), verifies sha1/sha256/sha512, raises `ChecksumError` on mismatch and removes the bad file, skips the request entirely when the existing file's hash matches, reports progress, and honours cancellation mid-stream.
  - `test_config.py`: absent file → defaults written with a fresh UUID `clientid`; corrupt JSON → defaults rewritten; unknown `auth_mode` → reset to `"entra"`; `memory_gb` above the cap is clamped; `max_memory_gb()` equals `min(ram - 4, 12)` with a floor of 2 for injected RAM values 8, 16, 64 and 4; `save_config` round-trips.
  - `test_versions.py`: manifest fixture with `26.2, 26.1.2, 1.21.11, 26.3-pre-1` proves `is_newer("26.2", "1.21.11")` is True and `is_newer("1.21.11", "26.2")` is False; `releases(include_snapshots=False)` excludes snapshots; `latest_release` matches `latest.release`; `fetch_manifest` caches to disk and serves the cache when the adapter raises `ConnectionError`; `fetch_version_json` verifies the entry sha1 and re-downloads a tampered cache; `java_major` reads `javaVersion.majorVersion` and raises `ManifestError` when absent.
- [ ] **Step 3: Confirm the tests fail, implement, run `python -m pytest tests -q`, all pass.**
- [ ] **Step 4: Commit** (`feat(core): http wrapper, config, version manifest`).

---

### Task 4: Authentication

**Files:**
- Create: `auth.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Consumes: Tasks 2–3; `contract.md` section 10.
- Produces: `Account`, `AccountStore`, `sign_in`, `refresh`, `ensure_fresh` used by `ui/account.py`, `core/pipeline.py`, `main.py`.

- [ ] **Step 1: Read `PLAN_1.md` section 4 completely, the auth part of the api-facts file, and `contract.md` section 10.**
- [ ] **Step 2: Tests first** (all HTTP through `FakeAdapter`; response bodies from the api-facts file):
  - Entra mode: device code start posts to the `consumers/v2.0/devicecode` URL with the right scope; polling sequence `authorization_pending` (HTTP 400) → `slow_down` (interval grows by 5 s, checked through injected `sleep`) → success; `expired_token` raises `AuthExpiredError`; `authorization_declined` raises `AuthDeclinedError`; `ConnectionError` during polling surfaces as `NetworkError` with its own message; cancellation stops the loop and raises `CancelledError`.
  - Live mode: start posts to `login.live.com/oauth20_connect.srf` with `client_id=00000000402b5328`, the MBI_SSL scope and `response_type=device_code`; token poll hits `oauth20_token.srf` with the device-code grant; the RpsTicket uses the `t=` prefix while Entra uses `d=`; no Live test touches an Entra URL and vice versa (assert on the recorded calls).
  - XBL then XSTS: `uhs` and `xid` are extracted; XSTS 401 with each XErr code raises `XboxAccountError` with the mapped `user_message`.
  - `login_with_xbox` sends `XBL3.0 x={uhs};{xsts}`; `fetch_profile` 404 raises `NoJavaEditionError`, 401 raises `TokenExpiredError`, 403 raises `AuthError`.
  - `sign_in` returns an `Account` with absolute expiry timestamps computed from `expires_in` using an injected clock.
  - `ensure_fresh` refreshes when the token expires within 300 s and leaves a fresh token alone; refresh uses the endpoint family matching `auth_mode` and re-runs XBL → XSTS → Mojang → profile.
  - `AccountStore` round-trips; on Windows with `win32crypt` importable the file is DPAPI-wrapped and not plaintext (skip on non-Windows); when `win32crypt` import is forced to fail the store falls back to plaintext and still round-trips; on POSIX the file mode is 0o600.
  - Redaction: every token, refresh token and device code returned by the fake responses is registered with the `Redactor`; a log record containing one is redacted.
- [ ] **Step 3: Implement `auth.py`, including the Path A / Path B comment block at the top.**
- [ ] **Step 4: Run `python -m pytest tests -q`; all pass. Commit** (`feat: Microsoft, Xbox and Mojang authentication`).

---

### Task 5: Java runtime provisioning (Adoptium)

**Files:**
- Create: `core/runtime.py`
- Create: `tests/test_runtime.py`

**Interfaces:**
- Consumes: Tasks 2–3; `contract.md` section 11.
- Produces: `ensure_runtime` used by `core/pipeline.py`.

- [ ] **Step 1: Read `PLAN_1.md` section 3, the Adoptium part of the api-facts file, and `contract.md` section 11.**
- [ ] **Step 2: Tests first:**
  - `adoptium_arch()` maps `AMD64`/`x86_64` → `x64` and `arm64`/`aarch64` → `aarch64`; `adoptium_os()` maps to `windows`/`linux`/`mac`.
  - `query_adoptium` sends all seven query parameters with `image_type=jre` and parses `binaries[0].package`.
  - `install_runtime` with a zip built in the test (top-level `jdk-25.0.4.1+1-jre/bin/java.exe` plus a sibling file): verifies SHA-256 (mismatch raises `ChecksumError` and leaves no runtime dir), extracts to a temp dir, flattens the top-level directory so `runtimes/java-25/bin/java.exe` exists, uses `os.replace` (no partially extracted directory remains when extraction fails midway, simulated by a corrupt member).
  - A tar.gz built in the test with `<top>/Contents/Home/bin/java` flattens to `bin/java`; on POSIX every file in `bin/` ends up 0o755 (skip the mode assertion on Windows but still run the flatten).
  - `runtime_is_valid` returns True only when the executable exists and the injected `run` returns exit 0; `ensure_runtime` skips download when valid and downloads when the runtime is missing or `java -version` fails.
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): Adoptium runtime provisioning`).

---

### Task 6: Mojang libraries, rules and natives

**Files:**
- Create: `core/libraries.py`
- Create: `tests/test_libraries.py`

**Interfaces:**
- Consumes: Tasks 2–3; `contract.md` section 12.
- Produces: `rules_allow`, `maven_path`, `select_libraries`, `download_libraries`, `download_client_jar`, `extract_natives` used by `core/fabric.py`, `core/launch.py`, `core/pipeline.py`.

- [ ] **Step 1: Read `PLAN_1.md` sections 6.1, 6.2 and `contract.md` section 12.**
- [ ] **Step 2: Tests first:**
  - `rules_allow`: no rules → allow; `[{allow, os:{name: windows}}]` allows on windows and denies on linux; `[{allow}, {disallow, os:{name: osx}}]` denies on osx; `os.arch` rule matches `x86` only when arch is `x86`; `os.version` regex `^10\\.` matches a Windows 10/11 version string; a `features` rule with `is_demo_user: true` denies when the feature map says False and allows when True; rules present but none matching → deny.
  - `maven_path("org.lwjgl:lwjgl:3.3.3:natives-windows")` → `org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3-natives-windows.jar`; `maven_path("com.mojang:jtracy:1.0.37")` → `com/mojang/jtracy/1.0.37/jtracy-1.0.37.jar`.
  - `select_libraries` with a fixture containing a plain library, a `natives-windows` entry gated to windows, a `natives-linux` entry gated to linux, and a legacy library with `natives` + `downloads.classifiers`: on windows the plain, `natives-windows`, and legacy entries are selected, and the `natives-windows` jar is on the classpath (spec section 6.2 second bullet), the legacy one is marked for extraction.
  - `download_libraries` skips a file whose sha1 already matches (adapter records zero calls for it), downloads a missing one, and raises `ChecksumError` on a tampered body.
  - `extract_natives` extracts from a zip built in the test into `natives/` honouring `extract.exclude` (`META-INF/` excluded) and creates the directory even when there is nothing to extract.
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): library rules, downloads and natives`).

---

### Task 7: Fabric loader integration

**Files:**
- Create: `core/fabric.py`
- Create: `tests/test_fabric.py`

**Interfaces:**
- Consumes: Tasks 2–3, 6; `contract.md` section 13.
- Produces: `choose_loader`, `fetch_profile`, `merge_profile`, `compare_versions`, `download_fabric_libraries` used by `core/pipeline.py`.

- [ ] **Step 1: Read `PLAN_1.md` section 6.3, the Fabric part of the api-facts file, and `contract.md` section 13.**
- [ ] **Step 2: Tests first:**
  - `choose_loader` picks the first `stable: true` entry even when index 0 is unstable, and falls back to index 0 when none is stable.
  - `fabric_library_url` for `org.ow2.asm:asm:9.10.1` with url `https://maven.fabricmc.net/` yields `https://maven.fabricmc.net/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar` and the `.sha1` sidecar URL.
  - `fabric_library_sha1` uses the inline `sha1` without any HTTP call, and fetches the sidecar when the entry lacks one.
  - Code never indexes `["downloads"]["artifact"]` on a Fabric library: a Fabric entry without `downloads` downloads correctly.
  - `compare_versions("9.10.1", "9.7") > 0`, `("9.7", "9.7") == 0`, `("0.16.0-beta.1", "0.16.0") < 0`, `("1.10", "1.9") > 0`.
  - `merge_profile`: Fabric libraries come first; a Mojang `org.ow2.asm:asm:9.6` is dropped in favour of Fabric's `9.10.1`; a Fabric lib older than Mojang's is dropped in favour of Mojang's; `mainClass` comes from the profile; a profile with a different `mainClass` still uses the profile's value and logs a warning (assert with `caplog`); `arguments.jvm` and `arguments.game` are concatenated after the vanilla ones; the result is written to `versions/{id}/fabric-merged.json` atomically.
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): Fabric loader profile and library merge`).

---

### Task 8: Assets and launch arguments

**Files:**
- Create: `core/assets.py`, `core/launch.py`
- Create: `tests/test_assets.py`, `tests/test_launch.py`

**Interfaces:**
- Consumes: Tasks 2–3, 6; `contract.md` sections 14, 15.
- Produces: `download_assets`, `game_assets_dir`, `build_variables`, `evaluate_arguments`, `substitute`, `build_launch_plan` used by `core/pipeline.py` and `process.py`.

- [ ] **Step 1: Read `PLAN_1.md` sections 6.4 and 7, and `contract.md` sections 14–15.**
- [ ] **Step 2: Tests first:**
  - Assets: index is written to `assets/indexes/{id}.json` and verified by sha1; objects land at `assets/objects/{hash[:2]}/{hash}` fetched from `https://resources.download.minecraft.net/{hash[:2]}/{hash}`; an object whose hash already matches is not requested; progress reports done/total in objects; a `virtual: true` index also materialises `assets/virtual/{id}/{name}`; a `map_to_resources: true` index copies into the instance `resources/` directory; the executor uses at most 16 workers (inject a recording executor factory or assert `max_workers`).
  - Launch: `evaluate_arguments` keeps plain strings, includes an `os`-gated value only on the matching OS, includes a list `value` as multiple argv entries, and drops the `--quickPlayPath ${quickPlayPath}` entry when `has_quick_plays_support` is False; `substitute` fills every variable in spec section 7 and raises `UnresolvedPlaceholderError` for a leftover `${foo}`; `build_variables` sets `user_type == "msa"`, `auth_xuid` from the account, `clientid` from config, `classpath_separator` `;` on Windows and `:` elsewhere, `launcher_name == "MaestroLauncher"`; `memory_flags(6)` → `["-Xmx6G", "-Xms6G"]`; `build_launch_plan` puts the java path first, then JVM args, `-Djava.library.path=<natives>` present, `mainClass`, then game args, and no argv element contains `${`.
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): assets download and launch arguments`).

---

### Task 9: Modrinth client and mod management

**Files:**
- Create: `core/modrinth.py`
- Create: `tests/test_modrinth.py`

**Interfaces:**
- Consumes: Tasks 2–3; `contract.md` section 16.
- Produces: `ModrinthClient`, `InstallPlan`, `list_installed`, `set_enabled`, `delete_mod`, `check_updates` used by `core/instances.py` and `ui/mods.py`.

- [ ] **Step 1: Read `PLAN_1.md` section 9, the Modrinth part of the api-facts file, and `contract.md` section 16.**
- [ ] **Step 2: Tests first:**
  - Every request carries the exact `User-Agent` from spec section 9.
  - `search` for mods builds `facets` as URL-encoded JSON `[["project_type:mod"],["categories:fabric"],["versions:26.2"]]`, resource packs use `[["project_type:resourcepack"],["versions:26.2"]]` with no loader facet; `offset`/`limit` are passed; `SearchPage.total_hits` is parsed and a second page uses `offset=20`.
  - `resolve_version` picks the newest entry and its `primary: true` file (a fixture where the primary file is not first).
  - `resolve_install_plan`: A requires B (by `project_id`) and C (by `version_id`), C requires B again, B requires A (cycle) — the plan lists each exactly once, dependencies before dependents, and `optional`/`incompatible`/`embedded` dependencies are not installed; a project with no version for the game version raises `DependencyResolutionError` naming the project; already-installed projects are reported in `already_installed` and not re-downloaded.
  - `install` verifies sha512 (mismatch raises `ChecksumError` and leaves nothing in `mods/`), writes atomically, and records project/version ids in the sidecar file.
  - Rate limiting: a response with `X-Ratelimit-Remaining: 0` and `X-Ratelimit-Reset: 2` makes the next call wait 2 s through the injected `sleep`; a 429 that keeps failing raises `RateLimitedError`.
  - `read_fabric_mod_json` reads name, version, description and icon path from a jar built in the test; `list_installed` lists `.jar` and `.jar.disabled` files with `enabled` set correctly and falls back to the filename when a jar has no `fabric.mod.json`; `set_enabled` renames `.jar` ↔ `.jar.disabled`; `delete_mod` removes the file and the sidecar entry; `check_updates` flags a mod whose newest version id differs from the recorded one.
  - `fetch_icon_bytes` returns raw bytes; `core/modrinth.py` never imports `PIL`, `tkinter` or `customtkinter` (assert by scanning the module source for those import statements).
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): Modrinth search, dependency resolution and mod management`).

---

### Task 10: Instances and the launch pipeline

**Files:**
- Create: `core/instances.py`, `core/pipeline.py`
- Create: `tests/test_instances.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 2–9; `contract.md` sections 17, 18.
- Produces: `InstanceManager`, `prepare_launch` used by `ui/play.py`, `ui/mods.py`, `main.py`.

- [ ] **Step 1: Read `PLAN_1.md` sections 9 ("Bundled-by-default mods"), 10 and `contract.md` sections 17–18.**
- [ ] **Step 2: Tests first:**
  - `create` builds every directory from spec section 10 plus `options.txt` and `instance.json`; invalid names (empty, `..`, path separators, reserved Windows names) raise `InstanceError` with a helpful `user_message`; duplicate names raise; `rename` moves the directory and updates `instance.json`; `delete` removes the tree and refuses to delete a running instance when told so through a parameter; `list` returns instances sorted by name.
  - `install_bundled_mods` calls `resolve_install_plan` for `fabric-api` and `sodium` through the normal path (assert the same public method is used, no special-casing); when Sodium has no version for the game version the instance is still created, Fabric API is installed, and `missing` carries `"Sodium isn't available for 26.3 yet."` for game version `26.3`.
  - `prepare_launch` with fakes for every step (monkeypatch the step functions) runs them in the contract's exact order, forwards `cancel`, and stops at the first `CancelledError`; the returned `LaunchPlan.cwd` is the instance directory and `argv` contains the Fabric main class when Fabric is enabled.
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat(core): instances and launch pipeline`).

---

### Task 11: Game process supervision

**Files:**
- Create: `process.py`, `tasks.py`
- Create: `tests/test_process.py`, `tests/test_tasks.py`

**Interfaces:**
- Consumes: Tasks 2, 8; `contract.md` sections 19, 20.
- Produces: `GameProcess`, `TaskRunner` used by `ui/`.

- [ ] **Step 1: Read `PLAN_1.md` sections 5 and 8, and `contract.md` sections 19–20.**
- [ ] **Step 2: Tests first** (use `sys.executable` running a small inline Python script as the fake game):
  - `GameProcess.start()` spawns with `shell=False`, `cwd` = instance dir, `CREATE_NO_WINDOW` on Windows / `start_new_session` on POSIX (assert through a recording `Popen` wrapper); stdout and stderr lines both reach `logs/latest.log` and the queue as `LogLine`; a script exiting 3 yields `GameExited(exit_code=3)` with `log_tail` limited to the last 200 lines of a 300-line output and `hint` matching the `UnsupportedClassVersionError` pattern when the output contains it; `stop()` terminates a long-running script and `is_running` becomes False; `hint` for `OutOfMemoryError`, `Mixin apply failed`, and a missing Fabric API message (`requires any version of fabric-api` style text) each map to their plain-English hint.
  - `TaskRunner.submit` posts `TaskFinished(result)` on success; a function raising `LauncherError` posts `TaskFailed` with its `user_message`; a function raising `ValueError` posts `TaskFailed` with the generic fallback sentence and the exception attached; `progress_fn(task_id)` posts `Progress` messages; nothing is ever raised on the worker thread unhandled (the executor keeps working after a failure).
- [ ] **Step 3: Implement, run `python -m pytest tests -q`, all pass. Commit** (`feat: game process supervision and task runner`).

---

### Task 12: Theme tokens

**Files:**
- Create: `theme.py`
- Create: `tests/test_theme.py`

**Interfaces:**
- Consumes: `contract.md` section 21 (the frozen design plan).
- Produces: every constant the `ui/` package uses.

- [ ] **Step 1: Read `PLAN_1.md` section 13 and `contract.md` section 21.**
- [ ] **Step 2: Tests first:**
  - Contrast: a WCAG relative-luminance function in the test computes contrast for `TEXT_PRIMARY` and `TEXT_MUTED` against `SURFACE` and `SURFACE_RAISED`, and for the accent button's label against `ACCENT`; each is ≥ 4.5.
  - Exactly one accent constant; spacing constants are exactly `{4, 8, 12, 16, 24, 32}`; exactly two radius constants; exactly three font sizes; `MIN_WINDOW` is defined.
  - `resolve_font_family(["NoSuchFont", "Segoe UI", "Arial"])` returns the first family present in `tkinter.font.families()` and returns the last candidate when none exist (mark `display`, skip when Tk cannot start).
  - `grep`-style test: no `.py` file under the repo other than `theme.py` (excluding the `tests/` directory) contains a `#RRGGBB` or `#RGB` colour literal — this test is added now and keeps guarding later UI tasks.
- [ ] **Step 3: Implement `theme.py` with the palette rationale comment at the top exactly as frozen in the contract. Run tests, commit** (`feat: theme tokens`).

---

### Task 13: UI shell — app window, sidebar, queue drain, shared widgets

**Files:**
- Create: `ui/__init__.py`, `ui/widgets.py`, `ui/app.py`
- Create: `tests/test_ui_app.py`, `tools/screenshot_ui.py`

**Interfaces:**
- Consumes: Tasks 2, 11, 12; `contract.md` section 22 (`widgets.py`, `app.py`).
- Produces: `MaestroApp` with placeholder screen frames that Tasks 14–15 replace; `IconCache`, `Sidebar`, buttons, `EmptyState`, `Banner`, `CodeLabel`; `tools/screenshot_ui.py` which opens the app against a temporary home directory, switches to each screen, and saves `account.png`, `play.png`, `mods.png` to a directory given on the command line using `PIL.ImageGrab.grab(bbox=<window bbox>)`.

- [ ] **Step 1: Read `PLAN_1.md` sections 5, 12, 13 and `contract.md` sections 21–22.**
- [ ] **Step 2: Tests first** (marked `display`, skipped without Tk):
  - `MaestroApp` constructs against `tmp_paths`, sets `minsize` to `MIN_WINDOW`, shows three sidebar entries named exactly "Account", "Play", "Mods", and switching screens raises the right frame.
  - `_drain_queue` routes `Progress`, `TaskFinished`, `TaskFailed`, `LogLine`, `AuthCode`, `GameStarted`, `GameExited` to the registered screen handlers (register recording stubs); a `TaskFailed` shows the error dialog with the `user_message` (dialog creation injectable for the test); the drain reschedules itself with `after(50, ...)`.
  - `IconCache` is an LRU bounded at its stated capacity, evicts the oldest, and builds `CTkImage` from bytes (WebP bytes made with Pillow in the test).
  - Every button created through `widgets.py` has a visible focus indicator: focusing it changes `border_color` to the focus colour and unfocusing restores it; targets are at least 32 px tall.
  - No raw hex in `ui/` (Task 12's guard test now covers these files).
- [ ] **Step 3: Implement. Run `python -m pytest tests -q`. Run `python tools/screenshot_ui.py <dir>` and confirm three PNGs are written. Commit** (`feat(ui): application shell, sidebar and shared widgets`).

---

### Task 14: Account and Play screens

**Files:**
- Create: `ui/account.py`, `ui/play.py`
- Modify: `ui/app.py` (replace the two placeholder frames)
- Create: `tests/test_ui_account_play.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 10, 11, 13; `contract.md` section 22 (`account.py`, `play.py`).
- Produces: `AccountScreen`, `PlayScreen`, `CrashPanel`.

- [ ] **Step 1: Read `PLAN_1.md` sections 4.1 (what to tell the user), 7 (memory note), 8 (crash panel), 12 (screens 1–2), 13, and `contract.md` section 22.**
- [ ] **Step 2: Tests first** (`display`):
  - Account: "Sign in" starts a task; an `AuthCode` message puts the code in the large monospace `CodeLabel`, enables "Copy code" (clipboard receives the code) and the link opens `verification_uri` through an injected opener; the waiting state text is shown; "Cancel" sets the `CancelToken` and the screen returns to the signed-out state; `TaskFinished` with an `Account` shows the player name and a "Sign out" button; `TaskFailed` shows the `user_message` in-screen (not only a dialog).
  - Play: version dropdown lists releases only until the snapshots switch is on; instance dropdown lists instances with create/rename/delete actions that call `InstanceManager` (fakes) and confirm before delete; the memory slider ranges 2..`max_memory_gb()` and persists to config; the note about more RAM not being faster is present; `Progress` updates the determinate bar and per-file label; `GameStarted` turns the button into "Running — Stop"; `GameExited(exit_code=1)` shows the `CrashPanel` with the tail and hint and a "Copy log" button that fills the clipboard; `GameExited(exit_code=0)` does not show the crash panel; the Play button is disabled while no account is signed in with a message naming the next action.
- [ ] **Step 3: Implement; run tests; run `python tools/screenshot_ui.py <dir>`; commit** (`feat(ui): account and play screens`).

---

### Task 15: Mods screen — browser, installed pane, texture packs

**Files:**
- Create: `ui/mods.py`
- Modify: `ui/app.py` (replace the placeholder frame)
- Create: `tests/test_ui_mods.py`

**Interfaces:**
- Consumes: Tasks 9, 10, 13; `contract.md` section 22 (`mods.py`).
- Produces: `ModsScreen`.

- [ ] **Step 1: Read `PLAN_1.md` sections 9 ("Management"), 12 (screen 3), 13 (Restraint: this screen carries the visual weight) and `contract.md` sections 21–22.**
- [ ] **Step 2: Tests first** (`display`):
  - Typing in the search box does not call `search` until 300 ms of silence (drive the Tk event loop with `after` and a fake clock); results render title, author, description, download count and an icon placeholder; icons arrive as bytes through `TaskFinished` and are turned into `CTkImage` only in the UI handler (assert the worker function returns bytes); scrolling back to a project already cached does not re-request it.
  - "Install" on a result resolves the plan in a task, shows the full list of what will be installed (root plus required dependencies) in a confirmation, and only then installs; the button reads "Install", then "Installing…" with determinate progress, then "Installed".
  - Installed pane lists mods from `list_installed` with name, version, description; toggle renames; delete asks for confirmation; toggling or deleting Fabric API shows the explicit warning first; the "Update available" badge appears for entries flagged by `check_updates`; the empty state text tells the player what to do next.
  - Texture Packs view searches with the resource-pack facets and installs into `resourcepacks/`.
  - Pagination: "Show more" requests `offset + 20` and appends.
- [ ] **Step 3: Implement; run tests; run `python tools/screenshot_ui.py <dir>`; commit** (`feat(ui): mod browser, installed mods and texture packs`).

---

### Task 16: Entry point and README

**Files:**
- Create: `main.py`, `README.md`
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: everything; `contract.md` section 23.
- Produces: `python main.py`.

- [ ] **Step 1: Read `PLAN_1.md` sections 0 (README expectations in 14), 4.1, 11, 14 and `contract.md` section 23.**
- [ ] **Step 2: Tests first:**
  - `main(["--home", tmp])` with a missing dependency (monkeypatch `builtins.__import__` to fail for `customtkinter`) prints the `pip install -r requirements.txt` guidance and returns 1 without a traceback.
  - With a corrupt `config.json` in the home directory, startup rewrites defaults and proceeds (inject a fake `MaestroApp` factory so no window opens).
  - First run creates the `default` instance skeleton and schedules exactly one bundled-mod install task; a second run does not create another instance.
  - `launcher.log` exists after startup and a logged token is redacted.
- [ ] **Step 3: Implement `main.py`. Write `README.md`: what it is, setup (`pip install -r requirements.txt`, `python main.py`), how to register the Entra app for Path A (portal steps, "Mobile and desktop applications", "Allow public client flows" = Yes, the Minecraft third-party launcher access form), how to switch `auth_mode` to `"live"`, the `core`/`ui` package amendment, where data lives per platform, known limitations (Sodium availability per version, Vulkan backend note, macOS best-effort, no offline play without a prior sign-in).**
- [ ] **Step 4: Run `python -m pytest tests -q`; run `python main.py --home <tmpdir>` for five seconds in the background and confirm it starts and exits cleanly when closed; commit** (`feat: entry point and README`).

---

### Task 17: End-to-end verification on the real machine

**Files:**
- Create: `tests/test_live.py` (marked `live`)
- Create: `tools/e2e_launch.py`
- Modify: whatever the run proves broken (each fix committed separately with a `fix:` prefix and reported)

**Interfaces:**
- Consumes: the whole program.
- Produces: a written report at the path given in the dispatch, plus screenshots.

- [ ] **Step 1: Write `tests/test_live.py`** (marked `live`): fetches the real manifest and asserts `latest.release` resolves; fetches the Fabric loader list for that release and gets a profile; resolves `fabric-api` and `sodium` install plans on Modrinth for that release; queries Adoptium for the release's Java major. Run with `python -m pytest -m live -q`.
- [ ] **Step 2: Write `tools/e2e_launch.py`:** using the real `Paths.default()`, an `Http`, the loaded config, and a placeholder offline `Account` (name `Player`, all-zero UUID, access token `"0"`, xuid `"0"`, no refresh token), create or reuse an instance named `e2e-check` for the latest release, install bundled mods, run `prepare_launch` with console progress, then start `GameProcess` and wait up to 120 s for a `LogLine` containing `Loading Minecraft` and one containing `Sodium` (or `sodium`), then `stop()`; exit 0 only when both appeared and the process was still running when stopped (a crash before that is a failure). Print the tail on failure.
- [ ] **Step 3: Run it.** Fix real defects it exposes (in the module that owns them) with their own tests, re-run until it passes. Delete the `e2e-check` instance afterwards through `InstanceManager.delete`.
- [ ] **Step 4: Run `python tools/screenshot_ui.py <report-dir>` and `python -m pytest -q`** (all offline tests) one final time.
- [ ] **Step 5: Write the report and commit** (`test: live checks and end-to-end launch tool`).
