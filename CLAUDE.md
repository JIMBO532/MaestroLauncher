# MaestroLauncher v1

A custom Minecraft: Java Edition launcher. Sodium works out of the box, and mods
and texture packs can be searched and installed from inside the launcher.

## Stack

- Python 3.11+
- `minecraft-launcher-lib` 8.0 — game install, Fabric install, launch command
- `requests` — Modrinth API
- `customtkinter` — GUI (milestone 5, not before)

## Layout

```
core/        engine. no GUI imports allowed in here, ever.
  installer.py   vanilla + Fabric install
  auth.py        Microsoft login (milestone 2)
  mods.py        Modrinth search/download (milestone 4)
  launch.py      command construction + process spawn
scripts/     throwaway manual test scripts, one per milestone
gui/         customtkinter app (milestone 5)
```

## Hard rules

- **Do not hand-roll the launch protocol.** No manual version-manifest parsing,
  asset downloading, natives extraction, or JVM argument building. That is what
  `minecraft-launcher-lib` is for. If you think you need to bypass it, stop and ask.
- **Do not create new `.md` files.** Not summaries, not notes, not design docs.
  Update `PLAN.md` checkboxes when a milestone lands; that is all.
- **One milestone per session.** Do not start the next one.
- **Run your own test script** before reporting back. "It should work" is not done.
- `core/` must stay importable and testable without a GUI and without a login.
- Type-hint public functions. Wrap library exceptions in our own error types so the
  GUI never sees a `minecraft_launcher_lib` traceback.

## Environment

- Target OS: Windows 11
- Game dir default: `%APPDATA%/.minecraft`, but every function takes an explicit
  directory argument — never hardcode.
- Fabric install shells out to a Java jar, so a JRE must be on PATH.
