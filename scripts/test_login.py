"""Milestone 2 acceptance test.

Two halves:

1. Self-checks that need no Azure app -- the redirect server, the token store and
   the error mapping. These run today.
2. The real thing: open a browser, complete a Microsoft login, print the username
   and UUID. This needs an approved Azure app (PLAN.md M0) and a client ID in
   .env, and is skipped with a clear message when there isn't one.

    python scripts/test_login.py              # self-checks, then real login
    python scripts/test_login.py --selftest   # self-checks only
    python scripts/test_login.py --logout     # forget the saved login

Exits 0 when the milestone's acceptance criterion is met, 1 otherwise.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.auth import (  # noqa: E402
    DEFAULT_REDIRECT_URI,
    Account,
    AuthError,
    LoginCancelled,
    LoginRequired,
    account_path,
    clear_account,
    load_account,
    load_client_id,
    login_or_refresh,
    refresh,
    save_account,
)
from core.auth import _wait_for_redirect  # noqa: E402 -- the bit worth testing

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
TARGET = ROOT / "test_mc"

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


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        return int(sock.getsockname()[1])


def hit(url: str) -> int:
    """GET a URL and return the status code, treating an HTTP error as its code."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except OSError:
        return 0


def selftest() -> bool:
    print("Self-checks (no Azure app needed)\n")

    # The redirect URI has to match what M0 registers, character for character.
    check(
        "default redirect URI matches the one M0 registers",
        DEFAULT_REDIRECT_URI == "http://localhost:8000/callback",
        DEFAULT_REDIRECT_URI,
    )

    # 1. The callback server captures a real redirect and ignores noise.
    port = free_port()
    redirect_uri = f"http://localhost:{port}/callback"
    captured: list[str] = []
    error: list[BaseException] = []

    def serve() -> None:
        try:
            captured.append(_wait_for_redirect(redirect_uri, timeout=15))
        except BaseException as exc:  # noqa: BLE001 -- reported below
            error.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    time.sleep(0.4)

    favicon = hit(f"http://localhost:{port}/favicon.ico")
    check("a non-callback request is ignored with a 404", favicon == 404, f"got {favicon}")
    check("the server is still waiting after the stray request", thread.is_alive())

    status = hit(f"http://localhost:{port}/callback?code=test-code&state=test-state")
    thread.join(timeout=5)
    check("the browser gets a real page back", status == 200, f"got {status}")
    check("the redirect URL is captured", bool(captured) and "code=test-code" in captured[0])
    check("no error raised while capturing", not error, repr(error[:1]))

    # 2. A denied consent screen reads as a cancellation, not a crash.
    port = free_port()
    redirect_uri = f"http://localhost:{port}/callback"
    outcome: list[BaseException] = []

    def serve_denied() -> None:
        try:
            _wait_for_redirect(redirect_uri, timeout=15)
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)

    thread = threading.Thread(target=serve_denied, daemon=True)
    thread.start()
    time.sleep(0.4)
    hit(f"http://localhost:{port}/callback?error=access_denied&error_description=User+said+no")
    thread.join(timeout=5)
    check(
        "a declined login raises LoginCancelled",
        bool(outcome) and isinstance(outcome[0], LoginCancelled),
        repr(outcome[:1]),
    )

    # 3. Waiting forever is not an option.
    started = time.monotonic()
    try:
        _wait_for_redirect(f"http://localhost:{free_port()}/callback", timeout=1.0)
        check("the wait times out", False, "it returned instead")
    except AuthError as exc:
        elapsed = time.monotonic() - started
        check("the wait times out cleanly", "Timed out" in str(exc) and elapsed < 10, f"{elapsed:.1f}s")

    # 4. The token store round-trips, and forgetting works.
    with tempfile.TemporaryDirectory() as tmp:
        check("nothing saved reads back as None", load_account(tmp) is None)

        account = Account(
            username="Notch", uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5",
            access_token="access-secret", refresh_token="refresh-secret",
        )
        path = save_account(account, tmp)
        loaded = load_account(tmp)
        check("saved account round-trips", loaded is not None and loaded.username == "Notch")
        check(
            "the refresh token survives",
            loaded is not None and loaded.refresh_token == "refresh-secret",
        )

        saved_text = path.read_text(encoding="utf-8")
        check("the access token is NOT written to disk", "access-secret" not in saved_text)
        check("tokens stay out of the repr", "refresh-secret" not in repr(account), repr(account))

        account_path(tmp).write_text("{ this is not json", encoding="utf-8")
        check("a corrupt token file reads back as None", load_account(tmp) is None)

        clear_account(tmp)
        check("clear_account removes the file", not account_path(tmp).exists())
        clear_account(tmp)  # must not raise the second time
        check("clear_account is safe to repeat", True)

    # 5. Bad input is our error type, never a library traceback.
    for label, call in (
        ("empty client ID", lambda: refresh("", "token")),
        ("empty refresh token", lambda: refresh("client", "")),
    ):
        try:
            call()
            check(f"{label} raises", False, "nothing raised")
        except AuthError as exc:
            check(f"{label} raises {type(exc).__name__}", True)
        except Exception as exc:  # noqa: BLE001
            check(f"{label} raises AuthError", False, f"leaked {type(exc).__name__}: {exc}")

    # A present-but-wrong client ID is the likely real mistake, and the library
    # signals it with a bare KeyError. Needs the network; a network failure is
    # also an AuthError, so either way the assertion holds.
    from core.auth import _exchange_code

    try:
        _exchange_code(
            "00000000-0000-0000-0000-000000000000",
            DEFAULT_REDIRECT_URI,
            "junk-code",
            "junk-verifier",
        )
        check("a rejected code exchange raises", False, "nothing raised")
    except AuthError as exc:
        check("a rejected code exchange raises AuthError", True)
        check("its message is actionable", "client ID" in str(exc) or "reach" in str(exc), str(exc)[:80])
    except Exception as exc:  # noqa: BLE001
        check(
            "a rejected code exchange raises AuthError",
            False,
            f"leaked {type(exc).__name__}: {exc}",
        )

    # 6. The client ID reader.
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text('# comment\nMAESTRO_CLIENT_ID = "abc-123"\n', encoding="utf-8")
        check("reads a client ID from .env", load_client_id(env) == "abc-123", str(load_client_id(env)))
        check("returns None when there is no .env", load_client_id(Path(tmp) / "nope") is None)

    print(f"\n  {_passed} passed, {_failed} failed\n")
    return _failed == 0


