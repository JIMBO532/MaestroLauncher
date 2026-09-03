# Build Task: "MaestroLauncher v1" — a zero-config Minecraft Java launcher

You are an expert systems engineer and desktop application architect. Build a complete,
production-ready custom Minecraft: Java Edition launcher: Sodium pre-installed out of the
box, one-click mod and resource-pack installation, no manual configuration of any kind.

Write real, fully implemented code. No pseudocode, no `// TODO`, no `pass  # implement
later`, no abridged functions. If a function is hard, write it anyway.

---

## 0. DELIVERY PROTOCOL — READ THIS FIRST

This project is roughly 3,000–4,000 lines. Do **not** attempt it in one response; you will
be truncated and the result will be unusable.

**Response 1:** Output ONLY `contract.md` — the frozen interface contract:
- Every module, every public class, every public function, with exact signatures and type
  hints, docstring one-liners, and the exceptions each raises.
- The exact JSON schema of `config.json`.
- The exact shape of every message put on the UI event queue (see §5).
- `requirements.txt` with pinned versions.
Then **stop and wait** for me to say "continue".

Also include in Response 1 the **design plan** required by §13: the token block
(colour, spacing, type, radius) plus one ASCII wireframe per screen, already checked against
the anti-defaults list. Freezing the tokens before any UI code exists is the point.

**Responses 2–7:** One module per response, in this order: `errors.py` + `paths.py`
(combined), `auth.py`, `core.py`, `process.py`, `theme.py` + `ui.py`, `main.py`. Each must
match `contract.md` exactly. If you discover the contract was wrong, say so explicitly at
the top of the response and state the amendment — do not silently diverge.

If you run low on output budget mid-module, stop at a function boundary and say
`--- CONTINUE FROM: <function name> ---`. Never truncate mid-function and never summarise.

---

## 1. STACK

- Python 3.12, `CustomTkinter` (dark mode), `requests`, `Pillow`.
- Concurrency: `concurrent.futures.ThreadPoolExecutor`. Primary dev/test target is
  **Windows 11**; Linux paths must be implemented, not stubbed. macOS may be best-effort
  but must not crash on import.
- No external launcher libraries (`minecraft-launcher-lib` etc.). Implement the protocol.

---

## 2. VERSION TARGETING — DO NOT HARDCODE

Minecraft moved to **calendar versioning in 2026**. The `1.x` line ended at `1.21.11`;
current releases are `26.1`, `26.2`, and so on. There is no 1.22. **String comparison
cannot order these versions** — `"26.2" > "1.21.11"` is false lexically but true in
reality. Do not write a version comparator that assumes semver.

Requirements:
- Resolve the version list from `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json`.
  Use `latest.release` as the default; use manifest **order** (newest first) for "which is
  newer", never string sorting.
- The user may pick any release version from a dropdown. Snapshots are filtered out by
  default with a toggle to include them.
- **Java version must be read from the version JSON's `javaVersion.majorVersion` field**,
  not hardcoded. (1.21.x needs 21; 26.1+ needs 25; future versions will differ.) The
  runtime provisioner takes this integer as a parameter.

---

## 3. RUNTIME PROVISIONING (Adoptium)

`GET https://api.adoptium.net/v3/assets/feature_releases/{major}/ga` with **all** required
query parameters, or the response is a huge unusable paginated blob:

```
architecture=x64|aarch64
image_type=jre
os=windows|linux|mac
vendor=eclipse
jvm_impl=hotspot
heap_size=normal
page_size=1
```

Notes that must be respected:
- There is **no "headless" image type**. Use `image_type=jre`. Minecraft needs AWT.
- Detect architecture with `platform.machine()`; map `AMD64`/`x86_64` → `x64`,
  `arm64`/`aarch64` → `aarch64`.
- Windows ships `.zip`, Linux/macOS ship `.tar.gz`. Handle both. **`zipfile` does not
  preserve the executable bit** — after extracting on any POSIX platform, `os.chmod(0o755)`
  every file in `bin/`.
