"""Microsoft account login for MaestroLauncher.

Wraps ``minecraft_launcher_lib.microsoft_account``: builds a PKCE login URL,
catches the OAuth redirect on a short-lived local HTTP server, exchanges the code
for a Minecraft token, and keeps the refresh token on disk so a restart does not
mean logging in again.

Nothing here imports a GUI or a browser widget -- ``login()`` shells out to the
system browser and waits for the redirect, so the whole flow is drivable from a
terminal or from a worker thread behind the GUI.

**This needs an approved Azure app** (PLAN.md M0). Until the Minecraft API
permission request is granted, ``api.minecraftservices.com`` answers 403 and the
final step of the login fails; that arrives here as ``AzureAppNotApproved`` with
an explanation rather than a library traceback.

Tokens are secrets. ``Account`` keeps them out of its repr, they are never put in
an exception message, and the saved file is written owner-only where the OS
supports it.
"""

from __future__ import annotations

import codecs
import json
import os
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

import minecraft_launcher_lib as mll
import requests

# Must match the redirect URI registered on the Azure app exactly, including the
# path and the lack of a trailing slash.
DEFAULT_REDIRECT_URI = "http://localhost:8000/callback"

# The file the refresh token lives in, inside whichever directory the caller picks.
ACCOUNT_FILENAME = "maestro_account.json"

# How long to wait for the person to finish logging in before giving up.
DEFAULT_TIMEOUT = 300.0

StatusCallback = Callable[[str], None]

_BROWSER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>MaestroLauncher</title></head>
<body style="font-family:system-ui;text-align:center;padding-top:4rem">
<h2>{heading}</h2><p>{detail}</p><p>You can close this tab and go back to MaestroLauncher.</p>
</body></html>"""


class AuthError(RuntimeError):
    """Anything that stopped a login from finishing."""


class AzureAppNotApproved(AuthError):
    """The Azure app is not permitted to use the Minecraft API (PLAN.md M0)."""


class LoginRequired(AuthError):
    """No usable saved login. The caller must run an interactive ``login()``."""


class LoginCancelled(AuthError):
    """The person closed the browser or refused the consent screen."""


@dataclass(frozen=True)
class Account:
    """A logged-in Minecraft account.

    ``access_token`` and ``refresh_token`` are deliberately kept out of the repr
    so they cannot leak into a log line or a traceback.
    """

    username: str
    uuid: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


def _to_account(data: dict) -> Account:
    """Turn the library's CompleteLoginResponse into our own type."""
    try:
        return Account(
            username=data["name"],
            uuid=data["id"],
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
        )
    except KeyError as exc:
        raise AuthError(f"Microsoft returned a login response with no {exc} field.") from exc


def _wait_for_redirect(
    redirect_uri: str,
    timeout: float,
    on_status: Optional[StatusCallback] = None,
) -> str:
    """Serve the redirect URI until the browser comes back, and return the URL hit.

    Runs a single-threaded HTTP server that answers exactly one real callback.
    Anything else (a favicon request, a stray probe) gets a 404 and is ignored.
    """
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    callback_path = parsed.path or "/"

    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        # BaseHTTPRequestHandler logs every hit to stderr; core does not print.
        def log_message(self, format: str, *args: object) -> None:
            return

        def _reply(self, code: int, heading: str, detail: str) -> None:
            body = _BROWSER_PAGE.format(heading=heading, detail=detail).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 -- name fixed by the stdlib
            if urllib.parse.urlparse(self.path).path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "error" in query:
                captured["error"] = query["error"][0]
                captured["error_description"] = query.get("error_description", [""])[0]
                self._reply(400, "Login failed", captured["error_description"] or captured["error"])
                return

            captured["url"] = f"{redirect_uri.split('?')[0]}?{urllib.parse.urlparse(self.path).query}"
            self._reply(200, "Signed in", "MaestroLauncher has what it needs.")

    try:
        server = HTTPServer((host, port), Handler)
    except OSError as exc:
        raise AuthError(
            f"Cannot listen on {host}:{port} for the login redirect: {exc}. "
            "Another program may already be using that port."
        ) from exc

    if on_status:
        on_status(f"Waiting for the browser to come back to {redirect_uri}")

    # A per-request timeout lets handle_request() return so the deadline is checked
    # even when nothing ever hits the port.
    server.timeout = 1.0
    remaining = timeout

    try:
        while not captured:
            if remaining <= 0:
                raise AuthError(
                    f"Timed out after {timeout:.0f}s waiting for the login redirect."
                )
            server.handle_request()
            remaining -= server.timeout
    except KeyboardInterrupt:
        raise LoginCancelled("Login cancelled.") from None
    finally:
        server.server_close()

    if "error" in captured:
        detail = captured.get("error_description") or captured["error"]
        if captured["error"] in {"access_denied", "consent_required"}:
            raise LoginCancelled(f"Login was declined: {detail}")
        raise AuthError(f"Microsoft rejected the login: {detail}")

    return captured["url"]


