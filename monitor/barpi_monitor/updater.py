"""Self-update for the packaged exe.

The platform reports the newest build of this software on every check-in (version, download
URL, SHA-256, size). Installing one means: download it next to the running exe, refuse it
unless the size and SHA-256 match, swap it in and start it. Windows lets a running exe be
renamed (not deleted), so the running build moves aside to ``<name>.old.exe`` and the new one
takes its name; the old file is removed on the next start. If the rename is refused, a small
helper script finishes the swap once this process has exited.

No Qt in here, so it can be tested on its own.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib import error, request

from . import __version__

log = logging.getLogger(__name__)
CHUNK = 256 * 1024
DOWNLOAD_TIMEOUT_S = 30


class UpdateError(Exception):
    pass


def current_exe() -> Path | None:
    """The running exe, or None when running from source (nothing to replace then)."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def staged_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".update")


def old_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".old.exe")


def helper_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".update.cmd")


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def download(url: str, dest: Path, sha256: str, size: int = 0, progress=None, opener=None) -> Path:
    """Fetch ``url`` to ``dest``; only a file with the expected size and SHA-256 is kept."""
    if not sha256:
        raise UpdateError("The platform sent no checksum for this build, so it will not be installed.")
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    got = 0
    try:
        out = open(part, "wb")  # noqa: SIM115 - opened first so a read-only folder fails before downloading
    except OSError as exc:
        raise UpdateError(f"Cannot write in {dest.parent} ({exc.strerror or exc}). Move the program to a folder "
                          "you can write to, or download the update from the platform by hand.") from exc
    req = request.Request(url, headers={"User-Agent": f"monitoring-application/{__version__}"})
    log.info("downloading %s", url)
    next_log = 10 * 1024 * 1024
    try:
        with out, (opener or request.urlopen)(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
            total = int(resp.headers.get("Content-Length") or size or 0)
            log.info("download answered HTTP %s, %s bytes", getattr(resp, "status", "?"), total or "unknown")
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if got >= next_log:
                    log.info("downloaded %d of %d bytes", got, total)
                    next_log += 10 * 1024 * 1024
                if progress is not None:
                    progress(got, total)
    except error.HTTPError as exc:
        _remove(part)
        raise UpdateError(f"The platform refused the download (HTTP {exc.code}).") from exc
    except (error.URLError, OSError, ValueError) as exc:
        _remove(part)
        raise UpdateError(f"The download failed ({getattr(exc, 'reason', exc)}).") from exc
    if size and got != size:
        _remove(part)
        raise UpdateError(f"The download stopped early ({got} of {size} bytes). Try again.")
    if digest.hexdigest().lower() != sha256.lower():
        _remove(part)
        raise UpdateError("The downloaded file does not match the platform's checksum, so it was discarded.")
    os.replace(part, dest)
    log.info("download complete and verified (%d bytes)", got)
    return dest


def install(new_file: Path, exe: Path) -> str:
    """Put ``new_file`` in place of ``exe``. Returns "swapped", or "deferred" when a helper must finish after exit."""
    old = old_path(exe)
    _remove(old)
    try:
        os.replace(exe, old)
    except OSError as exc:
        log.info("could not move the running exe aside (%s); finishing the update after exit", exc)
        return "deferred"
    try:
        os.replace(new_file, exe)
    except OSError as exc:
        os.replace(old, exe)
        raise UpdateError(f"Could not put the new version in place ({exc}).") from exc
    return "swapped"


def _child_env() -> dict:
    env = dict(os.environ)
    # The new exe must start as a fresh PyInstaller program, not as a child of this one
    # (whose unpacked files disappear when this process exits).
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _detached_flags(no_window: bool = False) -> int:
    if sys.platform != "win32":
        return 0
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    return flags | (subprocess.CREATE_NO_WINDOW if no_window else subprocess.DETACHED_PROCESS)


def relaunch(exe: Path, args: list[str]) -> None:
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent), env=_child_env(), close_fds=True,
                     creationflags=_detached_flags())


def finish_after_exit(new_file: Path, exe: Path, args: list[str], pid: int | None = None) -> None:
    """Windows fallback: a script waits for this process to end, swaps the files and starts the new exe."""
    pid = os.getpid() if pid is None else pid
    quoted = " ".join(f'"{a}"' for a in args)
    script = helper_path(exe)
    script.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)\r\n'
        f'move /y "{new_file}" "{exe}" >nul\r\n'
        f'start "" "{exe}" {quoted}\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(script)], cwd=str(exe.parent), env=_child_env(), close_fds=True,
                     creationflags=_detached_flags(no_window=True))


def cleanup(exe: Path) -> None:
    """Remove what an earlier update left behind (the old exe may still be closing: then it stays until next time)."""
    for path in (old_path(exe), staged_path(exe), staged_path(exe).with_name(staged_path(exe).name + ".part")):
        _remove(path)