- Verify the download against the `checksum` field in the Adoptium response before
  extracting. Extract atomically (temp dir → `os.replace`), never leaving a half-extracted
  JRE that looks valid on next launch.
- Cache per major version: `runtimes/java-{major}/`. Skip download if
  `bin/java(.exe)` exists and `java -version` exits 0.

---

## 4. AUTHENTICATION

### 4.1 Client ID — decide this explicitly and tell the user

Present both paths in a comment block at the top of `auth.py`, and read the client ID from
`config.json` with a constant fallback:

- **Path A (correct):** the user registers their own Microsoft Entra public-client app
  ("Mobile and desktop applications", "Allow public client flows" = Yes), then applies for
  Minecraft API access via Microsoft's third-party launcher form. Use
  `https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode` and `.../token`.
- **Path B (what most hobby launchers actually do):** the legacy Minecraft client ID
  `00000000402b5328`. This is a **Live** app registration, not an Entra app — it does
  **not** work against the `login.microsoftonline.com/consumers/v2.0` endpoints. It must be
  used with the Live endpoints:
  - Device code: `POST https://login.live.com/oauth20_connect.srf`
    body `client_id=...&scope=service::user.auth.xboxlive.com::MBI_SSL&response_type=device_code`
  - Token poll: `POST https://login.live.com/oauth20_token.srf`
    body `client_id=...&device_code=...&grant_type=urn:ietf:params:oauth:grant-type:device_code`

Implement **both**, selected by a `auth_mode: "entra" | "live"` key in `config.json`,
defaulting to `"entra"`. Do not silently mix endpoints across the two modes.

### 4.2 Chain

1. Device code → poll token endpoint. Handle `authorization_pending` (keep polling at the
   returned `interval`), `slow_down` (increase interval by 5s), `expired_token`,
   `authorization_declined`, and network failure separately, each with a distinct message.
2. `POST https://user.auth.xboxlive.com/user/authenticate` →
   extract `Token` and `DisplayClaims.xui[0].uhs`.
3. `POST https://xsts.auth.xboxlive.com/xsts/authorize`
   (`RelyingParty: rp://api.minecraftservices.com/`) →
   extract `Token` **and `DisplayClaims.xui[0].xid` (the XUID — you will need it at launch)**.
   On HTTP 401, parse the `XErr` field and map to plain-English messages:
   - `2148916233` — account has no Xbox profile; sign in at xbox.com once first
   - `2148916235` — Xbox Live unavailable in this account's country
   - `2148916236` / `2148916237` — adult verification required
   - `2148916238` — account is a child and must be added to a Family group
   - anything else — show the raw XErr and Redirect URL
4. `POST https://api.minecraftservices.com/authentication/login_with_xbox`
   body `{"identityToken": "XBL3.0 x={uhs};{xsts}"}` → `access_token`, `expires_in`.
5. `GET https://api.minecraftservices.com/minecraft/profile` with the Bearer token.
   **A 404 here means the account does not own Minecraft: Java Edition** (or is a Game Pass
   account that has never opened the official launcher). This is NOT an auth failure —
   surface it as its own error type with that exact explanation. A 401 means the token is
   expired; a 403 means something else. Do not collapse these into one handler.

### 4.3 Caching and silent refresh

- Persist: Microsoft `refresh_token`, Mojang `access_token`, `xuid`, `uuid`, `name`, and
  **absolute expiry timestamps** computed from `expires_in` at receipt time.
- On startup, refresh proactively if the Mojang token expires within 5 minutes rather than
  waiting for a 401 round-trip. Still handle a surprise 401 as a fallback.
- Refresh grant: `grant_type=refresh_token&refresh_token=...&client_id=...` against
  whichever endpoint family `auth_mode` selects, then re-run steps 2–5.
