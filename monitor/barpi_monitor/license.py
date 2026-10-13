"""Serial-key licensing: activation, periodic check-ins and remote lock.

The program is tied to a licence key on the licensing platform (license.oncue.cy). On first
start the operator enters the key; the platform records this machine against it and hands
back an activation token. From then on the program checks in every few minutes and the
platform can answer *locked* (the operator sees a lock screen and playback stops), *revoked*
or *expired*. If the platform cannot be reached the last answer stays valid for a grace
period, after which the program locks itself until it can check in again.

Computers without internet use an *offline licence file* instead: the platform issues a
file signed with its RSA key for one computer id, one software and an expiry date; the
program verifies the signature with the public key below and needs no server. If such a
computer does get a connection it checks in like the others, so a lock or revoke reaches
it then. The file's expiry is enforced by the computer's clock, so setting the clock back
to before the program last ran locks it until the clock is right again.

This module has no Qt in it so it can be unit-tested against a fake server.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import platform
import socket
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_SERVER = "https://license.oncue.cy"
# Earlier builds pointed at these; a saved state naming one is moved to DEFAULT_SERVER on load.
LEGACY_SERVERS = {"https://player.oncue.cy"}
PRODUCT = "monitoring-application"
DEFAULT_INTERVAL_S = 300          # check-in period unless the server says otherwise
OFFLINE_GRACE_S = 72 * 3600       # how long the last good answer stays valid without a server
HTTP_TIMEOUT_S = 12

MODE_ONLINE = "online"            # activated with a key, checked with the platform
MODE_OFFLINE = "offline"          # activated with a signed licence file
FILE_FORMAT = "oncue-licence/1"
CLOCK_TOLERANCE_S = 3600          # how far back the clock may go before an offline file stops working

# The licensing platform's RSA-2048 public key (modulus, base64url; exponent 65537). Offline
# licence files carry a PKCS#1 v1.5 / SHA-256 signature over their payload made with the
# matching private key, which only the platform holds.
PUBLIC_KEY_N = ("3uGaZXqcTQ8VUntrn3OWi0Fcct6cQ59hDn7lWURABchOLKpAoK_I7YVFRYpWXyX_O2XVj9qNy4TKysdjCjFdk2ZB5FhG1N4f2OOJ"
                "3uJs21Xs81S9qvCAvD6Si3Xvfk-XlKiypYDHQpapn-xbkpEl8t1vcHGk15Svova_MyZ2NqOKJcvTTaIMMnLCOyjuoTdlzAHlFv3W"
                "XOze786pGuSDFU6HV03VXms4Hin4hBxrQe3fJqzVa68v38_3Q-yk60tmYKQr91OKguP2uKP0vIqCBdcJdUC2EEmTwuqRt1bZZOXe"
                "0zC00wbxaawfKFsSr_zVQapYuuqLkihgLsivIkwUZw")
PUBLIC_KEY_E = 65537
_DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


class Status:
    UNLICENSED = "unlicensed"   # no key entered yet
    ACTIVE = "active"
    LOCKED = "locked"           # the platform locked this system or its licence
    REVOKED = "revoked"
    EXPIRED = "expired"
    UNKNOWN = "unknown"         # the platform no longer knows this machine: activate again
    OFFLINE = "offline"         # unreachable for longer than the grace period
    CLOCK = "clock"             # offline file: the clock was set back to before the last run


# Statuses in which the program may run.
USABLE = {Status.ACTIVE}
# Statuses that need a fresh activation rather than a check-in.
NEEDS_ACTIVATION = {Status.UNLICENSED, Status.UNKNOWN, Status.REVOKED, Status.EXPIRED}


class LicenseError(Exception):
    """A definitive answer from the platform (wrong key, locked, no seats...)."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class ServerUnreachable(Exception):
    pass


