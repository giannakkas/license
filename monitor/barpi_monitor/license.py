"""Serial-key licensing: activation, periodic check-ins and remote lock.

The program is tied to a licence key on the licensing platform (player.oncue.cy). On first
start the operator enters the key; the platform records this machine against it and hands
back an activation token. From then on the program checks in every few minutes and the
platform can answer *locked* (the operator sees a lock screen and playback stops), *revoked*
or *expired*. If the platform cannot be reached the last answer stays valid for a grace
period, after which the program locks itself until it can check in again.

This module has no Qt in it so it can be unit-tested against a fake server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import socket
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib import error, request

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_SERVER = "https://player.oncue.cy"
PRODUCT = "monitoring-application"
DEFAULT_INTERVAL_S = 300          # check-in period unless the server says otherwise
OFFLINE_GRACE_S = 72 * 3600       # how long the last good answer stays valid without a server
HTTP_TIMEOUT_S = 12


class Status:
    UNLICENSED = "unlicensed"   # no key entered yet
    ACTIVE = "active"
    LOCKED = "locked"           # the platform locked this system or its licence
    REVOKED = "revoked"
    EXPIRED = "expired"
    UNKNOWN = "unknown"         # the platform no longer knows this machine: activate again
    OFFLINE = "offline"         # unreachable for longer than the grace period


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

    @classmethod
    def load(cls, path: Path) -> "LicenseState":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        state = cls(**{k: v for k, v in raw.items() if k in names})
        if not state.server:
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

    # ----------------------------------------------------------------- queries

    @property
    def status(self) -> str:
        return self.state.status

    def effective_status(self, now: float | None = None) -> tuple[str, str]:
        """The status to act on right now: the stored one, aged by the offline grace rule."""
        now = time.time() if now is None else now
        st = self.state
        if st.status == Status.ACTIVE and st.last_check > st.last_ok and st.last_error:
            if now - st.last_ok > OFFLINE_GRACE_S:
                days = OFFLINE_GRACE_S // 86400
                return Status.OFFLINE, f"The licence server could not be reached for {days} days ({st.last_error})."
        return st.status, st.message

    def usable(self) -> bool:
        return self.effective_status()[0] in USABLE

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
            self.state.last_ok = self.state.last_check
            self.state.last_error = ""
            self.save()
            return self.state
        raise LicenseError(status or "invalid", message or f"Activation refused (HTTP {code}).")

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
            log.warning("licence check-in failed: %s", exc)
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
    """``BARPI_LICENSE_SERVER`` lets a test or a staging platform stand in for player.oncue.cy."""
    return os.environ.get("BARPI_LICENSE_SERVER") or None