- Write the token cache with `0o600` on POSIX. On Windows, write it under `%APPDATA%` and
  note in a comment that DPAPI (`win32crypt.CryptProtectData`) would be the hardening step;
  implement it if `pywin32` imports, fall back to plaintext if not.
- Never log a token, refresh token, or device code. Redact them in every log path.

---

## 5. CONCURRENCY AND UI THREAD SAFETY — NON-NEGOTIABLE

Tkinter is not thread-safe. Touching a widget from a worker thread produces intermittent,
undebuggable crashes. The contract:

- Worker threads **never** touch a widget, a `StringVar`, or a `CTkImage`.
- Workers push plain dataclass messages onto a single `queue.Queue`.
- The UI runs `self.after(50, self._drain_queue)` in a self-rescheduling loop and is the
  only code that mutates widgets.
- Define the message types up front in `contract.md`: at minimum `Progress(task_id, label,
  done, total)`, `TaskFinished(task_id, result)`, `TaskFailed(task_id, exc, user_message)`,
  `LogLine(text)`, `AuthCode(code, url)`.
- Every `Future` gets a `add_done_callback` that catches **everything** and posts
  `TaskFailed` — an unhandled exception inside a worker must never vanish silently.

---

## 6. MANIFEST ENGINE AND CLASSPATH

### 6.1 Mojang libraries
- Evaluate `rules` for `os.name`, **`os.arch`**, and `os.version` (regex). Default action
  when no rule matches is deny.
- Verify every library and `client.jar` against its published SHA-1 before use. Skip
  download if the on-disk hash already matches. Download atomically (`.part` → rename).

### 6.2 Natives — this is where naive launchers break
Modern versions (1.19+, including all 26.x) **no longer use the old
`natives.<os>` + `downloads.classifiers` extraction model**. LWJGL natives now arrive as
ordinary library entries named e.g. `org.lwjgl:lwjgl:3.3.x:natives-windows` with a normal
`downloads.artifact`, gated by an OS rule, and they belong **on the classpath**.

Implement both paths:
- If a library has `downloads.classifiers` + a `natives` map → extract to
  `instances/{name}/natives/`, honouring `extract.exclude`.
- Otherwise, if it has an OS rule and a `natives-*` classifier in its Maven name → put the
  jar on the classpath like any other library.
- Create the natives directory regardless (it is still passed as `-Djava.library.path`).

### 6.3 Fabric
- Loader list: `GET https://meta.fabricmc.net/v2/versions/loader/{game_version}` → pick the
  first entry with `loader.stable == true`; fall back to index 0 if none are stable.
- Profile: `GET https://meta.fabricmc.net/v2/versions/loader/{game_version}/{loader_version}/profile/json`
- **Fabric library entries have no `downloads` block.** They have `name` (Maven GAV) and
  `url` (a Maven root). You must build the path yourself:
  `{url}{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar`, and fetch
  `<that>.sha1` separately for verification. Code that does
  `lib["downloads"]["artifact"]["url"]` will crash on every Fabric library — do not write it.
- Take `mainClass` from the Fabric profile JSON. Do not hardcode
  `net.fabricmc.loader.impl.launch.knot.KnotClient` — assert it matches and log a warning
  if it doesn't, but use what the profile says.
- Merge order: Fabric libraries first, then Mojang's, de-duplicated by `group:artifact`
  keeping the **higher** version (Fabric intentionally overrides some Mojang libs).

### 6.4 Assets
- Asset index → `assets/indexes/{id}.json`; objects → `assets/objects/{hash[:2]}/{hash}`
  from `https://resources.download.minecraft.net/{hash[:2]}/{hash}`.
- ThreadPoolExecutor capped at 16. Use a single `requests.Session` with
  `HTTPAdapter(pool_connections=16, pool_maxsize=32)` — the default pool of 10 will
  throttle and emit warnings under 16 workers.
- Hash-check before downloading; ~4,000 objects, so skipping is the difference between
  3 seconds and 3 minutes on relaunch.
