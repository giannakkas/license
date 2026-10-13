import json
import time

import pytest

from barpi_monitor.license import (OFFLINE_GRACE_S, USABLE, LicenseClient, LicenseError, LicenseState, ServerUnreachable,
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


# ---------------------------------------------------------------- offline licence files

import base64

from barpi_monitor import license as L

# Signed by Node's crypto.sign("sha256") with a throwaway RSA-2048 key: the platform's signer.
NODE_N = ("-aT1s-VJ1dIzR2ZAG30eeOeg7zRbzkKkZO6S_NequI6mEKHr2uX0kC3H3SgyQB-Yfq2-2CsnNURrnbSUEKKfB1JhRKoDn_YNWE7GnFoy9EEgOi5"
          "yzfElQMZQfCepQkBCNOEpjNOTJKhRrUkOmqTzIewCZkv63ViuOsUhQdbpW2dAd0tmSS4L4Zt2BTbofo4eKtxcTHktnibQLtZT6jrVxiISuH4Fiyi"
          "KNtmrhF-_nYDBRtDkStuzHnOM0ThH2YN1jH759LAdTw2ryqd_G3vgqVRNFrvn_XfDklLt6iV_GrlIFEKBt0IpFslLGVgajq01Gp7kX0HEfU13-yX"
          "72QFSLQ")
NODE_PAYLOAD = ("eyJ2IjoxLCJrZXkiOiJPTkNVRS1BQkNERS1GR0hJSi1LTE1OTy1QUVJTVCIsInByb2R1Y3QiOiJtb25pdG9yaW5nLWFwcGxpY2F0aW9uIiwi"
                "cHJvZHVjdF9uYW1lIjoiTW9uaXRvcmluZyBBcHBsaWNhdGlvbiIsImN1c3RvbWVyIjoiRGVsdGEgRk0iLCJsYWJlbCI6IlN0dWRpbyAyIiwi"
                "bWFjaGluZV9pZCI6IkFCQ0RFRjAxMjM0NTY3ODlBQkNEIiwiaXNzdWVkX2F0IjoiMjAyNi0xMC0xM1QyMDowMDowMFoiLCJleHBpcmVzX2F0"
                "IjoiMjAyNy0xMC0xM1QyMzo1OTo1OVoiLCJzZXJ2ZXIiOiJodHRwczovL3BsYXllci5vbmN1ZS5jeSIsImludGVydmFsIjozMDB9")
NODE_SIG = ("u_U5-IxTiF_4CybU8LaVYKtNGS0_ojubkJeJBqlm_afiC8St2APuo9S8n8hQUiUngLYU-B42bXXkelCnWEkMut_TMulBYbnv8c8cXxNZhRNAwYTF"
            "VHj3Y2kSLk-BxIirlIqzwA8E8TYsvPpO5wfbx7acU_S-dXIHbwNR49EaZafEVOvGNrRbyUH4GbNm0Sdv_SrVXczdVwLFzqt5Ae44IAY6eRD8jMwV"
            "rV9KZHn6EipbJLUKGOS9IQ4o4v1YQ3ZL0skDiJtYipdhyIo_wYXrGemf_7g-OSOWVws7wjvLSK3rxY2GvTrFkedp47ESQzeZ7EcgbI1dIThGow_Q"
            "fi_5CQ")


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def write_lic(path, payload_b64: str, signature: str):
    path.write_text(json.dumps({"format": "oncue-licence/1", "payload": payload_b64, "signature": signature}))
    return path


def test_node_signed_file_verifies_and_tampering_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "PUBLIC_KEY_N", NODE_N)
    payload, sig = L.read_license_file(write_lic(tmp_path / "ok.lic", NODE_PAYLOAD, NODE_SIG))
    assert payload["key"] == KEY and payload["machine_id"] == "ABCDEF0123456789ABCD" and sig == NODE_SIG
    tampered = json.loads(L.b64url_decode(NODE_PAYLOAD))
    tampered["expires_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(LicenseError):
        L.read_license_file(write_lic(tmp_path / "bad.lic", b64u(json.dumps(tampered).encode()), NODE_SIG))
    with pytest.raises(LicenseError):
        L.read_license_file(write_lic(tmp_path / "sig.lic", NODE_PAYLOAD, NODE_SIG[:-4] + "AAAA"))
    monkeypatch.setattr(L, "PUBLIC_KEY_N", L.PUBLIC_KEY_N if L.PUBLIC_KEY_N != NODE_N else "AQAB")
    with pytest.raises(LicenseError, match="signature"):
        L.read_license_file(write_lic(tmp_path / "other.lic", NODE_PAYLOAD, NODE_SIG))
    (tmp_path / "junk.lic").write_text("{\"format\": \"something-else\"}")
    with pytest.raises(LicenseError, match="not an OnCue"):
        L.read_license_file(tmp_path / "junk.lic")


@pytest.fixture
def signer(monkeypatch):
    """A throwaway platform key: files signed with it verify because the public modulus is patched in."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = priv.public_key().public_numbers().n
    monkeypatch.setattr(L, "PUBLIC_KEY_N", b64u(n.to_bytes((n.bit_length() + 7) // 8, "big")))

    def make(path, machine, **overrides):
        payload = {"v": 1, "license_id": "lic1", "system_id": "sys1", "key": KEY, "product": "monitoring-application",
                   "product_name": "Monitoring Application", "customer": "Delta FM", "label": "Studio 2",
                   "machine_id": machine, "hostname": "PC-1", "issued_at": "2026-10-13T20:00:00Z",
                   "expires_at": "2099-01-01T23:59:59Z", "server": "https://platform.test", "interval": 120}
        payload.update(overrides)
        data = json.dumps(payload).encode()
        sig = priv.sign(data, padding.PKCS1v15(), hashes.SHA256())
        return write_lic(path, b64u(data), b64u(sig))

    return make


def test_import_file_activates_offline(client, tmp_path, signer):
    c, server = client
    path = signer(tmp_path / "a.lic", c.state.machine_id)
    st = c.import_file(path)
    assert st.mode == L.MODE_OFFLINE and st.status == Status.ACTIVE and c.usable()
    assert st.key == KEY and st.label == "Delta FM – Studio 2" and st.file_expires_at.startswith("2099")
    assert st.interval_s == 120 and st.server == "https://platform.test"
    assert st.token == json.loads(path.read_text())["signature"], "the signature doubles as the check-in token"
    assert LicenseClient(tmp_path / "license.json", post=server).usable()
    # No internet at all: no grace period applies, the file carries the licence.
    server.down = True
    c.check()
    assert c.state.last_error
    assert c.effective_status(now=time.time() + OFFLINE_GRACE_S * 10)[0] == Status.ACTIVE
    # A connection that does get through still lets the platform lock or revoke the computer.
    server.down = False
    server.answer = (200, {"status": "locked", "message": "Unpaid invoice"})
    assert c.check().status == Status.LOCKED and not c.usable()
    assert server.calls[-1][0] == "heartbeat" and server.calls[-1][1]["token"] == st.token
    server.answer = (200, {"status": "active", "label": "Delta FM – Studio 2"})
    assert c.check().status == Status.ACTIVE and c.usable()
    server.answer = (403, {"status": "revoked", "message": "Licence revoked"})
    assert c.check().status == Status.REVOKED and c.effective_status()[0] in L.NEEDS_ACTIVATION


def test_offline_file_expiry_and_clock_guard(client, tmp_path, signer):
    c, _ = client
    c.import_file(signer(tmp_path / "a.lic", c.state.machine_id, expires_at="2030-06-30T23:59:59Z"))
    expires = L.parse_iso("2030-06-30T23:59:59Z")
    assert c.effective_status(now=expires - 60)[0] == Status.ACTIVE
    status, message = c.effective_status(now=expires + 60)
    assert status == Status.EXPIRED and "2030-06-30" in message and status in L.NEEDS_ACTIVATION
    now = time.time()
    c.tick(now=now)
    assert c.effective_status(now=now - L.CLOCK_TOLERANCE_S + 60)[0] == Status.ACTIVE, "a small step back is tolerated"
    status, message = c.effective_status(now=now - 2 * L.CLOCK_TOLERANCE_S)
    assert status == Status.CLOCK and "clock" in message.lower() and not status in USABLE
    assert c.effective_status(now=now + 10)[0] == Status.ACTIVE, "works again once the clock is right"
    assert LicenseState.load(tmp_path / "license.json").clock_mark >= now - 1, "the mark is saved"


def test_import_file_rejections(client, tmp_path, signer):
    c, _ = client
    with pytest.raises(LicenseError, match="this computer is"):
        c.import_file(signer(tmp_path / "other.lic", "ZZZZZZZZZZZZZZZZZZZZ"))
    with pytest.raises(LicenseError, match="not for this program"):
        c.import_file(signer(tmp_path / "prod.lic", c.state.machine_id, product="playout-server", product_name="Playout Server"))
    with pytest.raises(LicenseError, match="expired on 2020-01-01"):
        c.import_file(signer(tmp_path / "old.lic", c.state.machine_id, expires_at="2020-01-01T23:59:59Z"))
    assert c.state.status == Status.UNLICENSED and not c.usable()
    # Going back to a key puts the computer in online mode again.
    c.import_file(signer(tmp_path / "ok.lic", c.state.machine_id))
    c.activate(KEY)
    assert c.state.mode == L.MODE_ONLINE and c.state.file_expires_at == ""
