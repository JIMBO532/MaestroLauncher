"""Keeps a second copy of the launcher from running alongside the first.

Two MaestroLauncher processes pointed at the same .minecraft, each racing
core.installer.link_shared_data() on the same instance directory, is one
concrete way the FileAlreadyExistsException in the 2026-09-12 crash report
could happen -- installer.py is now safe under that race regardless, but
never letting two copies run in the first place removes the precondition
outright, not just one of its symptoms.

A named OS mutex rather than a lock file: Windows releases it the instant
the owning process exits, crash or not, so there is no stale lock left
behind to clean up by hand -- a real risk for a launcher that starts a
long-running game and can be killed from outside.
"""

from __future__ import annotations

import ctypes

_MUTEX_NAME = "Local\\MaestroLauncher-SingleInstance"
_ERROR_ALREADY_EXISTS = 183

_handle: int | None = None  # kept alive for the process lifetime


def acquire() -> bool:
    """True if this process is the only one running.

    False means another instance already holds the mutex. Safe to call more
    than once -- only the first call does anything, and later calls just
    report that this process still holds it.
    """
    global _handle
    if _handle is not None:
        return True

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        # Not Windows -- nothing here is enforceable, so don't pretend it is.
        return True

    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        # Could not even ask. Startup should not block over that.
        return True

    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _handle = handle
    return True
