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

from core.installer import InstallError, Progress  # noqa: E402
from core.mods import ModError  # noqa: E402
from gui.app import BackgroundWorker, MaestroApp  # noqa: E402

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
        ("an install", app._install_failed, InstallError("disk full")),
        ("a Fabric install", app._fabric_failed, InstallError("fabric installer exited 1")),
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


def main() -> int:
    print("MaestroLauncher GUI worker test")
    print("  the window is withdrawn; nothing is shown, focused or clicked\n")

    try:
        test_worker()
        test_app_recovers()
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
