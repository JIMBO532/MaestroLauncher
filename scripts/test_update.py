"""core.update: release parsing, checksum enforcement, installer launch
failure modes, and the post-restart outcome. No network, nothing executed.

    python scripts/test_update.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import __version__, update  # noqa: E402

NEWER = "v" + ".".join(str(n + (1 if i == 0 else 0)) for i, n in enumerate(update._parse_version(__version__)))
GH = "https://github.com/JIMBO532/MaestroLauncher/releases/download/x/"


class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status
        self.ok = status < 400

    def raise_for_status(self):
        if not self.ok:
            raise update.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def with_get(response):
    update.requests.get = lambda *a, **k: response


def release(*asset_names):
    return {
        "tag_name": NEWER,
        "html_url": "https://github.com/JIMBO532/MaestroLauncher/releases/tag/" + NEWER,
        "assets": [
            {"name": n, "browser_download_url": GH + n, "size": 1234} for n in asset_names
        ],
    }


def test_check_requires_checksum_asset():
    with_get(FakeResponse(release(update.INSTALLER_ASSET_NAME, update.CHECKSUM_ASSET_NAME)))
    info = update.check_for_update()
    assert info and info.installable and info.download_size == 1234, info

    with_get(FakeResponse(release(update.INSTALLER_ASSET_NAME)))
    info = update.check_for_update()
    assert info and not info.installable and info.download_url is None, info

    payload = release(update.INSTALLER_ASSET_NAME, update.CHECKSUM_ASSET_NAME)
    payload["assets"][0]["browser_download_url"] = "https://evil.example/x.exe"
    with_get(FakeResponse(payload))
    assert not update.check_for_update().installable

    with_get(FakeResponse({"tag_name": "v" + __version__, "assets": []}))
    assert update.check_for_update() is None


def test_checksum_parsing():
    digest = "ab" * 32
    for text in (digest, f"{digest}  MaestroLauncherSetup.exe\n", digest.upper()):
        with_get(FakeResponse(text=text))
        assert update.fetch_expected_sha256("u") == digest
    for bad in (FakeResponse(text="not a hash"), FakeResponse(status=404)):
        with_get(bad)
        try:
            update.fetch_expected_sha256("u")
        except update.UpdateError:
            pass
        else:
            raise AssertionError("bad checksum accepted")


class FakeProcess:
    def __init__(self, exit_code):
        self.exit_code = exit_code
        self.killed = False

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True


def ready_path(args) -> Path:
    return Path(next(a for a in args if a.startswith("/READYFILE=")).split("=", 1)[1])


def make_installer(workdir: Path) -> tuple[Path, str]:
    path = workdir / update.INSTALLER_ASSET_NAME
    path.write_bytes(b"pretend installer")
    return path, hashlib.sha256(b"pretend installer").hexdigest()


def info() -> update.UpdateInfo:
    return update.UpdateInfo(
        __version__, NEWER[1:], "https://github.com/x/y", GH + "a", GH + "b", 1
    )


def expect(exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


def test_mismatch_never_runs():
    spawned = []
    update._spawn = lambda args: spawned.append(args)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path, _ = make_installer(workdir)
        expect(
            update.IntegrityError,
            lambda: update.run_installer(info(), path, "0" * 64, workdir=workdir, wait_pids=[1]),
        )
        assert not spawned, "a mismatched installer was run"
        assert not path.exists(), "mismatched installer was left on disk"
        assert not (workdir / update.PENDING_MARKER).exists()


def test_blocked_at_start():
    def blocked(args):
        err = OSError("An Application Control policy has blocked this file")
        err.winerror = 4551
        raise err

    update._spawn = blocked
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path, digest = make_installer(workdir)
        exc = expect(
            update.InstallerBlocked,
            lambda: update.run_installer(info(), path, digest, workdir=workdir, wait_pids=[1]),
        )
        assert "Smart App Control" in str(exc), exc
        assert not (workdir / update.PENDING_MARKER).exists()


def test_killed_right_after_start():
    update._spawn = lambda args: FakeProcess(exit_code=1)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path, digest = make_installer(workdir)
        exc = expect(
            update.InstallerBlocked,
            lambda: update.run_installer(
                info(), path, digest, workdir=workdir, wait_pids=[1], timeout=5
            ),
        )
        assert "exit code 1" in str(exc), exc
        assert not (workdir / update.PENDING_MARKER).exists()


def test_second_stage_never_reports_in():
    """The 1.1.0 -> 1.1.1 failure: Setup.exe starts fine, Smart App Control
    blocks the setup.tmp it unpacks, nothing ever writes the ready file.
    The launcher must not close -- it has to stop the stub and say so."""
    stuck = FakeProcess(exit_code=None)
    update._spawn = lambda args: stuck
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path, digest = make_installer(workdir)
        exc = expect(
            update.InstallerBlocked,
            lambda: update.run_installer(
                info(), path, digest, workdir=workdir, wait_pids=[1], timeout=0.5
            ),
        )
        assert "Smart App Control" in str(exc), exc
        assert stuck.killed, "stuck installer was left running"
        assert not (workdir / update.PENDING_MARKER).exists()


def test_running_installer_gets_the_right_arguments():
    spawned = []

    def spawn(args):
        spawned.append(args)
        ready_path(args).write_text("ready")
        return FakeProcess(exit_code=None)

    update._spawn = spawn
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path, digest = make_installer(workdir)
        update.run_installer(
            info(), path, digest.upper(), workdir=workdir, wait_pids=[111, 222], timeout=5
        )
        args = spawned[0]
        assert args[0] == str(path)
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/RELAUNCH=1", "/WAITPID1=111", "/WAITPID2=222"):
            assert flag in args, (flag, args)
        assert not ready_path(args).exists(), "ready file not cleaned up"
        marker = json.loads((workdir / update.PENDING_MARKER).read_text())
        assert marker["target_version"] == NEWER[1:]


def test_outcome_reported_once():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        marker = workdir / update.PENDING_MARKER
        marker.write_text(json.dumps({"target_version": NEWER[1:], "log_path": "l", "release_url": "https://github.com/a"}))
        outcome = update.take_install_outcome(workdir)
        assert outcome and not outcome.succeeded, outcome
        assert update.take_install_outcome(workdir) is None

        marker.write_text(json.dumps({"target_version": __version__, "release_url": "https://evil.example"}))
        outcome = update.take_install_outcome(workdir)
        assert outcome.succeeded and outcome.release_url == update.FALLBACK_RELEASES_URL


def test_launcher_pids_from_source():
    assert update.launcher_pids() == [__import__("os").getpid()]


def main() -> int:
    original_get, original_spawn = update.requests.get, update._spawn
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
        finally:
            update.requests.get, update._spawn = original_get, original_spawn
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
