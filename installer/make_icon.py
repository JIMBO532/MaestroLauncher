"""Build the Windows icon from the launcher's own logo.

    python installer/make_icon.py

The source logo is white linework on transparency, which is what the home
screen wants and exactly the wrong thing for an icon: on a light Explorer
background or a light Start Menu tile it would be white on white. So the mark
is composited onto the app's own dark background instead, which is legible
everywhere and is the same colour the window itself paints.

Kept as a script, and its output committed, so the icon can be regenerated
when the logo changes without the build depending on it being run.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gui_web" / "web" / "assets" / "logo.png"
TARGET = ROOT / "installer" / "MaestroLauncher.ico"

# Matches --bg in styles.css and the window's own background_color.
BACKGROUND = (10, 10, 10, 255)

# Drawn at this size and downsampled for every entry, so the small ones come
# from a clean resize rather than from re-rasterising fine linework badly.
MASTER = 512

# The mark is wide; leaving room on all four sides stops it touching the edge
# at 16px, where any overhang just turns into mush.
PADDING = 0.14

# What Windows actually asks for, smallest to largest: Explorer lists, the
# taskbar, Alt-Tab, and the 256px one the Start Menu and the shell's extra
# large view use.
SIZES = [16, 24, 32, 48, 64, 128, 256]


def build() -> Path:
    logo = Image.open(SOURCE).convert("RGBA")

    canvas = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    # A rounded square reads as an app icon rather than as a photo crop, and
    # it is what every other icon beside it in the Start Menu looks like.
    radius = int(MASTER * 0.18)
    ImageDraw.Draw(canvas).rounded_rectangle(
        [0, 0, MASTER - 1, MASTER - 1], radius=radius, fill=BACKGROUND
    )

    room = int(MASTER * (1 - PADDING * 2))
    scaled = logo.copy()
    scaled.thumbnail((room, room), Image.Resampling.LANCZOS)
    canvas.alpha_composite(
        scaled, ((MASTER - scaled.width) // 2, (MASTER - scaled.height) // 2)
    )

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(TARGET, format="ICO", sizes=[(size, size) for size in SIZES])
    return TARGET


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")
