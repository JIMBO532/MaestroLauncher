"""MaestroLauncher's CustomTkinter shell.

M6 slices 1 and 2: the window, and Play wired to a real install. The version
dropdown is filled from ``core.installer``, and pressing Play downloads the
selected version into the chosen folder with live progress. Launching, mods and
login are still not connected.

Every long operation this launcher will do -- downloading a version, installing
Fabric, fetching mods, logging in -- takes seconds to minutes, and Tk gives us
exactly one thread to draw on, so anything slow running on it freezes the window.
:class:`BackgroundWorker` is how that is avoided: the version fetch and the
install both go through it, and launching will too.

Imports point one way only: ``gui`` may import ``core``, never the reverse.
"""

from __future__ import annotations

import queue
import threading
import tkinter
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable, Optional

import customtkinter as ctk

from core import installer
from core.installer import InstallError, Progress

WINDOW_TITLE = "MaestroLauncher"
WINDOW_SIZE = "620x460"
POLL_INTERVAL_MS = 50

# CustomTkinter keeps a disabled button's fill colour, so a disabled Play still
# looks clickable unless the fill is changed too.
PLAY_DISABLED_FILL = ("gray72", "gray30")

READY_HINT = "Pick a version and press Play to install it. Launching comes later."


class BackgroundWorker:
    """Runs work off the UI thread and delivers the results back onto it.

    Tk is not thread safe: a widget may only be touched from the thread that
    created it. Worker threads here never touch a widget. They put a callable on
    a queue, and the UI thread drains that queue from a repeating ``after()``,
    so every callback the caller supplies runs on the UI thread where it is safe
    to update labels and progress bars.
    """

    def __init__(self, widget: tkinter.Misc, poll_interval_ms: int = POLL_INTERVAL_MS) -> None:
        self._widget = widget
        self._poll_interval_ms = poll_interval_ms
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._stopped = False
        self._widget.after(self._poll_interval_ms, self._drain)

    def submit(
        self,
        work: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> threading.Thread:
        """Run ``work`` on a worker thread; call back on the UI thread."""

        def run() -> None:
            try:
                result = work()
            except BaseException as exc:  # noqa: BLE001 -- handed to on_error
                if on_error is not None:
                    self._post(lambda: on_error(exc))
            else:
                if on_success is not None:
                    self._post(lambda: on_success(result))

        thread = threading.Thread(target=run, name="maestro-worker", daemon=True)
        thread.start()
        return thread

    def progress_bridge(
        self, on_progress: Callable[[Progress], None]
    ) -> Callable[[Progress], None]:
        """Wrap a progress callback so a worker thread can call it safely.

        Hand the result to any ``core`` function that takes ``on_progress``; the
        ticks arrive on the UI thread.

        Ticks are coalesced: an install fires thousands of them and the screen
        can only show the latest, so at most one update is queued at a time and
        newer ticks overwrite the pending one. Without this the queue fills with
        tens of thousands of closures the UI would redraw for no benefit.
        """
        lock = threading.Lock()
        latest: list[Optional[Progress]] = [None]
        queued = [False]

        def deliver() -> None:
            with lock:
                progress = latest[0]
                latest[0] = None
                queued[0] = False
            if progress is not None:
                on_progress(progress)

        def bridge(progress: Progress) -> None:
            with lock:
                latest[0] = progress
                if queued[0]:
                    return
                queued[0] = True
            self._post(deliver)

        return bridge

    def stop(self) -> None:
        """Stop draining. Called when the window is closing."""
        self._stopped = True

    def _post(self, callback: Callable[[], None]) -> None:
        self._queue.put(callback)

    def _drain(self) -> None:
        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except tkinter.TclError:
                # The window went away between posting and draining.
                return
        if not self._stopped:
            self._widget.after(self._poll_interval_ms, self._drain)


class MaestroApp(ctk.CTk):
    """The launcher window."""

    def __init__(self) -> None:
        super().__init__()

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(520, 420)
        self.grid_columnconfigure(0, weight=1)

        self.worker = BackgroundWorker(self)
        self.versions: list[str] = []
        self.busy = False

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.load_versions()

    # -- layout ---------------------------------------------------------------

    def _build_widgets(self) -> None:
        header = ctk.CTkLabel(
            self, text=WINDOW_TITLE, font=ctk.CTkFont(size=22, weight="bold")
        )
        header.grid(row=0, column=0, padx=24, pady=(24, 0), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="Not an official Minecraft product.",
            text_color=("gray45", "gray60"),
        )
        subtitle.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        body = ctk.CTkFrame(self)
        body.grid(row=2, column=0, padx=24, pady=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(body, text="Version").grid(
            row=0, column=0, padx=(18, 12), pady=(20, 8), sticky="w"
        )
        self.version_menu = ctk.CTkOptionMenu(
            body, values=["Loading..."], state="disabled", width=220
        )
        self.version_menu.grid(row=0, column=1, padx=(0, 18), pady=(20, 8), sticky="w")

        ctk.CTkLabel(body, text="Game folder").grid(
            row=1, column=0, padx=(18, 12), pady=8, sticky="w"
        )
        directory_row = ctk.CTkFrame(body, fg_color="transparent")
        directory_row.grid(row=1, column=1, padx=(0, 18), pady=8, sticky="ew")
        directory_row.grid_columnconfigure(0, weight=1)

        self.directory_var = ctk.StringVar(value=str(installer.default_directory()))
        self.directory_entry = ctk.CTkEntry(directory_row, textvariable=self.directory_var)
        self.directory_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ctk.CTkButton(
            directory_row, text="Browse", width=80, command=self.choose_directory
        )
        self.browse_button.grid(row=0, column=1, padx=(8, 0))

        self.play_button = ctk.CTkButton(
            body, text="Play", height=42, command=self.start_install
        )
        # Remember the theme's own fill so the button can be greyed and restored.
        self._play_fill = self.play_button.cget("fg_color")
        self.set_play_enabled(False)
        self.play_button.grid(row=2, column=0, columnspan=2, padx=18, pady=(22, 8), sticky="ew")

        self.progress = ctk.CTkProgressBar(body)
        self.progress.grid(row=3, column=0, columnspan=2, padx=18, pady=(8, 8), sticky="ew")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            body, text="Starting up...", anchor="w", text_color=("gray35", "gray70")
        )
        self.status_label.grid(row=4, column=0, columnspan=2, padx=18, pady=(0, 18), sticky="ew")

    # -- actions --------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def show_progress(self, progress: Progress) -> None:
        """Render one progress tick. Wire real work to this through the worker."""
        self.progress.set(progress.fraction)
        self.set_status(f"{progress.status} ({progress.percent}%)")

    def load_versions(self) -> None:
        """Fetch the release list from Mojang without blocking the window."""
        self.set_status("Fetching the version list from Mojang...")
        self.progress.configure(mode="indeterminate")
        self.progress.start()

        self.worker.submit(
            installer.list_releases,
            on_success=self._versions_loaded,
            on_error=self._versions_failed,
        )

    def _versions_loaded(self, versions: list[str]) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)

        self.versions = versions
        if not versions:
            self.set_status("Mojang returned no versions.")
            return

        self.version_menu.configure(values=versions, state="normal")
        self.version_menu.set(versions[0])
        self.set_play_enabled(True)
        self.set_status(f"{len(versions)} releases available. {READY_HINT}")

    def _versions_failed(self, error: BaseException) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        message = str(error) if isinstance(error, InstallError) else f"{error}"
        self.set_status(f"Could not load versions: {message}")

    def choose_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose the game folder", initialdir=self.directory_var.get()
        )
        if chosen:
            self.directory_var.set(str(Path(chosen)))

    def set_play_enabled(self, enabled: bool) -> None:
        """Enable or disable Play, and make it *look* the way it behaves."""
        self.play_button.configure(
            state="normal" if enabled else "disabled",
            fg_color=self._play_fill if enabled else PLAY_DISABLED_FILL,
            hover=enabled,
        )

    def _set_busy(self, busy: bool) -> None:
        """Lock the inputs while a long job runs, so nothing changes under it."""
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.version_menu.configure(state=state if self.versions else "disabled")
        self.directory_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.set_play_enabled(not busy and bool(self.versions))

    def start_install(self) -> None:
        """Install the selected version, off the UI thread, with live progress."""
        if self.busy:
            return

        version = self.version_menu.get()
        directory = self.directory_var.get().strip()

        if version not in self.versions:
            self.set_status("Pick a version first.")
            return
        if not directory:
            self.set_status("Choose a game folder first.")
            return

        self._set_busy(True)
        self.progress.set(0)
        self.set_status(f"Installing Minecraft {version}...")

        # The one call this whole pattern was built for.
        report = self.worker.progress_bridge(self.show_progress)
        self.worker.submit(
            lambda: installer.install_version(version, directory, on_progress=report),
            on_success=lambda path: self._install_finished(version, path),
            on_error=self._install_failed,
        )

    def _install_finished(self, version: str, path: Path) -> None:
        self.progress.set(1.0)
        self._set_busy(False)
        self.set_status(f"Minecraft {version} is installed in {path}. Launching comes later.")

    def _install_failed(self, error: BaseException) -> None:
        self.progress.set(0)
        self._set_busy(False)
        detail = str(error) if isinstance(error, InstallError) else f"{error}"
        self.set_status(f"Install failed: {detail}")

    def _on_close(self) -> None:
        self.worker.stop()
        self.destroy()


def main() -> int:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = MaestroApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