def login(
    client_id: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    timeout: float = DEFAULT_TIMEOUT,
    open_browser: bool = True,
    on_status: Optional[StatusCallback] = None,
) -> Account:
    """Run the interactive login and return the signed-in account.

    Opens the system browser, waits for the redirect on ``redirect_uri``, then
    exchanges the code. ``open_browser=False`` leaves opening it to the caller,
    which is what the GUI wants when it shows the URL itself.
    """
    if not client_id:
        raise AuthError("No Azure client ID. See PLAN.md M0.")

    try:
        login_url, state, code_verifier = mll.microsoft_account.get_secure_login_data(
            client_id, redirect_uri
        )
    except Exception as exc:
        raise AuthError(f"Could not build the login URL: {exc}") from exc

    if on_status:
        on_status("Opening your browser to sign in with Microsoft")
    if open_browser and not webbrowser.open(login_url):
        raise AuthError(f"Could not open a browser. Open this URL by hand:\n{login_url}")

    redirect_url = _wait_for_redirect(redirect_uri, timeout, on_status=on_status)

    try:
        auth_code = mll.microsoft_account.parse_auth_code_url(redirect_url, state)
    except AssertionError:
        # The state we generated did not come back -- treat it as hostile.
        raise AuthError(
            "The login redirect carried the wrong state value and was rejected. "
            "Start the login again."
        ) from None
    except KeyError as exc:
        raise AuthError(f"The login redirect was missing its {exc} value.") from exc

    if on_status:
        on_status("Exchanging the code with Xbox Live and Minecraft services")

    return _exchange_code(client_id, redirect_uri, auth_code, code_verifier)


def _exchange_code(
    client_id: str,
    redirect_uri: str,
    auth_code: str,
    code_verifier: str,
) -> Account:
    """Trade the authorization code for a Minecraft session.

    Split out from ``login()`` so the failure mapping can be exercised without
    driving a browser.
    """
    try:
        data = mll.microsoft_account.complete_login(
            client_id, None, redirect_uri, auth_code, code_verifier
        )
    except mll.exceptions.AzureAppNotPermitted as exc:
        raise AzureAppNotApproved(
            "This Azure app is not approved for the Minecraft API, so Minecraft "
            "returned 403. Submit the Minecraft API permission request for the app "
            "and wait for approval (PLAN.md M0)."
        ) from exc
    except mll.exceptions.AccountNotOwnMinecraft as exc:
        raise AuthError(
            "That Microsoft account does not own Minecraft: Java Edition."
        ) from exc
    except requests.RequestException as exc:
        raise AuthError(f"Could not reach the login servers: {exc}") from exc
    except KeyError as exc:
        # Microsoft answered, but not with a token. complete_login() indexes the
        # token response straight away, so a refusal arrives as a bare
        # KeyError('access_token') and the real AADSTS code is thrown away.
        #
        # The Minecraft hop is not what failed here: complete_login() checks that
        # one itself and raises AzureAppNotPermitted, which is caught above. So a
        # KeyError means Microsoft's own token endpoint said no, and by far the
        # most common reason is the Azure app being registered with a "Web"
        # redirect URI. That makes it a confidential client, which Azure insists
        # must send a client secret (AADSTS70002) -- but this is a PKCE public
        # client and has no secret to send.
        raise AuthError(
            f"Microsoft refused the login and returned no {exc}. The usual cause is "
            "the redirect URI being registered under the wrong platform: it must be "
            'under "Mobile and desktop applications", not "Web". A Web redirect URI '
            "makes Azure demand a client secret that this PKCE login does not use. "
            f"Also check the client ID, and that the URI is exactly {redirect_uri}."
        ) from exc
    except Exception as exc:
        # Belt and braces: the GUI must never see a library traceback.
        raise AuthError(f"The login failed unexpectedly: {exc}") from exc

    return _to_account(data)