- Handle the `map_to_resources` / `virtual` flags in the index for completeness even though
  current versions don't set them.

---

## 7. LAUNCH ARGUMENTS

Evaluate `arguments.jvm` and `arguments.game` arrays. Each element is either a string or an
object with `rules` + `value`. Rules here include **`features`** as well as `os` — supply a
feature map with `is_demo_user`, `has_custom_resolution`, `has_quick_plays_support`,
`is_quick_play_singleplayer`, `is_quick_play_multiplayer`, `is_quick_play_realms` all
defaulting to `False`, and honour it. Silently dropping feature rules will inject
`--quickPlayPath ${quickPlayPath}` into the command line and break launch.

Substitute the **complete** variable set:

```
${auth_player_name}   ${version_name}        ${game_directory}
${assets_root}        ${game_assets}         ${assets_index_name}
${auth_uuid}          ${auth_access_token}   ${auth_xuid}
${clientid}           ${user_type}           ${version_type}
${classpath}          ${classpath_separator} ${natives_directory}
${library_directory}  ${launcher_name}       ${launcher_version}
${resolution_width}   ${resolution_height}
```

- `${user_type}` is `msa`. Not `mojang`, not `legacy`.
- `${auth_xuid}` is the `xid` from XSTS DisplayClaims (§4.2 step 3).
- `${clientid}` is a stable per-install random UUID stored in `config.json`.
- `${classpath_separator}` is `;` on Windows, `:` elsewhere.
- After substitution, **assert no `${` remains** in the final argv. If any does, raise
  rather than launching — an unresolved placeholder is a guaranteed confusing crash later.

Memory: `-Xmx` and `-Xms` come from `config.json`, exposed as a slider in the UI. Default
`-Xmx6G -Xms6G` (equal min/max avoids heap resize stutter). Cap the slider at
`min(system_ram_gb - 4, 12)`. Add a note in the UI that more RAM is not faster for a
Minecraft client and large heaps increase GC pause time — 4–8 GB is correct for Sodium plus
a normal modlist.

---

## 8. PROCESS SUPERVISION

"Non-blocking" and "detached" are not the same thing, and detaching is the wrong choice
here — you lose crash detection entirely.

- Spawn with `subprocess.Popen`, `cwd` set to the instance directory, `shell=False`,
  argv as a list. On Windows add `creationflags=subprocess.CREATE_NO_WINDOW`. On POSIX use
  `start_new_session=True`.
- Pipe `stdout`/`stderr` through a single reader thread that (a) appends to
  `instances/{name}/logs/latest.log` and (b) posts `LogLine` messages to the UI queue.
- A supervisor thread `wait()`s and posts the exit code. On non-zero exit, the UI shows a
  crash panel with the last 200 log lines and a "copy log" button. Scan the tail for
  common causes and surface a plain-English hint: `UnsupportedClassVersionError` (wrong
  Java), `OutOfMemoryError`, `Mixin apply failed` (mod conflict), missing Fabric API.
- The launcher window stays usable throughout and does not exit when the game is running;
  the Play button becomes "Running — Stop".

---

## 9. MODRINTH INTEGRATION

`User-Agent: MaestroLauncher/1.0 (+https://github.com/<placeholder>/maestrolauncher)` on
every request. Respect the 300 req/min limit — read `X-Ratelimit-Remaining` and back off.

- Search: `GET /v2/search?query=&limit=20&offset=&facets=[["project_type:mod"],["categories:fabric"],["versions:{mc_version}"]]`
  (URL-encode the facets JSON). Resource packs use `[["project_type:resourcepack"],["versions:{mc_version}"]]`
  with no loader facet. Implement pagination via `offset`/`total_hits`.
- Version resolution: `GET /v2/project/{slug}/version?loaders=["fabric"]&game_versions=["{mc_version}"]`
  → newest entry → the file with `primary == true`. Verify the downloaded bytes against
  `files[].hashes.sha512`.
