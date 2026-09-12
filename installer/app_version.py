"""Print the launcher's version. Used by build.bat to stamp the installer.

The version lives in core/__init__.py and nowhere else -- that is the whole
point of it living there -- so the build reads it rather than writing it down
a second time in MaestroLauncher.iss.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "core" / "__init__.py"

match = re.search(r'__version__\s*=\s*"([^"]+)"', SOURCE.read_text(encoding="utf-8"))
if match is None:
    sys.exit(f"No __version__ found in {SOURCE}")

print(match.group(1))
