import json
import time

import pytest

from barpi_monitor.license import (OFFLINE_GRACE_S, LicenseClient, LicenseError, LicenseState, ServerUnreachable,
                                   Status, machine_id, normalise_key)

KEY = "ONCUE-ABCDE-FGHIJ-KLMNO-PQRST"


class FakeServer:
    """Stands in for the platform: records calls, answers from a script."""

    def __init__(self):
        self.calls = []
        self.answer = (200, {"status": "active", "token": "tok", "interval": 60, "label": "Newsroom"})
        self.down = False

    def __call__(self, url, payload, timeout=0):
        self.calls.append((url.rsplit("/", 1)[-1], payload))
        if self.down:
            raise ServerUnreachable("connection refused")
        return self.answer


@pytest.fixture
def client(tmp_path):
    server = FakeServer()
    c = LicenseClient(tmp_path / "license.json", server="https://platform.test", post=server)
    return c, server


def test_normalise_key():
    assert normalise_key("abcde fghij-klmno_pqrst") == KEY
    assert normalise_key("oncue-ABCDE-FGHIJ-KLMNO-PQRST") == KEY
    assert normalise_key("") == ""


def test_machine_id_is_stable_and_anonymous():
    a, b = machine_id(), machine_id()
    assert a == b and len(a) == 20 and a.isalnum()


def test_activate_success_persists(client, tmp_path):
    c, server = client
    st = c.activate("abcde-fghij-klmno-pqrst")
    assert st.status == Status.ACTIVE and st.token == "tok" and st.label == "Newsroom" and st.interval_s == 60
    kind, payload = server.calls[0]
    assert kind == "activate" and payload["key"] == KEY and payload["machine_id"] == c.state.machine_id
    assert payload["product"] == "monitoring-application" and payload["hostname"]
    saved = json.loads((tmp_path / "license.json").read_text())
    assert saved["key"] == KEY and saved["status"] == "active"
    assert LicenseClient(tmp_path / "license.json", post=server).usable()


def test_activate_refused(client):
    c, server = client
    server.answer = (403, {"status": "no_seats", "message": "All 1 seats are in use"})
    with pytest.raises(LicenseError) as exc:
        c.activate(KEY)
    assert exc.value.status == "no_seats" and "seats" in exc.value.message
    assert c.state.status == Status.UNLICENSED and not c.usable()


def test_activate_bad_format(client):
    c, _ = client
    with pytest.raises(LicenseError):
        c.activate("short")


def test_heartbeat_lock_and_unlock(client):
    c, server = client
    c.activate(KEY)
    server.answer = (200, {"status": "locked", "message": "Unpaid invoice"})
    st = c.check()
    assert st.status == Status.LOCKED and st.message == "Unpaid invoice" and not c.usable()
    assert server.calls[-1][0] == "heartbeat" and server.calls[-1][1]["token"] == "tok"
    server.answer = (200, {"status": "active", "token": "tok", "interval": 120})
    assert c.check().status == Status.ACTIVE and c.usable() and c.state.interval_s == 120


def test_heartbeat_revoked_needs_reactivation(client):
    c, server = client
    c.activate(KEY)
    server.answer = (403, {"status": "revoked", "message": "Licence revoked"})
    st = c.check()
    assert st.status == Status.REVOKED and st.token == "" and not c.usable()


def test_heartbeat_unknown_machine(client):
    c, server = client
    c.activate(KEY)
    server.answer = (404, {"status": "unknown", "message": "This system was removed"})
    assert c.check().status == Status.UNKNOWN


def test_offline_grace(client):
    c, server = client
    c.activate(KEY)
    server.down = True
    st = c.check()
    assert st.status == Status.ACTIVE and st.last_error and c.usable(), "within the grace period the last answer holds"
    later = time.time() + OFFLINE_GRACE_S + 60
    status, message = c.effective_status(now=later)
    assert status == Status.OFFLINE and "could not be reached" in message
    server.down = False
    server.answer = (200, {"status": "active", "token": "tok"})
    c.check()
    assert c.effective_status(now=later)[0] == Status.ACTIVE


def test_server_error_is_an_outage_not_a_verdict(client):
    c, server = client
    c.activate(KEY)
    server.answer = (502, {})
    st = c.check()
    assert st.status == Status.ACTIVE and st.last_error


def test_deactivate(client, tmp_path):
    c, server = client
    c.activate(KEY)
    c.deactivate()
    assert server.calls[-1][0] == "deactivate"
    assert c.state.status == Status.UNLICENSED and c.state.key == ""
    assert LicenseState.load(tmp_path / "license.json").key == ""
