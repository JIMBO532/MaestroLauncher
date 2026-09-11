"""GUI worker acceptance test.

Covers the one piece of machinery every long job in the launcher depends on:
``gui.app.BackgroundWorker``, and the app wiring that turns a failed job back
into an unlocked window and a message the user can read.

This exists because two bugs lived in that worker through five slices:

* ``on_error`` never fired. The callback was posted as ``lambda: on_error(exc)``,
  closing over the name bound by ``except ... as exc``; Python deletes that name
  when the block ends, so the lambda raised ``NameError`` on the UI thread and
  the real error was never delivered.
* That ``NameError`` then escaped the drain loop, which returned without
  rescheduling itself. The callback pump stopped for good, so after any failed
  job the window stayed locked with no way back short of a restart.

Neither showed up for five slices because every check until then exercised a job
that succeeded. So the failure paths are what this file is mostly about.

The window is withdrawn immediately and never shown, so running this does not
steal focus or interrupt anything else on the desktop. No clicks are synthesised.

    python scripts/test_gui.py

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk  # noqa: E402

from core import auth  # noqa: E402
from core.auth import AuthError  # noqa: E402
from core import installer  # noqa: E402
from core.installer import InstallError, Progress  # noqa: E402
from core.mods import ModError  # noqa: E402
from gui.app import SIGNED_OUT, BackgroundWorker, MaestroApp  # noqa: E402

# The install the other scripts use, so a login saved by test_login.py is found.
TARGET = Path(__file__).resolve().parent.parent / "test_mc"

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}{'  -- ' + detail if detail else ''}")


def pump(widget, until, timeout: float = 15.0) -> bool:
    """Drive the UI until ``until()`` is true. Returns whether it became true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        widget.update()
        if until():
            return True
        time.sleep(0.005)
    widget.update()
    return until()


def hidden_root() -> ctk.CTk:
    """A realised but never-visible Tk root, so nothing takes focus."""
    root = ctk.CTk()
    root.withdraw()
    root.update()
    return root


def test_worker() -> None:
    """BackgroundWorker on its own: no network, no app, just delivery."""
    print("Worker delivery\n")
    root = hidden_root()
    worker = BackgroundWorker(root)

    # -- a job that succeeds --
    got: list = []
    worker.submit(lambda: "the result", on_success=got.append, on_error=got.append)
    check("a successful job delivers its result", pump(root, lambda: bool(got)) and got == ["the result"], repr(got))

    # -- a job that raises --
    # The regression guard for "except ... as exc": the handler must receive the
    # exception object itself, not a NameError, and not nothing at all.
    raised = ModError("modrinth is unreachable")
    errors: list = []
    successes: list = []

    def explode():
        raise raised

    worker.submit(explode, on_success=successes.append, on_error=errors.append)
    delivered = pump(root, lambda: bool(errors))
    check("a raising job calls on_error at all", delivered, "nothing was delivered")
    check("on_success is not called for a raising job", not successes, repr(successes))
    if errors:
        check("the handler receives the exception object itself", errors[0] is raised, repr(errors[0]))
        check("its type survives the trip", isinstance(errors[0], ModError), type(errors[0]).__name__)
        check("its message survives the trip", str(errors[0]) == "modrinth is unreachable", str(errors[0]))

    # -- the worker keeps working after a failure --
    after: list = []
    worker.submit(lambda: "still alive", on_success=after.append)
    check("a later job is still delivered after a failure", pump(root, lambda: bool(after)), "the pump died")

    # -- a callback that itself raises must not kill the pump --
    # The regression guard for the drain returning without rescheduling.
    def bad_callback(_value):
        raise RuntimeError("callback blew up")

    worker.submit(lambda: "x", on_success=bad_callback)
    pump(root, lambda: False, timeout=0.6)          # let it run and throw

    revived: list = []
    worker.submit(lambda: "after the bad callback", on_success=revived.append)
    check(
        "a throwing callback does not stop later deliveries",
        pump(root, lambda: bool(revived)),
        "the pump died on a throwing callback",
    )

    # -- progress ticks arrive, and are coalesced --
    seen: list[Progress] = []
    bridge = worker.progress_bridge(seen.append)

    def reports_progress():
        for index in range(200):
            bridge(Progress("working", index + 1, 200))
        return "done"

    finished: list = []
    worker.submit(reports_progress, on_success=finished.append)
    check("a job reporting progress finishes", pump(root, lambda: bool(finished)), "never finished")
    check("progress ticks are delivered", bool(seen), "no ticks arrived")
    check("ticks are coalesced, not one redraw per tick", len(seen) < 200, f"{len(seen)} of 200 delivered")
    check("the last tick is the final one", bool(seen) and seen[-1].current == 200, repr(seen[-1] if seen else None))

    # -- a job that raises *during* progress reporting --
    partial: list[Progress] = []
    partial_bridge = worker.progress_bridge(partial.append)
    mid_errors: list = []

    def fails_midway():
        partial_bridge(Progress("downloading", 1, 10))
        partial_bridge(Progress("downloading", 2, 10))
        raise InstallError("connection dropped halfway")

    worker.submit(fails_midway, on_error=mid_errors.append)
    check(
        "a job that raises mid-progress still reports the error",
        pump(root, lambda: bool(mid_errors)),
        "no error after a mid-progress failure",
    )
    if mid_errors:
        check("that error is the one raised", isinstance(mid_errors[0], InstallError), type(mid_errors[0]).__name__)

    # -- a progress callback that raises must not kill the pump either --
    def bad_progress(_progress):
        raise RuntimeError("progress handler blew up")

    angry_bridge = worker.progress_bridge(bad_progress)
    worker.submit(lambda: angry_bridge(Progress("boom", 1, 1)) or "ok")
    pump(root, lambda: False, timeout=0.6)

    survived: list = []
    worker.submit(lambda: "survived", on_success=survived.append)
    check(
        "a throwing progress handler does not stop later deliveries",
        pump(root, lambda: bool(survived)),
        "the pump died on a throwing progress handler",
    )

    # -- stop() ends delivery --
    worker.stop()
    ignored: list = []
    worker.submit(lambda: "after stop", on_success=ignored.append)
    pump(root, lambda: False, timeout=0.5)
    check("stop() halts delivery", not ignored, repr(ignored))

    root.destroy()