def machine_id() -> str:
    """A stable, anonymous identifier for this computer (hash of the OS install id and host name)."""
    parts = [socket.gethostname()]
    if sys.platform == "win32":
        try:
            import winreg  # noqa: WPS433
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                parts.append(str(winreg.QueryValueEx(k, "MachineGuid")[0]))
        except OSError:
            parts.append(f"{uuid.getnode():012x}")
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                parts.append(Path(p).read_text().strip())
                break
            except OSError:
                continue
        else:
            parts.append(f"{uuid.getnode():012x}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20].upper()


def machine_info() -> dict:
    return {
        "hostname": socket.gethostname()[:80],
        "os": f"{platform.system()} {platform.release()}"[:80],
        "version": __version__,
        "product": PRODUCT,
    }


def normalise_key(text: str) -> str:
    """Upper-case, keep only letters and digits, re-group as XXXXX-XXXXX-XXXXX-XXXXX."""
    raw = "".join(ch for ch in text.upper() if ch.isalnum())
    if raw.startswith("ONCUE"):
        raw = raw[5:]
    groups = [raw[i:i + 5] for i in range(0, len(raw), 5)]
    return "ONCUE-" + "-".join(groups) if raw else ""


@dataclass
class LicenseState:
    key: str = ""
    token: str = ""
    machine_id: str = ""
    status: str = Status.UNLICENSED
    message: str = ""
    label: str = ""
    expires_at: str = ""
    server: str = DEFAULT_SERVER
    interval_s: int = DEFAULT_INTERVAL_S
    last_ok: float = 0.0        # epoch of the last answer that allowed running
    last_check: float = 0.0     # epoch of the last attempt
    last_error: str = ""
    mode: str = MODE_ONLINE
    file_issued_at: str = ""    # offline file: when the platform issued it
    file_expires_at: str = ""   # offline file: when it stops working
    clock_mark: float = 0.0     # the latest clock reading seen; guards against setting the clock back

    @classmethod
    def load(cls, path: Path) -> "LicenseState":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        state = cls(**{k: v for k, v in raw.items() if k in names})
        if not state.server or state.server.rstrip("/") in LEGACY_SERVERS:
            state.server = DEFAULT_SERVER
        return state

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)


def _post_json(url: str, payload: dict, timeout: float = HTTP_TIMEOUT_S) -> tuple[int, dict]:
    """POST JSON, return (http status, decoded body). Network failures raise ServerUnreachable."""
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"{PRODUCT}/{__version__}",
    })
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode(resp.read())
    except error.HTTPError as exc:
        body = _decode(exc.read())
        if exc.code >= 500 or not body:
            raise ServerUnreachable(f"server error {exc.code}") from exc
        return exc.code, body
    except (error.URLError, socket.timeout, OSError, ValueError) as exc:
        raise ServerUnreachable(str(getattr(exc, "reason", exc))) from exc


def _decode(raw: bytes) -> dict:
    try:
        body = json.loads(raw.decode("utf-8"))
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


# ------------------------------------------------------------------ offline licence files