def real_login(client_id: str) -> int:
    print("Interactive login\n")
    print("  A browser window will open. Sign in with the Microsoft account that")
    print("  owns Minecraft: Java Edition, then come back here.\n")

    try:
        account = login_or_refresh(
            client_id, TARGET, on_status=lambda text: print(f"  ... {text}")
        )
    except LoginCancelled as exc:
        print(f"\nCancelled: {exc}")
        return 1
    except LoginRequired as exc:
        print(f"\nFAILED: {exc}")
        return 1
    except AuthError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1

    print(f"\n  username: {account.username}")
    print(f"  uuid:     {account.uuid}")
    print(f"  token:    {'yes' if account.access_token else 'MISSING'}")
    print(f"  saved to: {account_path(TARGET)}")

    if not account.username or not account.uuid or not account.access_token:
        print("\nFAILED: the login came back incomplete.")
        return 1

    if load_account(TARGET) is None:
        print("\nFAILED: the login did not persist; a restart would need the browser again.")
        return 1

    print("\nMilestone 2 PASSED")
    return 0


def main() -> int:
    if "--logout" in sys.argv:
        clear_account(TARGET)
        print(f"Forgot the saved login at {account_path(TARGET)}")
        return 0

    print("MaestroLauncher login test")
    print(f"  redirect: {DEFAULT_REDIRECT_URI}")
    print(f"  storage:  {account_path(TARGET)}\n")

    if not selftest():
        print("FAILED: self-checks did not pass.")
        return 1

    if "--selftest" in sys.argv:
        print("Self-checks only. Skipping the interactive login.")
        return 0

    client_id = load_client_id(ENV_FILE)
    if not client_id:
        print("BLOCKED: no Azure client ID, so the login itself cannot run.")
        print()
        print("  The code is in place and its self-checks pass, but M2 needs M0 first:")
        print("    1. Create an Azure app registration, personal Microsoft accounts only")
        print(f"    2. Add the redirect URI {DEFAULT_REDIRECT_URI} (type: Web)")
        print("    3. Submit the Minecraft API permission request and wait for approval")
        print(f"    4. Put MAESTRO_CLIENT_ID=<the id> in {ENV_FILE}")
        print()
        print("  Then run this script again. Without approval the login reaches Microsoft")
        print("  but Minecraft answers 403, which surfaces as AzureAppNotApproved.")
        return 1

    print(f"Client ID found ({client_id[:8]}...). Continuing.\n")
    return real_login(client_id)


if __name__ == "__main__":
    raise SystemExit(main())