def test_app_recovers() -> None:
    """The app itself: a failed job must unlock the window and say what happened."""
    print("\nThe window after a failed job\n")

    app = MaestroApp()
    app.withdraw()          # never shown, so nothing takes focus
    app.update()

    # Let the startup version fetch settle so it cannot overwrite what we assert.
    pump(
        app,
        lambda: bool(app.versions) or "Could not load" in app.status_label.cget("text"),
        timeout=30,
    )
    if not app.versions:
        # Offline: give the rest of the test the state it needs.
        app.versions = ["1.21.1"]
        app.version_menu.configure(values=app.versions)
        app.version_menu.set("1.21.1")
        app._set_busy(False)

    locked_states = []

    for label, handler, error in (
        ("a launch", app._play_failed, InstallError("disk full")),
        ("a sign in", app._login_failed, AuthError("Microsoft refused the login")),
        ("a Fabric install", app._fabric_failed, InstallError("fabric installer exited 1")),
        ("the optimization pack", app._optimization_failed, ModError("modrinth returned 503")),
        ("a mod install", app._mod_install_failed, ModError("no version for 1.21.1")),
        ("a search", app._search_failed, ModError("modrinth returned 503")),
        ("a file import", app._import_failed_batch, OSError("permission denied")),
    ):
        app._set_busy(True)
        app.progress.set(0.5)
        locked_states.append(app.play_button.cget("state"))

        def failing_job(exc=error):
            raise exc

        app.worker.submit(failing_job, on_error=handler)
        delivered = pump(app, lambda: not app.busy, timeout=15)

        status = app.status_label.cget("text")
        check(f"{label} that fails unlocks the window", delivered and not app.busy, f"busy={app.busy}")
        check(f"{label} re-enables Play", app.play_button.cget("state") == "normal",
              app.play_button.cget("state"))
        check(f"{label} empties the progress bar", app.progress.get() == 0.0, str(app.progress.get()))
        check(f"{label} puts the reason in the status line",
              str(error).split(":")[0][:18] in status or "failed" in status.lower(), status)

    check("the window was genuinely locked while each job ran",
          all(state == "disabled" for state in locked_states), repr(locked_states))

    # After five failures in a row the app is still usable.
    final: list = []
    app.worker.submit(lambda: "fine", on_success=final.append)
    check("the app still works after five consecutive failures",
          pump(app, lambda: bool(final)), "the worker stopped delivering")

    app.worker.stop()
    app.destroy()