def b64url_decode(text: str) -> bytes:
    text = "".join(str(text).split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def rsa_verify_sha256(signature: bytes, data: bytes, n_b64url: str = PUBLIC_KEY_N, e: int = PUBLIC_KEY_E) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256: rebuild the padded block and compare it whole (RFC 8017 §8.2.2)."""
    try:
        n = int.from_bytes(b64url_decode(n_b64url), "big")
    except ValueError:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest_info = _DIGEST_INFO_SHA256 + hashlib.sha256(data).digest()
    if k < len(digest_info) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    return hmac.compare_digest(em, expected)


def parse_iso(text: str) -> float | None:
    """'2027-10-13T23:59:59Z' -> epoch seconds, or None."""
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def read_license_file(path: Path, n_b64url: str | None = None) -> tuple[dict, str]:
    """Parse and verify a .lic file. Returns (payload, signature) or raises LicenseError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LicenseError("invalid", f"The file could not be read as a licence file ({exc}).") from exc
    if not isinstance(raw, dict) or raw.get("format") != FILE_FORMAT:
        raise LicenseError("invalid", "This is not an OnCue licence file.")
    try:
        payload_bytes = b64url_decode(raw.get("payload", ""))
        signature = str(raw.get("signature", ""))
        sig_bytes = b64url_decode(signature)
    except (ValueError, TypeError) as exc:
        raise LicenseError("invalid", "The licence file is damaged.") from exc
    if not rsa_verify_sha256(sig_bytes, payload_bytes, n_b64url or PUBLIC_KEY_N):
        raise LicenseError("invalid", "The licence file's signature is not valid. Ask for a new file.")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except ValueError as exc:
        raise LicenseError("invalid", "The licence file is damaged.") from exc
    if not isinstance(payload, dict):
        raise LicenseError("invalid", "The licence file is damaged.")
    return payload, signature


class LicenseClient:
    """Talks to the platform and keeps ``license.json`` in the config folder up to date."""

    def __init__(self, path: Path, server: str | None = None, post=_post_json):
        self.path = Path(path)
        self.state = LicenseState.load(self.path)
        if server:
            self.state.server = server.rstrip("/")
        if not self.state.machine_id:
            self.state.machine_id = machine_id()
        self._post = post
        self._saved_mark = self.state.clock_mark

    # ----------------------------------------------------------------- queries

    @property
    def status(self) -> str:
        return self.state.status

    def effective_status(self, now: float | None = None) -> tuple[str, str]:
        """The status to act on right now: the stored one, aged by the offline grace rule.

        With an offline file there is no grace rule: the file works until its expiry unless a
        check-in that did get through said otherwise, or the clock was set back.
        """
        now = time.time() if now is None else now
        st = self.state
        if st.mode == MODE_OFFLINE:
            if st.status != Status.ACTIVE:
                return st.status, st.message
            if st.clock_mark and now < st.clock_mark - CLOCK_TOLERANCE_S:
                return Status.CLOCK, ("This computer's clock is set to before the program last ran. Set the correct "
                                      "date and time; the licence file works again once the clock is right.")
            expires = parse_iso(st.file_expires_at)
            if expires is not None and now > expires:
                return Status.EXPIRED, (f"The offline licence file expired on {st.file_expires_at[:10]}. "
                                        f"Ask for a new file for computer {st.machine_id}.")
            return Status.ACTIVE, ""
        if st.status == Status.ACTIVE and st.last_check > st.last_ok and st.last_error:
            if now - st.last_ok > OFFLINE_GRACE_S:
                days = OFFLINE_GRACE_S // 86400
                return Status.OFFLINE, f"The licence server could not be reached for {days} days ({st.last_error})."
        return st.status, st.message

    def usable(self) -> bool:
        return self.effective_status()[0] in USABLE

    def tick(self, now: float | None = None) -> None:
        """Remember the latest clock reading (saved every few minutes) for the set-back guard."""
        now = time.time() if now is None else now
        st = self.state
        if now > st.clock_mark:
            st.clock_mark = now
            if now - self._saved_mark >= 300:
                self._saved_mark = now
                self.save()

    # ----------------------------------------------------------------- actions

    def activate(self, key: str) -> LicenseState:
        key = normalise_key(key)
        if len(key) != len("ONCUE-XXXXX-XXXXX-XXXXX-XXXXX"):
            raise LicenseError("invalid", "A key looks like ONCUE-XXXXX-XXXXX-XXXXX-XXXXX.")
        payload = {**machine_info(), "key": key, "machine_id": self.state.machine_id}
        code, body = self._post(f"{self.state.server}/api/v1/activate", payload)
        self.state.last_check = time.time()
        status = str(body.get("status", ""))
        message = str(body.get("message", ""))
        if code == 200 and status == Status.ACTIVE and body.get("token"):
            self._apply(body, key=key, token=str(body["token"]))
            self.state.mode = MODE_ONLINE
            self.state.file_issued_at = self.state.file_expires_at = ""
            self.state.last_ok = self.state.last_check
            self.state.last_error = ""
            self.save()
            return self.state
        raise LicenseError(status or "invalid", message or f"Activation refused (HTTP {code}).")

    def import_file(self, path: Path, now: float | None = None) -> LicenseState:
        """Activate from an offline licence file issued by the platform for this computer."""
        now = time.time() if now is None else now
        payload, signature = read_license_file(path)
        st = self.state
        product = str(payload.get("product", ""))
        if product != PRODUCT:
            raise LicenseError("invalid", f"This file is for {payload.get('product_name') or product or 'another program'}, "
                                          f"not for this program.")
        wanted = str(payload.get("machine_id", "")).upper()
        if wanted != st.machine_id:
            raise LicenseError("invalid", f"This file was issued for computer {wanted or '?'}; this computer is "
                                          f"{st.machine_id}. Ask for a file for this id.")
        expires_at = str(payload.get("expires_at", ""))
        expires = parse_iso(expires_at)
        if expires is None:
            raise LicenseError("invalid", "The licence file has no valid expiry date.")
        if now > expires:
            raise LicenseError("expired", f"This licence file expired on {expires_at[:10]}. Ask for a new file.")
        key = normalise_key(str(payload.get("key", "")))
        if len(key) != len("ONCUE-XXXXX-XXXXX-XXXXX-XXXXX"):
            raise LicenseError("invalid", "The licence file carries no valid key.")
        customer = str(payload.get("customer", "") or "")
        label = str(payload.get("label", "") or "")
        st.key = key
        st.token = signature
        st.mode = MODE_OFFLINE
        st.status = Status.ACTIVE
        st.message = ""
        st.label = f"{customer} – {label}" if customer and label else (customer or label)
        st.expires_at = expires_at
        st.file_issued_at = str(payload.get("issued_at", "") or "")
        st.file_expires_at = expires_at
        if payload.get("server"):
            st.server = str(payload["server"]).rstrip("/")
        try:
            st.interval_s = max(30, int(payload.get("interval", st.interval_s)))
        except (TypeError, ValueError):
            pass
        st.last_ok = st.last_check = now
        st.last_error = ""
        st.clock_mark = max(st.clock_mark, now)
        self.save()
        return st

    def check(self) -> LicenseState:
        """One check-in. Never raises for network trouble: that is recorded and aged by the grace rule."""
        st = self.state
        if not st.key or not st.token:
            st.status = Status.UNLICENSED
            return st
        payload = {**machine_info(), "key": st.key, "machine_id": st.machine_id, "token": st.token}
        try:
            code, body = self._post(f"{st.server}/api/v1/heartbeat", payload)
        except ServerUnreachable as exc:
            st.last_check = time.time()
            st.last_error = str(exc)[:200]
            # Expected for a computer on an offline file; worth a warning otherwise.
            log.log(logging.DEBUG if st.mode == MODE_OFFLINE else logging.WARNING, "licence check-in failed: %s", exc)
            self.save()
            return st
        st.last_check = time.time()
        st.last_error = ""
        status = str(body.get("status", ""))
        if code == 200 and status in (Status.ACTIVE, Status.LOCKED):
            self._apply(body)
            if status == Status.ACTIVE:
                st.last_ok = st.last_check
        elif status in (Status.REVOKED, Status.EXPIRED, Status.UNKNOWN, "invalid"):
            st.status = Status.UNKNOWN if status == "invalid" else status
            st.message = str(body.get("message", "")) or f"The licence is {st.status}."
            st.token = ""
        else:
            # An answer we do not understand is treated like an outage, not a verdict.
            st.last_error = f"unexpected answer (HTTP {code})"
        self.save()
        return st

    def deactivate(self) -> None:
        st = self.state
        if st.key and st.token:
            try:
                self._post(f"{st.server}/api/v1/deactivate",
                           {"key": st.key, "machine_id": st.machine_id, "token": st.token, "product": PRODUCT})
            except ServerUnreachable as exc:
                log.warning("deactivate could not reach the server: %s", exc)
        self.state = LicenseState(machine_id=st.machine_id, server=st.server)
        self.save()

    # ----------------------------------------------------------------- helpers

    def _apply(self, body: dict, key: str | None = None, token: str | None = None) -> None:
        st = self.state
        if key:
            st.key = key
        if token:
            st.token = token
        st.status = str(body.get("status", st.status))
        st.message = str(body.get("message", "") or "")
        st.label = str(body.get("label", "") or "")
        st.expires_at = str(body.get("expires_at", "") or "")
        try:
            st.interval_s = max(30, int(body.get("interval", st.interval_s)))
        except (TypeError, ValueError):
            pass

    def save(self) -> None:
        try:
            self.state.save(self.path)
        except OSError as exc:
            log.warning("could not save licence state: %s", exc)


def license_path(config_dir: Path) -> Path:
    return Path(config_dir) / "license.json"


def server_override() -> str | None:
    """``BARPI_LICENSE_SERVER`` lets a test or a staging platform stand in for license.oncue.cy."""
    return os.environ.get("BARPI_LICENSE_SERVER") or None
