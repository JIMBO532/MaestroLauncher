# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for MaestroLauncher.

    pyinstaller MaestroLauncher.spec

Produces a single launcher/MaestroLauncher.exe. ``launcher/`` is gitignored, so
the binary has one place to live and no way to reach a commit. It used to build
to dist/ and be copied to the repo root afterwards, which left the exe sitting
next to the source and relying on a bare ``*.exe`` ignore rule.

What has to be carried in by hand, because following imports does not find it:

* **gui_web/web/** -- the whole frontend. index.html, app.js, styles.css and
  assets/ (the background screenshot and the logo) are read off disk at
  runtime and imported by nothing, so PyInstaller has no way to see them.
  Miss this and the exe starts, finds no index.html, and raises the
  FileNotFoundError create_window() throws on purpose rather than opening an
  empty window. The destination path matters as much as the source: app.py's
  _web_root() looks for ``<sys._MEIPASS>/gui_web/web``, so that is exactly
  where this has to land.

The icon is built from the launcher's own logo by installer/make_icon.py and
is referenced here rather than embedded, so the exe, the Start Menu shortcut
and the installer all show the same mark.

pywebview's own data files (its injected api.js/finish.js and the backend
hiddenimports) are NOT listed here: pywebview ships a PyInstaller hook of its
own at webview/__pyinstaller/hook-webview.py, which PyInstaller discovers
through the package's pyinstaller40 entry point and applies automatically.

The CustomTkinter app in gui/ is no longer the entry point and is deliberately
not packaged, so customtkinter's themes and tkinterdnd2's tkdnd Tcl package --
both of which used to need hand-carrying here for exactly the same reason
gui_web/web does -- are gone from this spec. gui/ still runs from source with
``python -m gui.app``.
"""

from pathlib import Path

from PyInstaller.config import CONF

# Build into launcher/ instead of dist/.
#
# This has to go through CONF. EXE() reads CONF["distpath"] when it is
# constructed, and it strips any directory off name= with os.path.basename, so
# neither reassigning the DISTPATH global nor putting a path in the name works
# -- DISTPATH is only a copy PyInstaller hands the spec, and writing to it
# changes nothing. Set before EXE() below, which is what reads it.
OUTPUT_DIR = Path(SPECPATH) / "launcher"  # noqa: F821 -- SPECPATH is injected
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CONF["distpath"] = str(OUTPUT_DIR)

WEB_SOURCE = Path(SPECPATH) / "gui_web" / "web"  # noqa: F821
ICON = Path(SPECPATH) / "installer" / "MaestroLauncher.ico"  # noqa: F821

# Fail the build rather than produce an exe that cannot find its own frontend.
# A missing data file is silent at build time and fatal at run time, which is
# the worst order for it to be discovered in.
if not (WEB_SOURCE / "index.html").is_file():
    raise SystemExit(f"Frontend missing at build time: {WEB_SOURCE / 'index.html'}")

datas = [(str(WEB_SOURCE), "gui_web/web")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MaestroLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)
