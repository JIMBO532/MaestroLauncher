"""MaestroLauncher's engine package.

The launcher's version lives here and nowhere else. Everything that shows it or
sends it -- the About screen, the launcher_version handed to the game, the
Modrinth User-Agent -- imports it from here, and scripts/test_gui.py fails if a
copy of the number turns up hardcoded anywhere else.
"""

__version__ = "0.1.0"