- **Recursive dependency resolution.** Each version has a `dependencies` array; entries
  with `dependency_type == "required"` must be resolved (by `project_id` or `version_id`)
  and installed too, transitively, with a visited-set to stop cycles. Show the user the
  full list of what will be installed before downloading. A one-click installer that
  ignores required dependencies produces crash-on-launch and is worse than no installer.

### Bundled-by-default mods
On instance creation, install **Fabric API** (`fabric-api`) and **Sodium** (`sodium`) via
the same resolution path used for user installs — do not special-case them, and do not
assume Sodium's dependency set; resolve it from the API like anything else. Current Sodium
for 26.2 is the `0.9.x` line and includes an experimental Vulkan backend selectable under
Video Settings → Graphics API.

If Sodium has no build for the selected MC version, do not fail the instance — create it
vanilla-Fabric and show a clear banner: "Sodium isn't available for {version} yet."

### Management
List installed mods by **reading `fabric.mod.json` from inside each jar** (name, version,
description, icon) rather than showing filenames. Toggle = rename `.jar` ↔ `.jar.disabled`.
Delete with confirmation. Show an "update available" badge by re-querying the version
endpoint. Never let the user delete or disable Fabric API without an explicit warning.

---

## 10. DIRECTORY LAYOUT

Windows `%APPDATA%/MaestroLauncher/`, Linux `~/.local/share/maestrolauncher/`,
macOS `~/Library/Application Support/MaestroLauncher/`.

```
MaestroLauncher/
├── config.json
├── accounts.json          # tokens, 0600
├── runtimes/java-{major}/
├── libraries/
├── assets/{indexes,objects}/
├── versions/{id}/         # client.jar, {id}.json, fabric-merged.json
└── instances/{name}/
    ├── mods/  resourcepacks/  shaderpacks/  saves/  logs/  natives/
    └── options.txt
```

Instances are plural in the layout, so make them plural in the code: create, rename, and
delete instances from the UI. Do not hardcode `default` anywhere outside the first-run
bootstrap.

---

## 11. ERROR HANDLING

- Exception hierarchy rooted at `LauncherError`, with `user_message` (shown in a dialog)
  separate from the technical string (logged).
- **Every** `requests` call passes `timeout=(10, 60)`. A missing timeout hangs forever and
  is the single most common bug in code like this.
- One retry helper with exponential backoff + jitter, retrying on 5xx, 429, and connection
  errors; never on 4xx.
- All file writes atomic: write `.part`, `fsync`, `os.replace`.
- Rotating file log at `MaestroLauncher/launcher.log`, tokens redacted.
- The app must start cleanly with a corrupt/absent `config.json` — validate and rewrite it
  with defaults rather than crashing.

---

## 12. UI — STRUCTURE

Three screens, sidebar navigation (not `CTkTabview` — tabs read as a settings dialog, a
sidebar reads as an app):
1. **Account** — device-code screen showing the code in a large monospace label with a
   copy button and a clickable link, plus a live "waiting for sign-in…" state and a cancel
   button that actually stops the polling thread.
2. **Play** — version dropdown, instance dropdown, RAM slider, a determinate progress bar
   with a per-file label, and Play/Stop. First launch downloads ~400 MB; the progress must
   be honest about totals, not a spinner.
3. **Mods** — search box (debounced 300 ms), results with async-loaded icons, one-click
   Install, and an "Installed" pane with toggle/delete/update. A separate view for resource
   packs.

Icons are fetched by workers as raw bytes; `CTkImage` objects are constructed **only** on
the UI thread from those bytes. Cache decoded icons in an LRU keyed by project ID so
scrolling the results list doesn't refetch.

---

## 13. UI — VISUAL DESIGN

Treat this as a design brief, not a styling afterthought. Before writing any UI code,
produce a short design plan (tokens + one ASCII wireframe per screen), check it against the
anti-defaults below, revise anything that reads generic, and only then build. State what you
changed and why.

