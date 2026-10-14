import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from barpi_monitor import updater
from barpi_monitor.license import LicenseClient, ServerUnreachable, is_newer, version_tuple

KEY = "ONCUE-ABCDE-FGHIJ-KLMNO-PQRST"


def test_version_compare():
    assert version_tuple("1.4.0") == (1, 4, 0) and version_tuple("v2") == (2,) and version_tuple("") == (0,)
    assert is_newer("1.4.0", "1.3.2") and is_newer("1.10", "1.9.9") and is_newer("2", "1.99")
    assert not is_newer("1.4", "1.4.0") and not is_newer("1.3.2", "1.4.0") and not is_newer("1.4.0", "1.4.0")


class Server:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, url, payload, timeout=0):
        self.calls.append((url.rsplit("/", 1)[-1], payload))
        return self.answer


def make_client(tmp_path, answer):
    server = Server(answer)
    c = LicenseClient(tmp_path / "license.json", server="https://platform.test", post=server)
    return c, server


LATEST = {"version": "9.1.0", "url": "/download/monitoring-application/rel1", "sha256": "ab" * 32,
          "size": 1234, "notes": "Faster meters"}


def test_offer_from_check_in(tmp_path):
    c, server = make_client(tmp_path, (200, {"status": "active", "token": "tok", "latest": LATEST, "min_version": None}))
    c.activate(KEY)
    offer = c.update_offer(current="1.4.0")
    assert offer == {"version": "9.1.0", "url": "https://platform.test/download/monitoring-application/rel1",
                     "sha256": "ab" * 32, "size": 1234, "notes": "Faster meters", "required": False}
    assert c.update_offer(current="9.1.0") is None, "nothing to offer when already on that version"
    server.answer = (200, {"status": "active", "latest": {**LATEST, "url": "https://cdn.test/x.exe"}, "min_version": "9.0"})
    c.check()
    offer = c.update_offer(current="1.4.0")
    assert offer["required"] and offer["url"] == "https://cdn.test/x.exe", "absolute URLs are kept"
    assert not c.update_offer(current="9.0.5")["required"], "at or above the minimum it is optional"
    # Persisted, so the offer survives a restart without internet.
    again = LicenseClient(tmp_path / "license.json", post=server)
    assert again.update_offer(current="1.4.0")["version"] == "9.1.0"
    # The platform removed every build: nothing offered any more.
    server.answer = (200, {"status": "active", "latest": None, "min_version": None})
    c.check()
    assert c.update_offer(current="1.4.0") is None
    # An old platform that sends neither key leaves what we knew untouched.
    server.answer = (200, {"status": "active", "latest": LATEST})
    c.check()
    server.answer = (200, {"status": "active"})
    c.check()
    assert c.update_offer(current="1.4.0")["version"] == "9.1.0"
    # Offline: no check-in arrives, the stored offer stays.
    c._post = lambda *a, **k: (_ for _ in ()).throw(ServerUnreachable("down"))
    c.check()
    assert c.update_offer(current="1.4.0")["version"] == "9.1.0"


def test_mislabelled_build_is_not_offered_again(tmp_path):
    c, _ = make_client(tmp_path, (200, {"status": "active", "token": "tok", "latest": LATEST, "min_version": "9.1.0"}))
    c.activate(KEY)
    c.state.installed_update = "9.1.0"      # installed once, but the program still reports 1.4.0
    assert c.update_offer(current="1.4.0") is None
    c.state.update_version = "9.2.0"        # a newer upload is offered normally again
    assert c.update_offer(current="1.4.0")["version"] == "9.2.0"


@pytest.fixture
def web(tmp_path):
    """A real HTTP server on 127.0.0.1 serving files from tmp_path/www."""
    root = tmp_path / "www"
    root.mkdir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_verifies_size_and_checksum(tmp_path, web):
    root, base = web
    payload = bytes(range(256)) * 4000            # ~1 MB
    (root / "new.exe").write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    app = tmp_path / "app"
    app.mkdir()
    seen = []
    dest = updater.download(f"{base}/new.exe", app / "MonitoringApp.update", sha, len(payload),
                            progress=lambda got, total: seen.append((got, total)))
    assert dest.read_bytes() == payload and seen[-1] == (len(payload), len(payload))
    assert not (app / "MonitoringApp.update.part").exists()
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(f"{base}/new.exe", app / "bad.update", "00" * 32, len(payload))
    with pytest.raises(updater.UpdateError, match="stopped early"):
        updater.download(f"{base}/new.exe", app / "short.update", sha, len(payload) + 10)
    with pytest.raises(updater.UpdateError, match="HTTP 404"):
        updater.download(f"{base}/missing.exe", app / "missing.update", sha)
    with pytest.raises(updater.UpdateError, match="no checksum"):
        updater.download(f"{base}/new.exe", app / "nosum.update", "")
    assert sorted(p.name for p in app.iterdir()) == ["MonitoringApp.update"], "failed downloads leave nothing behind"


def test_install_swaps_and_cleanup_removes_the_old_build(tmp_path):
    exe = tmp_path / "MonitoringApp.exe"
    exe.write_bytes(b"old build")
    new = updater.staged_path(exe)
    new.write_bytes(b"new build")
    assert updater.install(new, exe) == "swapped"
    assert exe.read_bytes() == b"new build" and updater.old_path(exe).read_bytes() == b"old build"
    assert not new.exists()
    updater.cleanup(exe)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["MonitoringApp.exe"]


def test_install_puts_the_running_build_back_when_the_new_file_is_gone(tmp_path):
    exe = tmp_path / "MonitoringApp.exe"
    exe.write_bytes(b"old build")
    with pytest.raises(updater.UpdateError):
        updater.install(tmp_path / "does-not-exist.update", exe)
    assert exe.read_bytes() == b"old build"


def test_current_exe_is_none_from_source():
    assert updater.current_exe() is None