def test_version_is_single_sourced() -> None:
    """The version must live in exactly one place and be read everywhere else.

    This lives here because this is the only test that imports both ``core`` and
    ``gui``, so it is the only one that can see every consumer at once.
    """
    print("\nVersion consistency\n")

    import inspect

    import core
    from core import launch, mods
    from gui import app as gui_app

    version = core.__version__
    print(f"  core.__version__          : {version}")

    launcher_version = inspect.signature(launch.build_command).parameters[
        "launcher_version"
    ].default
    consumers = {
        "gui.app.APP_VERSION": gui_app.APP_VERSION,
        "launch.build_command(launcher_version=)": launcher_version,
    }
    for name, value in consumers.items():
        print(f"  {name:<41}: {value}")
        check(f"{name} matches core.__version__", value == version, f"{value!r}")

    print(f"  mods.USER_AGENT{'':<27}: {mods.USER_AGENT}")
    check(
        "the Modrinth User-Agent carries core.__version__",
        f"/{version} " in mods.USER_AGENT,
        mods.USER_AGENT,
    )

    # The check that actually bites: someone re-typing the number somewhere
    # instead of importing it. Only the current version string is searched for,
    # so Minecraft versions in the test scripts are not false positives.
    root = Path(__file__).resolve().parent.parent
    source = sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and "test_mc" not in path.parts
    )
    home = root / "core" / "__init__.py"
    strays = [
        path.relative_to(root).as_posix()
        for path in source
        if path != home and f'"{version}"' in path.read_text(encoding="utf-8")
    ]
    print(f"  scanned {len(source)} source files for a hardcoded {version!r}")
    check(
        "the version is not hardcoded anywhere but core/__init__.py",
        not strays,
        f"also found in: {', '.join(strays)}",
    )

    # And the number actually reaches the screen. The About labels are built
    # inline rather than kept on the app, so read them off the tab itself.
    about = MaestroApp()
    about.withdraw()
    about.update()
    try:
        # CustomTkinter widgets do not list "text" in keys(), so ask each one.
        texts = []
        for child in about.tabs.tab("About").winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except Exception:  # noqa: BLE001 -- not every child carries text
                continue
    finally:
        about.worker.stop()
        about.destroy()

    shown = [t for t in texts if "Version" in t]
    print(f"  About screen shows       : {shown}")
    check(
        "the About screen renders the single-sourced version",
        any(version in t for t in shown),
        f"About labels: {texts}",
    )