def refresh(client_id: str, refresh_token: str) -> Account:
    """Trade a saved refresh token for a fresh session, without a browser.

    Raises ``LoginRequired`` when the token has expired or been revoked, which is
    the caller's cue to run ``login()`` again.
    """
    if not client_id:
        raise AuthError("No Azure client ID. See PLAN.md M0.")
    if not refresh_token:
        raise LoginRequired("No saved refresh token.")

    try:
        data = mll.microsoft_account.complete_refresh(client_id, None, None, refresh_token)
    except mll.exceptions.InvalidRefreshToken as exc:
        # Microsoft does not say why it refused, so a wrong client ID looks the
        # same as a genuinely expired token. Either way the fix is a fresh login,
        # which then reports the real problem.
        raise LoginRequired(
            "The saved login could not be renewed. Sign in again."
        ) from exc
    except mll.exceptions.AzureAppNotPermitted as exc:
        raise AzureAppNotApproved(
            "This Azure app is not approved for the Minecraft API (PLAN.md M0)."
        ) from exc
    except mll.exceptions.AccountNotOwnMinecraft as exc:
        raise AuthError("That Microsoft account does not own Minecraft: Java Edition.") from exc
    except requests.RequestException as exc:
        raise AuthError(f"Could not reach the login servers: {exc}") from exc
    except KeyError as exc:
        raise LoginRequired(
            f"Renewing the saved login returned no {exc}. Sign in again."
        ) from exc
    except Exception as exc:
        raise AuthError(f"Renewing the saved login failed unexpectedly: {exc}") from exc

    return _to_account(data)


def account_path(directory: Path | str) -> Path:
    """Where the saved account lives inside a given directory."""
    return Path(directory).expanduser() / ACCOUNT_FILENAME


def save_account(account: Account, directory: Path | str) -> Path:
    """Persist the refresh token so the next start can skip the browser.

    The file holds a live credential. It is written owner-only where the OS
    honours that, but it is not encrypted -- treat it like a password file.
    """
    path = account_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "username": account.username,
            "uuid": account.uuid,
            "refresh_token": account.refresh_token,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        raise AuthError(f"Could not save the login to {path}: {exc}") from exc

    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best effort. Windows ACLs do not map onto this and it is not fatal.
        pass

    return path


def load_account(directory: Path | str) -> Optional[Account]:
    """Read the saved account, or None if there is nothing usable saved.

    A missing, unreadable or malformed file all mean the same thing to the caller
    -- log in again -- so none of them raise. The returned account carries only
    the refresh token; pass it to ``refresh()`` to get a usable access token.
    """
    path = account_path(directory)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if not isinstance(payload, dict) or not payload.get("refresh_token"):
        return None

    return Account(
        username=str(payload.get("username", "")),
        uuid=str(payload.get("uuid", "")),
        access_token="",
        refresh_token=str(payload["refresh_token"]),
    )


def clear_account(directory: Path | str) -> None:
    """Forget the saved login. Safe to call when nothing is saved."""
    try:
        account_path(directory).unlink(missing_ok=True)
    except OSError as exc:
        raise AuthError(f"Could not remove the saved login: {exc}") from exc


