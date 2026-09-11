"""MaestroLauncher's CustomTkinter shell.

All of M6 plus the M7 About screen: an account panel that signs in with Microsoft,
a Play tab that installs a version -- or adds Fabric with Sodium -- and launches
it, a Mods tab that searches Modrinth, installs what you pick, and imports files
you already have on disk, and an About tab carrying the name, version and
trademark notice. Every job runs through the same worker with live progress and
the inputs locked, so the whole flow works without touching a terminal.

Every long operation this launcher does -- downloading a version, installing
Fabric, fetching mods, logging in -- takes seconds to minutes, and Tk gives us
exactly one thread to draw on, so anything slow running on it freezes the window.
:class:`BackgroundWorker` is how that is avoided: the version fetch, the install,
the login and the launch all go through it.

Imports point one way only: ``gui`` may import ``core``, never the reverse.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, Optional, Sequence

import customtkinter as ctk

try:  # drag and drop is a nice-to-have; the Add files button works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001 -- a missing or broken tkdnd must not stop the app
    DND_FILES = None
    TkinterDnD = None

from core import __version__, auth, imports, installer, launch, mods, worlds
from core.auth import Account, AuthError, LoginCancelled
from core.installer import InstallError, Progress
from core.mods import ModError, SearchResult

WINDOW_TITLE = "MaestroLauncher"

# The version lives in core/__init__.py and is read from there, so the About
# screen, the game and Modrinth can never be told three different numbers.
APP_VERSION = __version__

# The notice M7 asks for, kept as one string so the About screen and anything
# else that needs it cannot drift apart.
DISCLAIMER = (
    "Not an official Minecraft product. Not approved by or associated with "
    "Mojang or Microsoft."
)
WINDOW_SIZE = "660x620"
POLL_INTERVAL_MS = 50

# CustomTkinter keeps a disabled button's fill colour, so state alone leaves a
# button looking clickable while it does nothing. Every button here is greyed
# through set_button_enabled() instead.
DISABLED_FILL = ("gray72", "gray30")

RESULT_DWELL_MS = 6000

# Where the Azure client ID lives when it is not in the environment. Beside the
# project when running from source, and beside the exe once PyInstaller has
# bundled it -- freezing moves __file__ into the unpacked bundle under a temp
# directory, so the executable's own folder is what counts there.
#
# The folder above the exe is checked too, because the build drops the exe in
# launcher/ while the .env it needs sits in the project root one level up. A
# shipped copy still finds a .env sitting next to it; this only adds the
# development layout, and it stops one directory up rather than walking.
def _env_file_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent.parent
    beside_exe = Path(sys.executable).resolve().parent
    return [here / ".env", beside_exe / ".env", beside_exe.parent / ".env"]


SIGNED_OUT = "Not signed in"

# The launcher is Fabric-only for now, so mod searches and downloads are
# filtered to it. core.mods drops the filter by itself for the types that
# have no loader -- Modrinth files resource packs under "minecraft" -- so it
# is safe to pass for every type.
MOD_LOADER = "fabric"

# What the Content tab can browse, in the order the picker shows them.
# The values are Modrinth project types; core.mods routes each to its own
# folder, so nothing here needs to know about mods/ or resourcepacks/.
CONTENT_TYPES: dict[str, str] = {
    "Mods": "mod",
    "Resource packs": "resourcepack",
    "Shaders": "shader",
}

# Enough to fill the list without a scrollbar marathon.
SEARCH_LIMIT = 10

# tkinterdnd2 needs its wrapper mixed into the root window, so the base classes
# have to be decided before the class body. When it is missing we are a plain
# CTk and the drop zone simply is not built.
_ROOT_BASES = (ctk.CTk,) if TkinterDnD is None else (ctk.CTk, TkinterDnD.DnDWrapper)


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
                    # Bound as a default argument, not captured as a free
                    # variable: Python deletes the name bound by "except ... as"
                    # when the block ends, so a plain closure over it raises
                    # NameError by the time the UI thread runs it.
                    self._post(lambda error=exc: on_error(error))
            else:
                if on_success is not None:
                    self._post(lambda value=result: on_success(value))

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

    def status_bridge(self, on_status: Callable[[str], None]) -> Callable[[str], None]:
        """Wrap a plain status callback so a worker thread can call it safely.

        ``core.auth`` reports its progress as sentences rather than as
        :class:`Progress` values, and it fires few enough of them that there is
        nothing to coalesce -- each one is a distinct step worth showing.
        """

        def bridge(text: str) -> None:
            self._post(lambda message=text: on_status(message))

        return bridge

    def stop(self) -> None:
        """Stop draining. Called when the window is closing."""
        self._stopped = True

    def _post(self, callback: Callable[[], None]) -> None:
        self._queue.put(callback)

    def _drain(self) -> None:
        # A drain may already be scheduled when stop() is called, and the window
        # is usually being destroyed by then, so drop the queue rather than
        # running callbacks against widgets on their way out.
        if self._stopped:
            return

        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:  # noqa: BLE001
                # A callback that throws must not stop the pump. Returning here
                # used to end the drain for good, so every later job sat with
                # busy set and the inputs locked, with no way back.
                traceback.print_exc()

        if self._stopped:
            return
        try:
            self._widget.after(self._poll_interval_ms, self._drain)
        except tkinter.TclError:
            # The window is gone; there is nothing left to deliver to.
            self._stopped = True


def _split_braced(data: str) -> list[str]:
    """Split a tkdnd payload on whitespace, honouring {braced paths}.

    Deliberately does no backslash processing, so Windows paths survive intact.
    """
    items: list[str] = []
    index = 0
    while index < len(data):
        char = data[index]
        if char.isspace():
            index += 1
        elif char == "{":
            end = data.find("}", index)
            if end == -1:
                items.append(data[index + 1:])
                break
            items.append(data[index + 1:end])
            index = end + 1
        else:
            end = index
            while end < len(data) and not data[end].isspace():
                end += 1
            items.append(data[index:end])
            index = end
    return [item for item in items if item]


class VersionPrompt(ctk.CTkToplevel):
    """A small modal "which Minecraft version?" picker.

    Returns the chosen version from :meth:`ask`, or None if the person closed or
    cancelled it. Kept as its own window rather than a third dropdown on the Play
    tab because the version being optimized is a different decision from the
    version being played, and putting both on screen at once invites picking the
    wrong one.
    """

    def __init__(self, parent: tkinter.Misc, versions: Sequence[str]) -> None:
        super().__init__(parent)
        self.choice: Optional[str] = None

        self.title("Install optimizations")
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Which Minecraft version?",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                "Fabric and the optimization mods are installed for this version,\n"
                "and a profile is added to the version list to launch them with."
            ),
            justify="left", anchor="w", text_color=("gray45", "gray60"),
        ).grid(row=1, column=0, padx=24, pady=(0, 14), sticky="w")

        self.version_var = ctk.StringVar(value=versions[0] if versions else "")
        ctk.CTkOptionMenu(
            self, values=list(versions), variable=self.version_var, width=260
        ).grid(row=2, column=0, padx=24, pady=(0, 18), sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, padx=24, pady=(0, 20), sticky="e")
        ctk.CTkButton(
            buttons, text="Cancel", width=100, command=self._cancel,
            fg_color=("gray70", "gray30"),
        ).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkButton(buttons, text="Install", width=120, command=self._accept).grid(
            row=0, column=1
        )

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())

    def _accept(self) -> None:
        self.choice = self.version_var.get() or None
        self.destroy()

    def _cancel(self) -> None:
        self.choice = None
        self.destroy()

    def ask(self) -> Optional[str]:
        """Show the dialog and block until it is answered. Returns the choice."""
        # Centre on the parent, then take the focus. Doing this before the first
        # idle pass puts the window at 1x1 in the corner.
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self.grab_set()
        self.wait_window()
        return self.choice


class MaestroApp(*_ROOT_BASES):
    """The launcher window."""

    def __init__(self) -> None:
        super().__init__()

        # tkdnd has to be loaded into this interpreter before any widget can be
        # registered as a drop target. If it will not load -- no binaries for
        # this Tk, say -- carry on without it rather than failing to start.
        self.dnd_ready = False
        if TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ready = True
            except Exception:  # noqa: BLE001
                self.dnd_ready = False

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(520, 420)
        self.grid_columnconfigure(0, weight=1)

        self.worker = BackgroundWorker(self)
        self.versions: list[str] = []
        self.busy = False
        self.results: list[SearchResult] = []
        self._result_rows: list[ctk.CTkRadioButton] = []

        # The signed-in account, and the game we most recently started. The game
        # is held so closing the launcher can leave it alone deliberately rather
        # than by accident.
        self.account: Optional[Account] = None
        self.game: Optional[launch.RunningGame] = None

        # Versions already re-checked for newly available mods, so browsing the
        # dropdown does not fire a network round trip per keystroke.
        self._skipped_checked: set[str] = set()

        # Versions already warned about upgrading a world, so the warning is
        # shown once rather than on every press of Play.
        self._world_warned: set[str] = set()
        # The pending "clear the result" callback, so a new message cancels it.
        self._status_clear: Optional[str] = None

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.load_versions()
        self.restore_account()

    # -- layout ---------------------------------------------------------------

    def _build_widgets(self) -> None:
        header = ctk.CTkLabel(
            self, text=WINDOW_TITLE, font=ctk.CTkFont(size=22, weight="bold")
        )
        header.grid(row=0, column=0, padx=24, pady=(24, 0), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text=DISCLAIMER.split(".")[0] + ".",
            text_color=("gray45", "gray60"),
        )
        subtitle.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        # -- account panel, top right --
        #
        # Signing in is the one job that cannot be hurried along: it opens a
        # browser and waits for a person. It goes through the worker like
        # everything else, so the window keeps drawing while it waits.
        account_panel = ctk.CTkFrame(self, fg_color="transparent")
        account_panel.grid(row=0, column=1, rowspan=2, padx=(0, 24), pady=(24, 18), sticky="ne")

        self.account_label = ctk.CTkLabel(
            account_panel, text=SIGNED_OUT, anchor="e",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.account_label.grid(row=0, column=0, sticky="e")

        account_buttons = ctk.CTkFrame(account_panel, fg_color="transparent")
        account_buttons.grid(row=1, column=0, pady=(6, 0), sticky="e")

        self.signin_button = ctk.CTkButton(
            account_buttons, text="Sign in", width=90, height=28,
            command=self.start_login,
        )
        self.signin_button.grid(row=0, column=0)

        self.signout_button = ctk.CTkButton(
            account_buttons, text="Sign out", width=90, height=28,
            command=self.sign_out,
        )
        self.signout_button.grid(row=0, column=1, padx=(8, 0))

        self.tabs = ctk.CTkTabview(self, anchor="w")
        self.tabs.grid(row=2, column=0, columnspan=2, padx=24, pady=0, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        play_tab = self.tabs.add("Play")
        mods_tab = self.tabs.add("Content")
        about_tab = self.tabs.add("About")

        # -- Play tab --
        play_tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(play_tab, text="Version").grid(
            row=0, column=0, padx=(4, 12), pady=(12, 8), sticky="w"
        )
        self.version_menu = ctk.CTkOptionMenu(
            play_tab, values=["Loading..."], state="disabled", width=220,
            command=self._version_changed,
        )
        self.version_menu.grid(row=0, column=1, padx=(0, 4), pady=(12, 8), sticky="w")

        # The game folder lives on the About tab. It is picked once, defaults
        # correctly for everyone on Windows, and every other control here reads
        # it rather than changing it -- so it does not earn a row on the screen
        # someone looks at every time they play.
        self.directory_var = ctk.StringVar(value=str(installer.default_directory()))

        self.play_button = ctk.CTkButton(
            play_tab, text="Play", height=42, command=self.start_play
        )
        self.play_button.grid(row=1, column=0, columnspan=2, padx=4, pady=(22, 6), sticky="ew")

        # One button, not two. Installing Fabric and installing the optimization
        # mods were always the same errand, and doing them separately is how a
        # folder full of mods ends up under a vanilla profile that ignores them.
        self.optimize_button = ctk.CTkButton(
            play_tab, text="Install optimizations", height=36,
            command=self.start_optimization_pack,
        )
        self.optimize_button.grid(row=2, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="ew")

        # -- Content tab --
        mods_tab.grid_columnconfigure(0, weight=1)
        mods_tab.grid_rowconfigure(2, weight=1)

        self.content_type = ctk.CTkSegmentedButton(
            mods_tab, values=list(CONTENT_TYPES),
            command=self._content_type_changed,
        )
        self.content_type.set("Mods")
        self.content_type.grid(row=0, column=0, padx=4, pady=(12, 4), sticky="ew")

        search_row = ctk.CTkFrame(mods_tab, fg_color="transparent")
        search_row.grid(row=1, column=0, padx=4, pady=(4, 8), sticky="ew")
        search_row.grid_columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_row, textvariable=self.search_var,
            placeholder_text="Search Modrinth...",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.start_search())
        self.search_button = ctk.CTkButton(
            search_row, text="Search", width=90, command=self.start_search
        )
        self.search_button.grid(row=0, column=1, padx=(8, 0))

        self.results_frame = ctk.CTkScrollableFrame(mods_tab, fg_color=("gray92", "gray14"))
        self.results_frame.grid(row=2, column=0, padx=4, pady=0, sticky="nsew")
        self.results_frame.grid_columnconfigure(0, weight=1)

        self.selected_mod = ctk.StringVar(value="")
        self.results_hint = ctk.CTkLabel(
            self.results_frame,
            text="Results appear here, filtered to the version picked on the\n"
                 "Play tab.",
            justify="left", anchor="w", text_color=("gray45", "gray60"),
        )
        self.results_hint.grid(row=0, column=0, padx=8, pady=8, sticky="ew")

        self.install_mod_button = ctk.CTkButton(
            mods_tab, text="Install selected", height=36,
            command=self.start_mod_install,
        )
        self.install_mod_button.grid(row=3, column=0, padx=4, pady=(10, 6), sticky="ew")

        self.add_files_button = ctk.CTkButton(
            mods_tab, text="Add files from your computer...", height=32,
            command=self.choose_files_to_import,
        )
        self.add_files_button.grid(row=4, column=0, padx=4, pady=(0, 6), sticky="ew")

        self.drop_zone = ctk.CTkLabel(
            mods_tab,
            text=(
                "...or drop jars and pack zips here"
                if self.dnd_ready
                else "Drag and drop is unavailable; use the button above."
            ),
            height=44, fg_color=("gray88", "gray20"), corner_radius=8,
            text_color=("gray40", "gray65"),
        )
        self.drop_zone.grid(row=5, column=0, padx=4, pady=(0, 12), sticky="ew")

        if self.dnd_ready:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        # -- About tab --
        about_tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            about_tab, text=WINDOW_TITLE,
            font=ctk.CTkFont(size=20, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=8, pady=(20, 2), sticky="ew")

        ctk.CTkLabel(
            about_tab, text=f"Version {APP_VERSION}", anchor="w",
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=0, padx=8, pady=(0, 18), sticky="ew")

        ctk.CTkLabel(
            about_tab, text="Game folder", anchor="w",
        ).grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

        directory_row = ctk.CTkFrame(about_tab, fg_color="transparent")
        directory_row.grid(row=3, column=0, padx=8, pady=(0, 4), sticky="ew")
        directory_row.grid_columnconfigure(0, weight=1)

        self.directory_entry = ctk.CTkEntry(directory_row, textvariable=self.directory_var)
        self.directory_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ctk.CTkButton(
            directory_row, text="Browse", width=80, command=self.choose_directory
        )
        self.browse_button.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(
            about_tab,
            text="Where versions, mods and the saved login are kept.",
            anchor="w", text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=11),
        ).grid(row=4, column=0, padx=8, pady=(0, 18), sticky="ew")

        self.about_notice = ctk.CTkLabel(
            about_tab, text=DISCLAIMER, justify="left", anchor="w",
            wraplength=520, text_color=("gray35", "gray70"),
        )
        self.about_notice.grid(row=5, column=0, padx=8, pady=(0, 18), sticky="ew")

        ctk.CTkLabel(
            about_tab,
            text=(
                "Minecraft is a trademark of Mojang Studios. Game files come from\n"
                "Mojang; mods and packs come from Modrinth."
            ),
            justify="left", anchor="w", text_color=("gray50", "gray55"),
        ).grid(row=6, column=0, padx=8, pady=(0, 18), sticky="ew")

        # Keep the notice readable when the window is resized, the same way the
        # status line does.
        about_tab.bind(
            "<Configure>",
            lambda event: self.about_notice.configure(
                wraplength=max(event.width - 40, 200)
            ),
        )

        # -- shared footer: one progress bar and one status line for every job --
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, columnspan=2, padx=24, pady=(10, 18), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(footer)
        self.progress.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            footer, text="", anchor="w", justify="left",
            text_color=("gray35", "gray70"), wraplength=560,
        )
        self.status_label.grid(row=1, column=0, sticky="ew")

        # Each button's own fill, so greying one out can be undone with the colour
        # it actually had rather than a single shared guess.
        self._button_fills = {
            button: button.cget("fg_color")
            for button in (
                self.browse_button, self.play_button,
                self.search_button, self.install_mod_button, self.add_files_button,
                self.signin_button, self.signout_button, self.optimize_button,
            )
        }
        self._set_busy(False)

        # Long statuses -- an install path, a Fabric profile id, a jar name -- used
        # to run off the window edge. Wrap them to whatever width we currently have.
        footer.bind("<Configure>", self._fit_status_width)

    # -- actions --------------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Show text and leave it there.

        For work in flight and for anything that went wrong: a problem stays on
        screen until the next action replaces it, because a message that erases
        itself is a message the person may never have read.
        """
        if self._status_clear is not None:
            self.after_cancel(self._status_clear)
            self._status_clear = None
        self.status_label.configure(text=text)

    def flash_status(self, text: str) -> None:
        """Show a result, then get out of the way.

        The status line is for work happening now. A finished job is worth a
        sentence, but leaving that sentence up turns the line into a log of the
        last thing that happened, which is what made it read as clutter at rest.
        """
        self.set_status(text)
        self._status_clear = self.after(RESULT_DWELL_MS, self._clear_status)

    def _clear_status(self) -> None:
        self._status_clear = None
        self.status_label.configure(text="")

    def clear_progress(self) -> None:
        """Put the bar back to empty.

        The bar reports work in flight, so it sits empty whenever nothing is
        running rather than staying full after the last job. What happened is
        the status line's job, and it keeps saying so.
        """
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)

    def show_progress(self, progress: Progress) -> None:
        """Render one progress tick. Wire real work to this through the worker."""
        self.progress.set(progress.fraction)
        self.set_status(f"{progress.status} ({progress.percent}%)")

    def load_versions(self) -> None:
        """List what can be launched: everything installed, plus Mojang's releases.

        Installed profiles come first and are listed even when Mojang has never
        heard of them, because a Fabric profile is not one of Mojang's releases.
        Listing only releases meant that installing Fabric and then restarting
        left nothing modded to pick, so Play launched vanilla, loaded no mods,
        and the game looked exactly as if the mods had never installed.
        """
        self.set_status("Fetching the version list from Mojang...")
        self.progress.configure(mode="indeterminate")
        self.progress.start()

        directory = self.directory_var.get().strip()

        def work() -> list[str]:
            installed = installer.installed_versions(directory) if directory else []
            try:
                releases = installer.list_releases()
            except InstallError:
                # Offline is survivable: what is already on disk still launches.
                if not installed:
                    raise
                releases = []
            return installed + [v for v in releases if v not in installed]

        self.worker.submit(
            work,
            on_success=self._versions_loaded,
            on_error=self._versions_failed,
        )

    def _versions_loaded(self, versions: list[str]) -> None:
        self.clear_progress()

        self.versions = versions
        if not versions:
            self.set_status("Mojang returned no versions.")
            return

        self.version_menu.configure(values=versions)
        # versions[0] is an installed one when anything is installed, which is a
        # better default than the newest release nobody has downloaded yet.
        self.version_menu.set(versions[0])
        self._set_busy(False)

        # Nothing to report: the version menu is the result. A shared mods
        # folder holding several versions is the exception, because that is what
        # stops a launch, and it stays up rather than clearing.
        self.set_status("")
        self.warn_about_shared_mods()

        # And offer anything the selected version had to skip last time.
        self.maybe_offer_skipped(self.version_menu.get())

    def _versions_failed(self, error: BaseException) -> None:
        self.clear_progress()
        message = str(error) if isinstance(error, InstallError) else f"{error}"
        self.set_status(f"Could not load versions: {message}")

    def choose_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose the game folder", initialdir=self.directory_var.get()
        )
        if chosen and str(Path(chosen)) != self.directory_var.get():
            self.directory_var.set(str(Path(chosen)))
            # Which versions are installed is a property of the folder, so the
            # list is stale the moment the folder changes.
            self.load_versions()

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
        self.content_type.configure(state="disabled" if busy else "normal")
        self.set_button_enabled(self.browse_button, not busy)
        self.set_button_enabled(self.play_button, ready)
        self.set_button_enabled(self.optimize_button, ready)
        self.set_button_enabled(self.search_button, ready)
        self.set_button_enabled(
            self.install_mod_button, ready and bool(self.selected_mod.get())
        )
        # Importing needs a folder, not a version, so it does not wait on the
        # Mojang fetch the way the other buttons do.
        self.set_button_enabled(self.add_files_button, not busy)

        # Signing in needs neither a version nor anything downloaded, so it is
        # available as soon as nothing else is running. Play stays enabled while
        # signed out on purpose: a button that quietly does nothing teaches
        # nothing, whereas pressing it says what is missing.
        self.set_button_enabled(self.signin_button, not busy and self.account is None)
        self.set_button_enabled(self.signout_button, not busy and self.account is not None)
        for row in self._result_rows:
            row.configure(state="disabled" if busy else "normal")

    # -- account --------------------------------------------------------------

    def _client_id(self) -> Optional[str]:
        """The Azure client ID, from the environment or a .env beside us."""
        for candidate in _env_file_candidates():
            client_id = auth.load_client_id(candidate)
            if client_id:
                return client_id
        return None

    def _render_account(self) -> None:
        """Put the account panel in step with what we are actually signed in as."""
        if self.account is not None:
            self.account_label.configure(text=self.account.username or "Signed in")
        else:
            self.account_label.configure(text=SIGNED_OUT)
        self._set_busy(self.busy)

    def restore_account(self) -> None:
        """Bring back a saved login on startup, without opening a browser.

        This deliberately calls ``refresh`` rather than ``login_or_refresh``: the
        latter falls through to an interactive login when the saved token is
        dead, and a browser opening by itself because the launcher started is not
        something anyone asked for. A token that will not renew just leaves the
        panel signed out, and the Sign in button is right there.
        """
        saved = auth.load_account(self.directory_var.get().strip() or ".")
        if saved is None or not saved.refresh_token:
            return

        client_id = self._client_id()
        if client_id is None:
            # Show who was signed in, but there is no way to renew the session.
            self.account_label.configure(text=f"{saved.username} (signed out)")
            return

        self.account_label.configure(text=f"{saved.username} (restoring...)")
        directory = self.directory_var.get().strip()

        def work() -> Account:
            account = auth.refresh(client_id, saved.refresh_token)
            auth.save_account(account, directory)
            return account

        self.worker.submit(
            work,
            on_success=self._restore_finished,
            on_error=self._restore_failed,
        )

    def _restore_finished(self, account: Account) -> None:
        self.account = account
        self._render_account()
        self.set_status("")

    def _restore_failed(self, error: BaseException) -> None:
        # A saved login that will not renew is not an error worth shouting about;
        # it is the normal end of a token's life. Say so once and move on.
        self.account = None
        self._render_account()
        self.set_status("Your saved login expired. Sign in again to play.")

    def start_login(self) -> None:
        """Sign in with Microsoft, off the UI thread, browser and all."""
        if self.busy:
            return

        client_id = self._client_id()
        if client_id is None:
            self.set_status(
                "No Azure client ID. Put MAESTRO_CLIENT_ID=<the id> in a .env "
                "file beside the launcher. See PLAN.md M0."
            )
            return

        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder first; the login is saved inside it.")
            return

        self._set_busy(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.set_status("Opening your browser to sign in with Microsoft...")

        report = self.worker.status_bridge(self.set_status)
        self.worker.submit(
            lambda: auth.login_or_refresh(client_id, directory, on_status=report),
            on_success=self._login_finished,
            on_error=self._login_failed,
        )

    def _login_finished(self, account: Account) -> None:
        self.clear_progress()
        self.account = account
        # Unlock before rendering: _render_account re-applies the current busy
        # state to every button, so leaving it set here would lock the window
        # for good on the one path where the login actually worked.
        self._set_busy(False)
        self._render_account()
        self.flash_status(f"Signed in as {account.username}.")

    def _login_failed(self, error: BaseException) -> None:
        self.clear_progress()
        self.account = None
        self._set_busy(False)
        self._render_account()
        if isinstance(error, LoginCancelled):
            self.set_status("Sign in was cancelled.")
        elif isinstance(error, AuthError):
            self.set_status(f"Sign in failed: {error}")
        else:
            self.set_status(f"Sign in failed unexpectedly: {error}")

    def sign_out(self) -> None:
        """Forget the saved login. The game keeps running if one is up."""
        if self.busy:
            return
        try:
            auth.clear_account(self.directory_var.get().strip() or ".")
        except AuthError as exc:
            self.set_status(f"Could not remove the saved login: {exc}")
            return
        self.account = None
        self._render_account()
        self.flash_status("Signed out.")

    # -- catching up on mods that were skipped --------------------------------

    def _version_changed(self, version: str) -> None:
        """Called when the version picker changes. Offers any newly available mods."""
        self.maybe_offer_skipped(version)

    def maybe_offer_skipped(self, version: str) -> None:
        """Re-check Modrinth for mods this version had to skip, and offer them.

        Once per version per session. A mod with no build for a brand-new
        Minecraft version usually gets one within weeks, and nothing would ever
        notice otherwise -- the install already happened and will not repeat
        itself. Checking on every version change instead would mean a network
        round trip each time someone browses the dropdown.
        """
        if self.busy or not version:
            return
        directory = self.directory_var.get().strip()
        if not directory or version in self._skipped_checked:
            return
        self._skipped_checked.add(version)

        instance = installer.instance_directory(version, directory)
        if not mods.load_skipped(instance):
            return

        game_version = installer.base_game_version(version, directory)

        self.worker.submit(
            lambda: (
                version,
                instance,
                game_version,
                mods.recheck_skipped(instance, game_version),
            ),
            on_success=self._skipped_rechecked,
            on_error=lambda error: None,  # a failed re-check is not worth a banner
        )

    def _skipped_rechecked(self, outcome: tuple) -> None:
        version, instance, game_version, available = outcome
        if not available or self.busy:
            return
        if self.version_menu.get() != version:
            # They moved on while the check was in flight; do not ambush them.
            return

        names = ", ".join(item.title for item in available)
        wanted = messagebox.askyesno(
            "Mods now available",
            f"{len(available)} mod(s) skipped earlier now have a build for "
            f"{game_version}:\n\n{names}\n\nInstall them now?",
            parent=self,
        )
        if not wanted:
            self.flash_status(f"Left {len(available)} newly available mod(s) uninstalled.")
            return

        self._set_busy(True)
        self.progress.set(0)
        self.set_status(f"Installing {len(available)} newly available mod(s)...")

        report = self.worker.progress_bridge(self.show_progress)
        projects = [item.project_id for item in available]
        self.worker.submit(
            lambda: mods.install_skipped(
                instance, game_version, projects, on_progress=report
            ),
            on_success=self._skipped_installed,
            on_error=self._optimization_failed,
        )

    def _skipped_installed(self, entries: list) -> None:
        self.clear_progress()
        self._set_busy(False)
        installed = [entry for entry in entries if entry.installed]
        failed = [entry for entry in entries if not entry.installed]

        parts = [f"{len(installed)} newly available mod(s) installed"]
        if failed:
            parts.append(
                "still skipped: "
                + "; ".join(f"{entry.title} ({entry.error})" for entry in failed)
            )
        show = self.set_status if failed else self.flash_status
        show(". ".join(parts) + ".")

    def warn_about_shared_mods(self) -> None:
        """Say so when the old shared mods folder holds builds for several versions.

        Not touched and not migrated -- that folder was filled by hand and is not
        ours to empty. But it is exactly what stops Fabric from starting, so
        leaving it unmentioned would be unhelpful.
        """
        directory = self.directory_var.get().strip()
        if not directory:
            return
        groups = installer.mixed_version_mods(directory)
        declared = {key: names for key, names in groups.items() if key != "unknown"}
        if len(declared) < 2:
            return

        summary = "; ".join(
            f"{key} ({len(names)})" for key, names in sorted(declared.items())
        )
        self.set_status(
            f"Heads up: {installer.shared_mods_directory(directory)} holds mods for "
            f"several Minecraft versions -- {summary}. Nothing here uses that folder "
            "any more (each version has its own), but the old launcher profiles do, "
            "and Fabric will refuse to start with mixed versions in it."
        )

    # -- playing --------------------------------------------------------------

    @staticmethod
    def _world_listing(affected: list[worlds.World]) -> str:
        """A short bulleted list of worlds, with the version each was made in."""
        shown = "\n".join(
            f"  - {world.name}"
            + (f" (made in {world.version_name})" if world.version_name else "")
            for world in affected[:8]
        )
        if len(affected) > 8:
            shown += f"\n  ... and {len(affected) - 8} more"
        return shown

    def confirm_world_state(self, version: str, directory: str) -> bool:
        """Warn once about what this version will do to the shared worlds.

        Sharing saves across versions means a launch now reaches worlds that a
        different version made, and the two directions go wrong in opposite
        ways:

        Older world, newer game -- Minecraft rewrites the world's format on load
        and never writes it back, so it will not open in the older version
        again. Permanent, usually wanted, and worth hearing about first.

        Newer world, older game -- Minecraft refuses to load it and simply omits
        it from the world list. Nothing is damaged, but a world that vanishes
        from the list looks exactly like a world that was deleted, so the worry
        it causes is the thing worth heading off. Naming the worlds and the
        reason turns a scare into a version switch.

        Neither blocks: returns False only if they actively cancel, which is the
        useful escape when the answer is "then let me pick another version".
        Once per version per session -- the first Play is the moment this helps,
        the fifth is nagging.
        """
        if version in self._world_warned:
            return True

        base = installer.base_game_version(version, directory)
        saves = installer.shared_data_directory(directory) / "saves"
        try:
            upgrading = worlds.worlds_needing_upgrade(saves, base, directory)
            hidden = worlds.worlds_too_new(saves, base, directory)
        except Exception:  # noqa: BLE001 -- a warning must never stop a launch
            return True

        self._world_warned.add(version)

        # Hidden worlds first: that is the one that gets mistaken for data loss,
        # and the one where cancelling and picking a newer version is the fix.
        if hidden:
            proceed = messagebox.askokcancel(
                "Some worlds will not appear",
                f"{len(hidden)} world(s) were made in a version newer than {base}:\n\n"
                f"{self._world_listing(hidden)}\n\n"
                "Minecraft cannot open a world that is newer than the game, so "
                "these will be missing from the world list.\n\n"
                "Nothing is deleted or damaged -- they come back as soon as you "
                "launch the newer version again. Continue?",
                parent=self,
                icon=messagebox.WARNING,
            )
            if not proceed:
                return False

        if not upgrading:
            return True

        return messagebox.askokcancel(
            "World format will be upgraded",
            f"{len(upgrading)} world(s) were made in an older version than {base}:\n\n"
            f"{self._world_listing(upgrading)}\n\n"
            "Opening one in this version upgrades its format permanently. It will "
            "not open in the older version afterwards.\n\n"
            "Worlds you do not open are untouched. Continue?",
            parent=self,
            icon=messagebox.WARNING,
        )

    def start_play(self) -> None:
        """Install the selected version if it is missing, then launch it.

        One button for the whole thing: the person who just picked a version
        wants to play it, and whether the files happen to be on disk already is
        not a decision worth making them take.
        """
        if self.busy:
            return

        version = self.version_menu.get()
        directory = self.directory_var.get().strip()

        if not directory:
            self.set_status("Choose a game folder first.")
            return
        # A Fabric profile is installed but is not one of Mojang's releases, so
        # accept anything already on disk as well as anything in the menu.
        if version not in self.versions and not installer.is_installed(version, directory):
            self.set_status("Pick a version first.")
            return
        if self.account is None or not self.account.access_token:
            self.set_status("Sign in first -- Minecraft will not start without an account.")
            return

        if not self.confirm_world_state(version, directory):
            return

        account = self.account
        self._set_busy(True)
        self.progress.set(0)

        report = self.worker.progress_bridge(self.show_progress)
        status = self.worker.status_bridge(self.set_status)

        def work() -> launch.RunningGame:
            if not installer.is_installed(version, directory):
                status(f"Installing Minecraft {version}...")
                installer.install_version(version, directory, on_progress=report)
            status(f"Starting Minecraft {version}...")

            # Every version launches in its own directory, not just generated
            # ones. Mods belong to a game version, so two versions sharing one
            # mods folder is the whole bug: switching from 26.2 to 1.21.11 used
            # to load both sets at once and Fabric refused to start. Keyed by the
            # Minecraft version, so every 26.2 profile sees the same mods and
            # 1.21.11 cannot see any of them.
            game_directory = installer.instance_directory(version, directory)
            game_directory.mkdir(parents=True, exist_ok=True)

            # Worlds, settings and packs are shared across versions; only mods
            # are not. Relinking before every launch is what keeps an instance
            # made before this existed in step with one made after.
            for note in installer.link_shared_data(game_directory, directory):
                status(note)

            return launch.launch(
                version,
                directory,
                account.username,
                account.uuid,
                account.access_token,
                game_directory=game_directory,
            )

        self.worker.submit(
            work,
            on_success=lambda game: self._play_started(version, game),
            on_error=self._play_failed,
        )

    def _play_started(self, version: str, game: launch.RunningGame) -> None:
        self.clear_progress()
        self._set_busy(False)
        self.game = game
        self.flash_status(
            f"Minecraft {version} is running (pid {game.pid}). Log: {game.log_path}"
        )

    def _play_failed(self, error: BaseException) -> None:
        self.clear_progress()
        self._set_busy(False)
        # InstallError and LaunchError already read as sentences; anything else
        # is a surprise and gets shown as-is rather than swallowed.
        self.set_status(f"Could not start the game: {error}")

    def start_optimization_pack(self) -> None:
        """Ask which Minecraft version to optimize, then build the profile.

        The version is asked for rather than taken from the Play tab's picker,
        because this makes a *new* profile rather than changing the selected
        one, and the two are rarely the same choice.
        """
        if self.busy:
            return

        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder first.")
            return
        if not self.versions:
            self.set_status("Still fetching the version list. Try again in a moment.")
            return

        choices = [v for v in self.versions if not installer.is_optimized_profile(v)]
        chosen = VersionPrompt(self, choices).ask()
        if chosen is None:
            self.flash_status("Cancelled.")
            return

        self.begin_optimization(chosen)

    def begin_optimization(self, minecraft_version: str) -> None:
        """Install Fabric, the optimization pack, and a named profile for them.

        Split from the prompt so the whole job can be driven without opening a
        dialog, which is what the tests do.
        """
        if self.busy:
            return

        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder first.")
            return

        self._set_busy(True)
        self.progress.set(0)
        self.set_status(f"Building an optimized profile for {minecraft_version}...")

        report = self.worker.progress_bridge(self.show_progress)
        status = self.worker.status_bridge(self.set_status)

        def work() -> tuple[str, Path, list, list[str]]:
            status(f"Installing Minecraft {minecraft_version} and Fabric...")
            profile_id = installer.install_optimized_profile(
                minecraft_version, directory, on_progress=report
            )

            # The mods go in this profile's own directory, not the shared one.
            # Sharing is what let a 1.21.11 build sit beside a 26.2 build until
            # Fabric refused to start.
            instance = installer.instance_directory(profile_id, directory)

            status("Installing the optimization pack from Modrinth...")
            # Sodium goes in as a candidate rather than as a fallback decided
            # here. install_collection reads what the jars declare and drops
            # whichever of a mutually exclusive pair came second, so the renderer
            # ends up as an either/or without this code guessing which won.
            entries = mods.install_collection(
                mods.OPTIMIZATION_COLLECTION,
                minecraft_version,
                instance,
                extra_projects=("sodium",),
                on_progress=report,
            )

            return (
                profile_id,
                instance,
                entries,
                mods.ranged_conflict_warnings(instance),
            )

        self.worker.submit(
            work,
            on_success=self._optimization_finished,
            on_error=self._optimization_failed,
        )

    def _optimization_finished(
        self, outcome: tuple[str, Path, list, list[str]]
    ) -> None:
        profile_id, instance, entries, conflicts = outcome
        self.clear_progress()

        # The profile is brand new, so nothing else knows it exists yet. Adding
        # and selecting it is the difference between this button finishing and
        # this button being usable.
        if profile_id not in self.versions:
            self.versions.insert(0, profile_id)
            self.version_menu.configure(values=self.versions)
        self.version_menu.set(profile_id)
        self._set_busy(False)

        installed = [entry for entry in entries if entry.installed]
        failed = [entry for entry in entries if not entry.installed]
        prerelease = [entry for entry in installed if not entry.stable]

        parts = [f"'{profile_id}' is ready -- pick it and press Play"]
        parts.append(f"{len(installed)} mods installed into {instance.name}/mods")
        if prerelease:
            parts.append(
                f"{len(prerelease)} came from a prerelease "
                f"({', '.join(entry.title for entry in prerelease)})"
            )
        if failed:
            # Naming the reason matters more than the count: "no build for this
            # version" and "conflicts with something else" are different
            # problems, and only one of them is worth changing version over.
            reasons = "; ".join(f"{entry.title} ({entry.error})" for entry in failed)
            parts.append(f"{len(failed)} skipped -- {reasons}")
        parts.extend(conflicts)

        # A clean install can go quiet. One that skipped something, or that has
        # a conflict to report, is the whole reason the pack tells you anything.
        show = self.set_status if (failed or conflicts) else self.flash_status
        show(". ".join(parts) + ".")

    def _optimization_failed(self, error: BaseException) -> None:
        self.clear_progress()
        self._set_busy(False)
        self.set_status(f"Could not build the optimized profile: {error}")

    def _selected_version(self) -> Optional[str]:
        version = self.version_menu.get()
        if version not in self.versions:
            self.set_status("Pick a version on the Play tab first.")
            return None
        return version

    def selected_content_type(self) -> str:
        """The Modrinth project type the picker is currently on."""
        return CONTENT_TYPES.get(self.content_type.get(), "mod")

    def _content_type_changed(self, _label: str) -> None:
        """Switching type invalidates the results, which were of the old type."""
        if self.busy:
            return
        self._clear_results()
        self.results_hint.configure(
            text=f"Search Modrinth for {self.content_type.get().lower()}."
        )
        self.results_hint.grid()
        self._set_busy(False)
        self.set_status("")

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
        project_type = self.selected_content_type()
        self.set_status(
            f'Searching Modrinth for "{query}" ({self.content_type.get().lower()}, '
            f"{version})..."
        )

        # loader is passed for every type; core.mods drops it for the ones
        # Modrinth files under "minecraft" rather than a mod loader.
        self.worker.submit(
            lambda: mods.search_projects(
                query, game_version=version, loader=MOD_LOADER,
                project_type=project_type, limit=SEARCH_LIMIT,
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
        self.clear_progress()

        self._clear_results()
        self.results = results

        if not results:
            self.results_hint.configure(text="Nothing matched that search.")
            self.results_hint.grid()
            self._set_busy(False)
            self.flash_status("No mods matched. Try another term or another version.")
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
        self.flash_status(
            f"{len(results)} {self.content_type.get().lower()} found. "
            "Pick one and install it."
        )

    def _search_failed(self, error: BaseException) -> None:
        self.clear_progress()
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
            self.set_status("Pick something from the results first.")
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

        # Into the version's own directory, like everything else. A mod
        # downloaded here for 26.2 must not turn up when 1.21.11 launches.
        instance = installer.instance_directory(version, directory)

        report = self.worker.progress_bridge(self.show_progress)
        self.worker.submit(
            lambda: mods.install_project(
                slug, version, instance, loader=MOD_LOADER,
                project_type=hit.project_type, on_progress=report,
            ),
            on_success=lambda path: self._mod_install_finished(hit, path),
            on_error=self._mod_install_failed,
        )

    def _mod_install_finished(self, hit: SearchResult, path: Path) -> None:
        self.clear_progress()
        self._set_busy(False)
        # path.parent.name is whichever folder core.mods routed it to.
        self.flash_status(f"{hit.title} installed: {path.name} in {path.parent.name}/.")

    def _mod_install_failed(self, error: BaseException) -> None:
        self.clear_progress()
        self._set_busy(False)
        detail = str(error) if isinstance(error, ModError) else f"{error}"
        self.set_status(f"Install failed: {detail}")

    def _parse_drop(self, data: str) -> list[str]:
        """Turn tkdnd's payload into a list of existing file paths.

        tkdnd hands over a Tcl list: paths containing spaces are brace-quoted,
        the rest are bare. Bare Windows paths are the catch -- Tcl list parsing
        treats their backslashes as escapes and quietly mangles them, so a
        dropped drive-letter path disappears. Both readings are tried and
        whichever finds more real files wins.
        """
        readings: list[list[str]] = []
        try:
            readings.append([str(item) for item in self.tk.splitlist(data)])
        except Exception:  # noqa: BLE001
            pass
        readings.append(_split_braced(data))

        best: list[str] = []
        for reading in readings:
            found = [path for path in reading if Path(path).is_file()]
            if len(found) > len(best):
                best = found
        return best

    def _on_drop(self, event: Any) -> None:
        """Handle files dropped onto the drop zone."""
        if self.busy:
            return

        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder on the Play tab first.")
            return

        files = self._parse_drop(str(event.data))
        if not files:
            self.set_status("Nothing usable was dropped -- drop files, not folders.")
            return

        self.import_paths(files, directory)

    def choose_files_to_import(self) -> None:
        """Pick local jars or pack zips and file them into the game folder."""
        if self.busy:
            return

        directory = self.directory_var.get().strip()
        if not directory:
            self.set_status("Choose a game folder on the Play tab first.")
            return

        chosen = filedialog.askopenfilenames(
            title="Choose mods, resource packs or shader packs",
            filetypes=[("Mods and packs", "*.jar *.zip"), ("All files", "*.*")],
        )
        if not chosen:
            return

        version = self.version_menu.get()
        target = (
            installer.instance_directory(version, directory)
            if version in self.versions
            else Path(directory)
        )
        self.import_paths(chosen, str(target))

    def import_paths(self, paths: Sequence[str], directory: str) -> None:
        """Import a list of local files off the UI thread.

        Separate from the file picker so a drop zone, or a test, can hand files
        in without going through a dialog.
        """
        if self.busy:
            return

        files = list(paths)
        self._set_busy(True)
        self.progress.set(0)
        self.set_status(f"Importing {len(files)} file(s)...")

        report = self.worker.progress_bridge(self.show_progress)
        self.worker.submit(
            lambda: imports.import_files(files, directory, on_progress=report),
            on_success=self._import_finished,
            on_error=self._import_failed_batch,
        )

    def _import_finished(self, results: list) -> None:
        self.clear_progress()
        self._set_busy(False)
        show = self.set_status if any(r.error for r in results) else self.flash_status
        show(imports.describe(results))

    def _import_failed_batch(self, error: BaseException) -> None:
        self.clear_progress()
        self._set_busy(False)
        self.set_status(f"Import failed: {error}")

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