def test_real_flow(version: str) -> None:
    """Drive the real window: restore a login, press Play, watch the game start.

    This is M6's actual acceptance -- "the whole flow works with zero terminal
    use" -- so it goes through the widgets and their handlers rather than calling
    core directly. It needs a signed-in account saved in test_mc/ and a working
    graphics stack, which is why it is behind --real.
    """
    print("\nThe real flow, through the window\n")

    app = MaestroApp()
    app.withdraw()          # driven programmatically; never shown
    app.update()

    try:
        # Point the app at the test install rather than %APPDATA%/.minecraft.
        app.directory_var.set(str(TARGET))

        # 1. The account panel restores a saved login without a browser.
        app.restore_account()
        restored = pump(app, lambda: app.account is not None, timeout=60)
        check("the saved login is restored on startup", restored,
              app.account_label.cget("text"))
        if not restored:
            print("\n  No saved login in test_mc/. Run scripts/test_login.py first.")
            app.destroy()
            return

        check("the account panel shows the username",
              app.account.username in app.account_label.cget("text"),
              app.account_label.cget("text"))
        check("Sign out is offered once signed in",
              app.signout_button.cget("state") == "normal",
              app.signout_button.cget("state"))

        # 2. Pick the version the way a person would.
        pump(app, lambda: bool(app.versions), timeout=30)
        if version not in app.versions:
            app.versions.append(version)
            app.version_menu.configure(values=app.versions)
        app.version_menu.set(version)
        app._set_busy(False)

        # 3. Press Play. Installing is part of it when the files are missing.
        app.start_play()
        check("pressing Play locks the window", app.busy, f"busy={app.busy}")

        started = pump(app, lambda: not app.busy, timeout=600)
        status = app.status_label.cget("text")
        check("Play finishes and unlocks the window", started, f"busy={app.busy}")
        check("a game process was started", app.game is not None, status)
        check("the status line says it is running",
              "running" in status.lower(), status)

        if app.game is not None:
            check("the game is still alive", app.game.is_running(), status)
            check("the access token is not in the status line",
                  app.account.access_token not in status)
            app.game.terminate()

        # 4. Signing out clears the panel without touching the running game.
        #
        # This really does delete the saved token, and that token is what lets
        # every other run here skip the browser, so it is put back afterwards.
        # Testing sign-out must not cost the person their login.
        token_file = auth.account_path(TARGET)
        saved_bytes = token_file.read_bytes() if token_file.exists() else None

        app.sign_out()
        check("signing out empties the account panel",
              app.account is None and app.account_label.cget("text") == SIGNED_OUT,
              app.account_label.cget("text"))
        check("Sign in is offered again after signing out",
              app.signin_button.cget("state") == "normal",
              app.signin_button.cget("state"))

        if saved_bytes is not None:
            token_file.write_bytes(saved_bytes)
            check("the saved login is put back after the sign-out check",
                  auth.load_account(TARGET) is not None)
    finally:
        app.destroy()


def test_installed_versions_are_selectable() -> None:
    """Anything installed must be launchable, including modded profiles.

    This is a regression guard. The version menu used to be filled from Mojang's
    release list alone, so a Fabric profile was only selectable in the session
    that installed it. After a restart the only thing left to pick was vanilla,
    Play launched vanilla, no mods loaded, and the game looked exactly as though
    the mods had never been installed.
    """
    print("\nInstalled versions are selectable\n")

    app = MaestroApp()
    app.withdraw()
    app.update()

    try:
        app.directory_var.set(str(TARGET))
        app.load_versions()
        pump(
            app,
            lambda: bool(app.versions) or "Could not load" in app.status_label.cget("text"),
            timeout=60,
        )

        installed = installer.installed_versions(TARGET)
        check("the test install has something in it", bool(installed), str(installed))
        if not installed:
            return

        missing = [v for v in installed if v not in app.versions]
        check("every installed version is in the menu", not missing, f"missing {missing}")

        profiles = [v for v in installed if v.startswith("fabric-loader-")]
        if profiles:
            check(
                "a Fabric profile is selectable without installing it again",
                all(p in app.versions for p in profiles),
                f"{profiles} vs menu",
            )
            # Mojang's release list will never contain it, which is the whole point.
            check(
                "that profile is not one of Mojang's releases",
                all(p not in installer.list_releases() for p in profiles),
            )

        check(
            "the menu defaults to something installed",
            app.version_menu.get() in installed,
            app.version_menu.get(),
        )

        # base_game_version is what tells the pack which Minecraft to ask for.
        for profile in profiles:
            base = installer.base_game_version(profile, TARGET)
            check(
                f"{profile} resolves to a plain Minecraft version",
                base != profile and not base.startswith("fabric-loader-"),
                base,
            )
    finally:
        app.worker.stop()
        app.destroy()


def main() -> int:
    print("MaestroLauncher GUI worker test")
    print("  the window is withdrawn; nothing is shown, focused or clicked\n")

    argv = [a for a in sys.argv[1:] if a != "--real"]
    version = argv[0] if argv else "1.21.1"

    try:
        test_worker()
        test_app_recovers()
        test_version_is_single_sourced()
        test_installed_versions_are_selectable()
        if "--real" in sys.argv:
            test_real_flow(version)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: the test itself blew up: {type(exc).__name__}: {exc}")
        raise

    print(f"\n  {_passed} passed, {_failed} failed")
    if _failed:
        print("\nFAILED")
        return 1
    print("\nGUI worker test PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
