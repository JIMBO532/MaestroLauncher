"""MaestroLauncher's CustomTkinter shell.

M6 slices 1 to 4: a Play tab that installs a version or adds Fabric with Sodium,
and a Mods tab that searches Modrinth and installs what you pick into the game
folder's mods/. Every job runs through the same worker with live progress and
the inputs locked. Launching and login are still not connected.

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

from core import installer, mods
from core.installer import InstallError, Progress
from core.mods import ModError, SearchResult

WINDOW_TITLE = "MaestroLauncher"
WINDOW_SIZE = "660x620"
POLL_INTERVAL_MS = 50

# CustomTkinter keeps a disabled button's fill colour, so state alone leaves a
# button looking clickable while it does nothing. Every button here is greyed
# through set_button_enabled() instead.
DISABLED_FILL = ("gray72", "gray30")

READY_HINT = "Pick a version, then install it, add Fabric, or browse mods."

# The launcher is Fabric-only for now, so every mod search and download is
# filtered to it. Resource packs would need this dropped; see core.mods.
MOD_LOADER = "fabric"

# Enough to fill the list without a scrollbar marathon.
SEARCH_LIMIT = 10


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
        self.results: list[SearchResult] = []
        self._result_rows: list[ctk.CTkRadioButton] = []

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

        self.tabs = ctk.CTkTabview(self, anchor="w")
        self.tabs.grid(row=2, column=0, padx=24, pady=0, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        play_tab = self.tabs.add("Play")
        mods_tab = self.tabs.add("Mods")

        # -- Play tab --
        play_tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(play_tab, text="Version").grid(
            row=0, column=0, padx=(4, 12), pady=(12, 8), sticky="w"
        )
        self.version_menu = ctk.CTkOptionMenu(
            play_tab, values=["Loading..."], state="disabled", width=220
        )
        self.version_menu.grid(row=0, column=1, padx=(0, 4), pady=(12, 8), sticky="w")

        ctk.CTkLabel(play_tab, text="Game folder").grid(
            row=1, column=0, padx=(4, 12), pady=8, sticky="w"
        )
        directory_row = ctk.CTkFrame(play_tab, fg_color="transparent")
        directory_row.grid(row=1, column=1, padx=(0, 4), pady=8, sticky="ew")
        directory_row.grid_columnconfigure(0, weight=1)

        self.directory_var = ctk.StringVar(value=str(installer.default_directory()))
        self.directory_entry = ctk.CTkEntry(directory_row, textvariable=self.directory_var)
        self.directory_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ctk.CTkButton(
            directory_row, text="Browse", width=80, command=self.choose_directory
        )
        self.browse_button.grid(row=0, column=1, padx=(8, 0))

        self.play_button = ctk.CTkButton(
            play_tab, text="Play", height=42, command=self.start_install
        )
        self.play_button.grid(row=2, column=0, columnspan=2, padx=4, pady=(22, 6), sticky="ew")

        self.fabric_button = ctk.CTkButton(
            play_tab, text="Install Fabric + Sodium", height=36, command=self.start_fabric
        )
        self.fabric_button.grid(row=3, column=0, columnspan=2, padx=4, pady=(0, 12), sticky="ew")

        # -- Mods tab --
        mods_tab.grid_columnconfigure(0, weight=1)
        mods_tab.grid_rowconfigure(1, weight=1)

        search_row = ctk.CTkFrame(mods_tab, fg_color="transparent")
        search_row.grid(row=0, column=0, padx=4, pady=(12, 8), sticky="ew")
        search_row.grid_columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_row, textvariable=self.search_var,
            placeholder_text="Search Modrinth for a mod...",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.start_search())
        self.search_button = ctk.CTkButton(
            search_row, text="Search", width=90, command=self.start_search
        )
        self.search_button.grid(row=0, column=1, padx=(8, 0))

        self.results_frame = ctk.CTkScrollableFrame(mods_tab, fg_color=("gray92", "gray14"))
        self.results_frame.grid(row=1, column=0, padx=4, pady=0, sticky="nsew")
        self.results_frame.grid_columnconfigure(0, weight=1)

        self.selected_mod = ctk.StringVar(value="")
        self.results_hint = ctk.CTkLabel(
            self.results_frame,
            text="Results appear here. Searches are filtered to the selected\n"
                 "version and Fabric.",
            justify="left", anchor="w", text_color=("gray45", "gray60"),
        )
        self.results_hint.grid(row=0, column=0, padx=8, pady=8, sticky="ew")

        self.install_mod_button = ctk.CTkButton(
            mods_tab, text="Install selected mod", height=36,
            command=self.start_mod_install,
        )
        self.install_mod_button.grid(row=2, column=0, padx=4, pady=(10, 12), sticky="ew")

        # -- shared footer: one progress bar and one status line for every job --
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=24, pady=(10, 18), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(footer)
        self.progress.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            footer, text="Starting up...", anchor="w", justify="left",
            text_color=("gray35", "gray70"), wraplength=560,
        )
        self.status_label.grid(row=1, column=0, sticky="ew")

        # Each button's own fill, so greying one out can be undone with the colour
        # it actually had rather than a single shared guess.
        self._button_fills = {
            button: button.cget("fg_color")
            for button in (
                self.browse_button, self.play_button, self.fabric_button,
                self.search_button, self.install_mod_button,
            )
        }
        self._set_busy(False)

        # Long statuses -- an install path, a Fabric profile id, a jar name -- used
        # to run off the window edge. Wrap them to whatever width we currently have.
        footer.bind("<Configure>", self._fit_status_width)

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

        self.version_menu.configure(values=versions)
        self.version_menu.set(versions[0])
        self._set_busy(False)
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

    def _fit_status_width(self, event: tkinter.Event) -> None:
        self.status_label.configure(wraplength=max(event.width - 40, 200))

    def set_button_enabled(self, button: ctk.CTkButton, enabled: bool) -> None:
        """Enable or disable a button, and make it *look* the way it behaves."""
        button.configure(
            state="normal" if enabled else "disabled",
            fg_color=self._button_fills[button] if enabled else DISABLED_FILL,
            hover=enabled,
        )

    def _set_busy(self, busy: bool) -> None:
        """Lock the inputs while a long job runs, so nothing changes under it."""
        self.busy = busy
        ready = not busy and bool(self.versions)
        self.version_menu.configure(state="normal" if ready else "disabled")
        self.directory_entry.configure(state="disabled" if busy else "normal")
        self.search_entry.configure(state="disabled" if busy else "normal")
        self.set_button_enabled(self.browse_button, not busy)
        self.set_button_enabled(self.play_button, ready)
        self.set_button_enabled(self.fabric_button, ready)
        self.set_button_enabled(self.search_button, ready)
        self.set_button_enabled(
            self.install_mod_button, ready and bool(self.selected_mod.get())
        )
        for row in self._result_rows:
            row.configure(state="disabled" if busy else "normal")

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

    def start_fabric(self) -> None:
        """Install Fabric plus Sodium for the selected version, off the UI thread."""
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
        self.set_status(f"Installing Fabric and Sodium for {version}...")

        report = self.worker.progress_bridge(self.show_progress)
        self.worker.submit(
            lambda: installer.install_fabric_with_sodium(
                version, directory, on_progress=report
            ),
            on_success=self._fabric_finished,
            on_error=self._fabric_failed,
        )

    def _fabric_finished(self, profile_id: str) -> None:
        self.progress.set(1.0)
        self._set_busy(False)
        self.set_status(f"Ready: {profile_id}, with Sodium in mods/.")

    def _fabric_failed(self, error: BaseException) -> None:
        self.progress.set(0)
        self._set_busy(False)
        detail = str(error) if isinstance(error, InstallError) else f"{error}"
        self.set_status(f"Fabric install failed: {detail}")

    def _selected_version(self) -> Optional[str]:
        version = self.version_menu.get()
        if version not in self.versions:
            self.set_status("Pick a version on the Play tab first.")
            return None
        return version

    def start_search(self) -> None:
        """Search Modrinth for the typed term, off the UI thread."""
        if self.busy:
            return

        query = self.search_var.get().strip()
        if not query:
            self.set_status("Type something to search for.")
            return
        version = self._selected_version()
        if version is None:
            return

        self._set_busy(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.set_status(f'Searching Modrinth for "{query}" ({version}, {MOD_LOADER})...')

        self.worker.submit(
            lambda: mods.search_projects(
                query, game_version=version, loader=MOD_LOADER, limit=SEARCH_LIMIT
            ),
            on_success=self._search_finished,
            on_error=self._search_failed,
        )

    def _clear_results(self) -> None:
        for row in self._result_rows:
            row.destroy()
        self._result_rows.clear()
        self.results = []
        self.selected_mod.set("")

    def _search_finished(self, results: list[SearchResult]) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)

        self._clear_results()
        self.results = results

        if not results:
            self.results_hint.configure(text="Nothing matched that search.")
            self.results_hint.grid()
            self._set_busy(False)
            self.set_status("No mods matched. Try another term or another version.")
            return

        self.results_hint.grid_remove()
        for index, hit in enumerate(results):
            label = f"{hit.title}  --  {hit.author}  --  {hit.downloads:,} downloads"
            row = ctk.CTkRadioButton(
                self.results_frame, text=label, value=hit.slug,
                variable=self.selected_mod, command=self._mod_selected,
            )
            row.grid(row=index, column=0, padx=8, pady=6, sticky="w")
            self._result_rows.append(row)

        self._set_busy(False)
        self.set_status(f"{len(results)} mods found. Pick one and install it.")

    def _search_failed(self, error: BaseException) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self._set_busy(False)
        detail = str(error) if isinstance(error, ModError) else f"{error}"
        self.set_status(f"Search failed: {detail}")

    def _mod_selected(self) -> None:
        self.set_button_enabled(self.install_mod_button, not self.busy)

    def start_mod_install(self) -> None:
        """Download the selected mod into the game folder's mods/, off the UI thread."""
        if self.busy:
            return

        slug = self.selected_mod.get()
        hit = next((r for r in self.results if r.slug == slug), None)
        if hit is None:
            self.set_status("Pick a mod from the results first.")
            return
        version = self._selected_version()
        if version is None:
            return
        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder on the Play tab first.")
            return

        self._set_busy(True)
        self.progress.set(0)
        self.set_status(f"Installing {hit.title} for {version}...")

        report = self.worker.progress_bridge(self.show_progress)
        self.worker.submit(
            lambda: mods.install_project(
                slug, version, directory, loader=MOD_LOADER,
                project_type=hit.project_type, on_progress=report,
            ),
            on_success=lambda path: self._mod_install_finished(hit, path),
            on_error=self._mod_install_failed,
        )

    def _mod_install_finished(self, hit: SearchResult, path: Path) -> None:
        self.progress.set(1.0)
        self._set_busy(False)
        self.set_status(f"{hit.title} installed: {path.name} in {path.parent.name}/.")

    def _mod_install_failed(self, error: BaseException) -> None:
        self.progress.set(0)
        self._set_busy(False)
        detail = str(error) if isinstance(error, ModError) else f"{error}"
        self.set_status(f"Mod install failed: {detail}")

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
