"""Write launcher/MaestroLauncherSetup.exe.sha256 in sha256sum format.

Uploaded to every release next to the installer. The launcher's Update
button refuses to run an installer that doesn't match it, and won't offer
one-click install at all for a release without it.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "launcher" / "MaestroLauncherSetup.exe"


def main() -> int:
    if not INSTALLER.is_file():
        print(f"{INSTALLER} does not exist", file=sys.stderr)
        return 1
    digest = hashlib.sha256()
    with INSTALLER.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    target = INSTALLER.with_name(INSTALLER.name + ".sha256")
    target.write_text(f"{digest.hexdigest()}  {INSTALLER.name}\n", encoding="ascii", newline="\n")
    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