def login_or_refresh(
    client_id: str,
    directory: Path | str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    timeout: float = DEFAULT_TIMEOUT,
    open_browser: bool = True,
    on_status: Optional[StatusCallback] = None,
) -> Account:
    """Get a usable account: refresh the saved login, or sign in from scratch.

    This is the one the GUI should call. The result is always saved back, so the
    rotated refresh token is not lost.
    """
    saved = load_account(directory)
    if saved:
        if on_status:
            on_status(f"Restoring the saved login for {saved.username or 'your account'}")
        try:
            account = refresh(client_id, saved.refresh_token)
            save_account(account, directory)
            return account
        except LoginRequired:
            # Expired or revoked. Drop it and fall through to a real login.
            clear_account(directory)

    account = login(
        client_id,
        redirect_uri=redirect_uri,
        timeout=timeout,
        open_browser=open_browser,
        on_status=on_status,
    )
    save_account(account, directory)
    return account


def load_client_id(env_file: Path | str | None = None) -> Optional[str]:
    """Find the Azure client ID, from the environment or a .env file.

    Checks ``MAESTRO_CLIENT_ID`` then ``AZURE_CLIENT_ID`` in the environment, then
    the same two keys in ``env_file`` if one is given. Returns None when the ID has
    not been set up yet, which is the normal state until PLAN.md M0 is done.
    """
    for key in ("MAESTRO_CLIENT_ID", "AZURE_CLIENT_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value

    if env_file is None:
        return None

    text = _read_text_any_encoding(Path(env_file).expanduser())
    if text is None:
        return None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        # ".env" files are often written to be sourced by a shell.
        if key.startswith("export "):
            key = key[len("export "):].strip()

        if key in {"MAESTRO_CLIENT_ID", "AZURE_CLIENT_ID"}:
            return _unquote(value) or None

    return None


def _unquote(value: str) -> str:
    """Trim whitespace and one matching pair of surrounding quotes."""
    value = value.strip()
    for quote in ('"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1].strip()
    return value


def _read_text_any_encoding(path: Path) -> Optional[str]:
    """Read a text file whatever encoding it happens to be in.

    A .env file is written by whatever the person had to hand, and on Windows
    that is usually PowerShell, which does not write plain UTF-8:

    * ``Out-File`` and ``>`` in Windows PowerShell 5.1 write UTF-16 LE with a
      BOM. Decoding that as UTF-8 raises UnicodeDecodeError, which is a
      ValueError and so slipped straight past a bare ``except OSError``.
    * ``-Encoding utf8`` writes UTF-8 *with* a BOM. That decodes without
      complaint, but leaves a zero-width no-break space on the front of the
      first key, so ``MAESTRO_CLIENT_ID`` silently stops matching and the file
      looks empty of anything useful.

    So the bytes are sniffed for a BOM first, then tried as UTF-8, then as
    UTF-16 but only if they contain a NUL to justify it, and finally as latin-1,
    which cannot fail. Returns None only when the file cannot be read at all.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    # Longest BOMs first: the UTF-32 LE mark starts with the UTF-16 LE one.
    for bom, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if raw.startswith(bom):
            try:
                return raw[len(bom):].decode(encoding)
            except UnicodeDecodeError:
                break

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # No BOM and not UTF-8. Only try UTF-16 if the bytes actually look like it:
    # ``bytes.decode("utf-16")`` accepts *any* even-length input and happily
    # returns CJK nonsense, so trying it blind makes a single-byte file parse or
    # not depending on whether its length happens to be even. Real UTF-16 text in
    # the ASCII range is half NUL bytes; a NUL never appears in a single-byte
    # .env, so their presence is the thing worth branching on.
    if b"\x00" in raw:
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass

    # latin-1 maps every byte to a character, so this always returns something.
    # A binary file will produce nonsense, but nonsense that matches no key.
    return raw.decode("latin-1")
