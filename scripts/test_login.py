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

import codecs
import os
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
    #
    # This used to be one check that wrote its own tidy UTF-8 file with a
    # trailing newline and read it back. That is the single shape which already
    # worked, so it kept passing while the function was broken for the files
    # people actually produce: PowerShell's redirect writes UTF-16 with a BOM,
    # and -Encoding utf8 writes UTF-8 *with* a BOM, which parsed as a key named
    # "﻿MAESTRO_CLIENT_ID" and therefore matched nothing.
    client_id = "11111111-2222-3333-4444-555555555555"

    def as_utf8(text: str) -> bytes:
        return text.encode("utf-8")

    def as_utf8_bom(text: str) -> bytes:
        return codecs.BOM_UTF8 + text.encode("utf-8")

    def as_utf16le_bom(text: str) -> bytes:
        return codecs.BOM_UTF16_LE + text.encode("utf-16-le")

    def as_utf16be_bom(text: str) -> bytes:
        return codecs.BOM_UTF16_BE + text.encode("utf-16-be")

    def as_utf32le_bom(text: str) -> bytes:
        return codecs.BOM_UTF32_LE + text.encode("utf-32-le")

    def as_cp1252(text: str) -> bytes:
        return text.encode("cp1252")

    cases = [
        ("plain utf-8, trailing newline", as_utf8, "MAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("no trailing newline", as_utf8, "MAESTRO_CLIENT_ID=<<V>>", client_id),
        ("utf-8 WITH BOM, no trailing newline", as_utf8_bom, "MAESTRO_CLIENT_ID=<<V>>", client_id),
        ("utf-16 LE with BOM (PowerShell default)", as_utf16le_bom, "MAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("utf-16 LE with BOM, no trailing newline", as_utf16le_bom, "MAESTRO_CLIENT_ID=<<V>>", client_id),
        ("utf-16 BE with BOM", as_utf16be_bom, "MAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("utf-32 LE with BOM", as_utf32le_bom, "MAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("crlf line endings", as_utf8, "MAESTRO_CLIENT_ID=<<V>>\r\n", client_id),
        # Not UTF-8 and no BOM to go on. Both parities, because a bare
        # decode("utf-16") accepts any even-length input and returns nonsense,
        # so this used to pass or fail on byte count alone.
        ("cp1252, odd byte count", as_cp1252, "# Dimitris’ key\nMAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("cp1252, even byte count", as_cp1252, "# Dimitris’ keys\nMAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("whitespace around key and value", as_utf8, "   MAESTRO_CLIENT_ID   =   <<V>>   \n", client_id),
        ("double quoted value", as_utf8, 'MAESTRO_CLIENT_ID="<<V>>"\n', client_id),
        ("single quoted value", as_utf8, "MAESTRO_CLIENT_ID='<<V>>'\n", client_id),
        ("quotes with padding inside", as_utf8, 'MAESTRO_CLIENT_ID = "  <<V>>  "\n', client_id),
        ("export prefix", as_utf8, "export MAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("AZURE_CLIENT_ID fallback key", as_utf8, "AZURE_CLIENT_ID=<<V>>\n", client_id),
        ("comments and blank lines first", as_utf8, "# a note\n\nMAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("other keys are skipped", as_utf8, "OTHER=nope\nMAESTRO_CLIENT_ID=<<V>>\n", client_id),
        ("empty value reads as absent", as_utf8, "MAESTRO_CLIENT_ID=\n", None),
        ("quoted empty value reads as absent", as_utf8, 'MAESTRO_CLIENT_ID=""\n', None),
        ("wrong key only", as_utf8, "SOMETHING_ELSE=<<V>>\n", None),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        # load_client_id reads the environment before the file, so if either key
        # is set here every case below would pass without opening anything.
        saved = {k: os.environ.pop(k, None) for k in ("MAESTRO_CLIENT_ID", "AZURE_CLIENT_ID")}
        try:
            os.environ["MAESTRO_CLIENT_ID"] = "from-the-environment"
            precedence = Path(tmp) / "precedence.env"
            precedence.write_bytes(as_utf8("MAESTRO_CLIENT_ID=" + client_id + "\n"))
            check(
                "the environment wins over the file",
                load_client_id(precedence) == "from-the-environment",
                str(load_client_id(precedence)),
            )
            del os.environ["MAESTRO_CLIENT_ID"]

            # The sentinel is "<<V>>" and not "ID" because the key itself ends in
            # ID -- a bare placeholder would rewrite MAESTRO_CLIENT_ID as well as
            # its value. A row that forgets the sentinel writes a literal value
            # and quietly asserts nothing, so refuse to run one.
            for label, _encode, template, expected in cases:
                if expected is not None and "<<V>>" not in template:
                    check(f".env: {label}", False, "fixture never substitutes <<V>>")

            for index, (label, encode, template, expected) in enumerate(cases):
                if expected is not None and "<<V>>" not in template:
                    continue
                path = Path(tmp) / f"case{index}.env"
                path.write_bytes(encode(template.replace("<<V>>", client_id)))
                try:
                    got = load_client_id(path)
                except Exception as exc:  # noqa: BLE001
                    check(f".env: {label}", False, f"raised {type(exc).__name__}: {exc}")
                    continue
                check(f".env: {label}", got == expected, f"got {got!r}, wanted {expected!r}")

            check("returns None when there is no .env", load_client_id(Path(tmp) / "nope") is None)

            binary = Path(tmp) / "binary.env"
            binary.write_bytes(bytes(range(256)) * 4)
            try:
                check("a binary file reads as absent", load_client_id(binary) is None)
            except Exception as exc:  # noqa: BLE001
                check("a binary file reads as absent", False, f"raised {type(exc).__name__}")

            check("no env_file given is None", load_client_id(None) is None)

            # The fixtures above are all files this script wrote itself, which is
            # exactly how the old single check stayed green while the function was
            # broken for real input. So finish on the actual .env, whatever shape
            # the person's shell left it in. Absent is fine -- that is a fresh
            # clone, and main() reports it properly further down.
            if ENV_FILE.exists():
                real = load_client_id(ENV_FILE)
                check(
                    f"the real {ENV_FILE.name} on disk parses",
                    bool(real),
                    f"{ENV_FILE} is {ENV_FILE.stat().st_size} bytes but yielded {real!r}",
                )
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)

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
