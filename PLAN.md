# MaestroLauncher — Milestones

Work top to bottom. Each milestone must be runnable and verified before the next
one starts. Do not skip ahead to the GUI.

---

## M0 — Azure app registration (do this first, it blocks M2)

Not a coding task. Runs in parallel with M1.

- [ ] Create an Azure app registration, "Personal Microsoft accounts only"
- [ ] Redirect URI: `http://localhost:8000/callback` (type: Web)
- [ ] Submit the Minecraft API permission request form
- [ ] Store the client ID in `.env` (gitignored), never commit it

Without approval, `api.minecraftservices.com` returns 403 and login cannot work.
Approval is not instant. Submit it before writing any auth code.

---

## M1 — Install pipeline  ← start here

**Done when:** `python scripts/test_install.py` downloads 1.21.1 into `./test_mc/`
with a live progress readout and exits 0.

- [ ] `core/installer.py`: list versions, check if installed, install vanilla
- [ ] Progress reported through a callback, not printed from inside core
- [ ] Library errors wrapped in `InstallError`
- [ ] `scripts/test_install.py` passes

No auth required. Fully testable today.

---

## M2 — Microsoft login

**Done when:** `python scripts/test_login.py` opens a browser, completes login,
and prints the account username and UUID.

- [ ] `core/auth.py` using `minecraft_launcher_lib.microsoft_account`
- [ ] Local HTTP server on port 8000 to catch the redirect
- [ ] Refresh token persisted to disk so login survives a restart
- [ ] `AzureAppNotPermitted` surfaced as a clear message, not a traceback

## M3 — First real launch

**Done when:** vanilla 1.21.1 launches to the main menu, logged in.

- [ ] `core/launch.py` builds the command and spawns the process
- [ ] Configurable RAM allocation
- [ ] Game stdout/stderr captured to a log file

## M4 — Fabric + Sodium

**Done when:** one function call produces a Fabric profile with Sodium installed
and it launches.

- [ ] `install_fabric_loader()` in `core/installer.py` (stub already written)
- [ ] Sodium jar pulled from the Modrinth API, matched to the game version
- [ ] Dropped into `<dir>/mods/`

## M5 — Mod browser

**Done when:** search a term, get results, install one, and it appears in `mods/`.

- [x] `core/mods.py` — Modrinth search, version resolution, download
- [x] Filter by game version and loader
- [x] Resource packs go to `resourcepacks/`, not `mods/`

## M6 — GUI

**Done when:** the whole flow above works with zero terminal use.

- [ ] CustomTkinter shell: account, version picker, play button, progress bar
- [ ] All long work off the UI thread
- [ ] Mod browser tab

## M7 — Ship

- [ ] PyInstaller one-file build
- [ ] "Not an official Minecraft product" notice in the README and About screen