### Know the medium's limits
CustomTkinter is not the web. It has **no CSS, no box-shadow, no gradients, no transitions,
no flexbox, and no easy arbitrary font loading.** Do not design as if it does, and do not
generate code that pretends otherwise. What you actually have: flat fills, per-widget
`corner_radius`, `border_width`/`border_color`, hover colours, `CTkFont`, grid/pack layout,
and `after()`-driven state changes. Design within that. A restrained interface that uses
these five things consistently beats an ambitious one that fights the toolkit.

Fonts: request families through `CTkFont` with an ordered fallback list and verify each
against `tkinter.font.families()` at startup, falling back gracefully. Do not assume a font
is installed. Do not bundle font files unless you also implement `tkextrafont` loading.

### Token system — define these as module constants, use nothing else
Emit a single `theme.py` with named constants. No raw hex anywhere else in the codebase, and
no magic padding numbers inline.

- **Colour:** 5–6 named values. One surface, one raised surface, one border, two text
  weights (primary/muted), and exactly **one** accent. The accent appears on the primary
  action and nowhere else.
- **Spacing:** a single scale in multiples of 4 (4, 8, 12, 16, 24, 32). Every `padx`/`pady`
  in the app comes from it.
- **Type:** three sizes only — body, small/muted, and one display size for the screen
  heading. Two weights. Monospace is reserved for the device code and log output, where it
  carries meaning.
- **Radius:** two values maximum — one for containers, one for controls. Not one radius on
  everything regardless of hierarchy.

### Ground the palette in the subject
This is a Minecraft launcher whose entire pitch is *performance* — Sodium, framerate,
Vulkan. Let the palette come from that rather than from a generic dark-mode template. Make a
deliberate, defensible choice and say why in a comment at the top of `theme.py`. Do not
default to the near-black-plus-single-acid-accent look, which is the most common generated
result for any dark desktop app; if you land there, it should be because you argued for it,
not because it was the first thing to hand.

### Anti-defaults — avoid these; they are the tells
- Tracked-out ALL-CAPS labels above every section.
- The same corner radius and the same border on every element regardless of importance.
- Emoji used as icons.
- Metadata strings joined with middle dots (`A · B · C`).
- A `→` glued onto button text.
- An accent colour sprayed across every interactive element until it means nothing.
- Chopping every screen into identical rounded cards.

### Restraint
Spend the boldness in one place. On this app that place is the **mod browser** — it is the
feature that justifies the launcher existing, so let it carry the visual weight and keep the
Play and Account screens quiet and functional around it. Then cut one thing you like.

### Quality floor
Full keyboard navigation with a visible focus indicator on every control. Text contrast at
4.5:1 or better against its own background — check the muted text colour specifically, since
grey-on-dark-grey is where this fails. Clickable targets no smaller than 32×32 px. Every
action that takes longer than ~200 ms shows determinate progress, never a bare spinner. No
window resize below a stated minimum that breaks layout; set `minsize()`.

### Interface copy
Words are part of the design. Active voice, sentence case, no filler.
- Buttons name what happens: "Install Sodium", not "Submit". The verb stays the same through
  the whole flow — a button that says "Install" produces a state that says "Installed".
- Errors explain what broke **and the next action**, in the interface's voice. "Couldn't
  reach Modrinth. Check your connection and try again." Not "An error occurred."
  Not an apology.
- Empty states are invitations, not blank panels: the empty mod list says what to do next.
- Name things the way a player would: "Mods", "Texture Packs", "Memory" — not "Artifacts",
  "Resource Pack Directory", "Heap Allocation".

---

## 14. ALSO SHIP

- `requirements.txt` with pinned versions.
- `README.md`: setup, how to register the Azure app for Path A, and known limitations.
- The whole thing must run from `python main.py` on a clean machine with no Java installed
  and no environment variables set.
