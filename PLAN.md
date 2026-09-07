# MaestroLauncher — Milestones

Work top to bottom. Each milestone must be runnable and verified before the next
one starts. Do not skip ahead to the GUI.

---

## M0 — Azure app registration (do this first, it blocks M2)

Not a coding task. Runs in parallel with M1.

- [x] Create an Azure app registration, "Personal Microsoft accounts only"
- [x] Redirect URI: `http://localhost:8000/callback` (type: Web)
- [x] Submit the Minecraft API permission request form
- [ ] Store the client ID in `.env` (gitignored), never commit it

Without approval, `api.minecraftservices.com` returns 403 and login cannot work.
Approval is not instant. Submit it before writing any auth code.

---

## M1 — Install pipeline  ← start here

**Done when:** `python scripts/test_install.py` downloads 1.21.1 into `./test_mc/`
with a live progress readout and exits 0.

- [x] `core/installer.py`: list versions, check if installed, install vanilla
- [x] Progress reported through a callback, not printed from inside core
- [x] Library errors wrapped in `InstallError`
- [x] `scripts/test_install.py` passes

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
- [x] All long work off the UI thread
- [x] Mod browser tab
- [x] Slice 5: import local files -- drop a jar or pack zip in and it lands in the
      right folder (`core/imports.py` + an "Add files" button)

## M7 — Ship

- [x] PyInstaller one-file build
- [x] "Not an official Minecraft product" notice in the README and About screen

---

## M8 — Web frontend

Replace the CustomTkinter GUI with an HTML/CSS/JS frontend hosted by pywebview
in a native window. `gui/` keeps working until M8 is finished; `core/` does not
change at all. No frontend framework and no build step -- plain files.

Window opens at 1280x760, resizable, minimum 1024x640.

**Design brief** (reference: the Helios Launcher)

Full-bleed dark background. No panels, boxes or borders -- content floats
directly on the background. One large primary action; secondary items are small
icons at the edges.

- Background: pure black `#0a0a0a`, no photo.
- The wireframe logo is black-on-white at source; it is inverted to
  white-on-transparent and used as the hero image, top-left, large. It is the
  main visual on the screen.
- Type: white, thin weights, generous letter-spacing on small labels. All-caps
  for small labels, as in the reference.
- Royal blue `#2B4FD6` is the primary action colour -- PLAY and install buttons
  only.
- Minecraft grass green `#5CB85C` is for state only: progress bars, installed
  ticks, online indicators. Never for buttons.
- Everything else is white or grey on black.
- Buttons: generous corner radius, subtle lift and brightening on hover, quick
  scale-down on press. Rounded and tactile without being cartoonish -- it has to
  sit alongside the sharp cinematic layout without fighting it.

Measured contrast, so the palette is not re-litigated later: white on royal blue
6.58:1, white on black 19.8:1, green on black 7.98:1, grey `#8A8A8A` on black
5.73:1. Royal blue on black is 3.01:1, which is fine for a fill or a focus ring
but not for text -- blue is never a text colour.

Home screen: logo top-left, account placeholder top-right, large PLAY button
bottom-centre with the version selector as small text beside it, and a vertical
icon rail on the right edge for Content, Settings and About. Nothing else.

- [x] Slice 1: static shell in `gui_web/`, nothing wired to `core/`
- [ ] Slice 2: version list and install wired through to `core/`
- [ ] Slice 3: content browsing and local file import
- [ ] Slice 4: account and launching
- [ ] Retire `gui/` once the web frontend covers everything it did
