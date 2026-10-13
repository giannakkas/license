"""Persistent configuration: the list of sources and the user's settings, as one JSON file."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def is_url(text: str) -> bool:
    return "://" in text and not text.lower().startswith("file://")


def guess_name(url: str) -> str:
    """A readable default name for a source: the file name, or the host of a stream."""
    if not is_url(url):
        base = os.path.basename(url.replace("\\", "/").rstrip("/"))
        return os.path.splitext(base)[0] or url
    parsed = urlparse(url)
    host = parsed.hostname or url
    tail = os.path.basename(parsed.path.rstrip("/"))
    if tail and tail.lower() not in ("index.m3u8", "playlist.m3u8", "stream", "live"):
        return f"{host} / {os.path.splitext(tail)[0]}"
    return host


@dataclass
class Source:
    name: str
    url: str
    loop: bool = False            # loop a file when it reaches the end
    silence_alarm: bool = True    # raise the SILENCE alarm on this source

    @property
    def is_stream(self) -> bool:
        return is_url(self.url)

    def display_name(self) -> str:
        return self.name.strip() or guess_name(self.url)


@dataclass
class Settings:
    silence_threshold_db: float = -50.0   # loudest channel under this counts as silent
    silence_seconds: float = 10.0         # how long silence must last before alarming
    stall_seconds: float = 15.0           # no playback progress for this long -> reconnect
    beep_on_alarm: bool = False
    show_loudness: bool = True            # EBU R128 momentary / short-term readout
    volume: int = 100
    audio_device: str = "auto"
    hwdec: bool = True                    # hardware video decoding
    meter_release_db_s: float = 20.0
    peak_hold_s: float = 1.5
    reconnect: bool = True


def _from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


@dataclass
class Config:
    sources: list[Source] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)
    audible: int = 0            # index of the tile whose audio is heard; -1 for none
    mute_all: bool = False
    geometry: str = ""          # window geometry, base64 (opaque Qt blob)
    layout_columns: int = 0     # 0 = automatic

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("config %s unreadable (%s); starting with defaults", path, exc)
            try:
                Path(path).replace(Path(path).with_suffix(".bad.json"))
            except OSError:
                pass
            return cls()
        cfg = cls()
        cfg.sources = [_from_dict(Source, s) for s in raw.get("sources", [])
                       if isinstance(s, dict) and str(s.get("url", "")).strip()]
        cfg.settings = _from_dict(Settings, raw.get("settings", {}))
        cfg.audible = int(raw.get("audible", 0))
        cfg.mute_all = bool(raw.get("mute_all", False))
        cfg.geometry = str(raw.get("geometry", ""))
        cfg.layout_columns = int(raw.get("layout_columns", 0))
        return cfg

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "BarpiMonitor"


def default_config_path() -> Path:
    return default_config_dir() / "config.json"
