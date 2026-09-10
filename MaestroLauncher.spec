# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for MaestroLauncher.

    pyinstaller MaestroLauncher.spec

Produces a single launcher/MaestroLauncher.exe. ``launcher/`` is gitignored, so
the 38 MB binary has one place to live and no way to reach a commit. It used to
build to dist/ and be copied to the repo root afterwards, which left the exe
sitting next to the source and relying on a bare ``*.exe`` ignore rule.

Two packages need their data files carried in by hand, because neither is found
by following imports alone:

* tkinterdnd2 loads its tkdnd Tcl package at runtime from
  ``os.path.dirname(__file__)/tkdnd/<platform>``, and on Tcl 9 from the
  ``-tcl9`` variant of that folder. Those are .tcl scripts and a .dll that
  nothing imports, so PyInstaller does not see them. They are copied to
  ``tkinterdnd2/tkdnd`` inside the bundle, which is exactly where that
  dirname(__file__) lookup lands once the archive is unpacked. Miss this and
  the app still starts, but ``TkinterDnD._require`` fails and the drop zone
  turns itself off.
* customtkinter reads its themes and assets from disk at import time.
"""

from pathlib import Path

import tkinterdnd2
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files

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

TKDND_SOURCE = Path(tkinterdnd2.__file__).parent / "tkdnd"

datas = [(str(TKDND_SOURCE), "tkinterdnd2/tkdnd")]
datas += collect_data_files("customtkinter")

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
)
