"""Audio level maths with no Qt or mpv dependency, so it can be unit-tested on its own.

Everything is in dBFS (decibels relative to digital full scale, 0 dBFS = the loudest
possible sample). Silence is clamped to SILENCE_FLOOR rather than -inf so the arithmetic
stays finite.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

MIN_DB = -60.0          # bottom of the meter scale
MAX_DB = 0.0            # top of the meter scale
SILENCE_FLOOR = -120.0  # what "-inf" becomes
ALIGNMENT_DB = -18.0    # EBU alignment level: green/amber boundary
MAX_PERMITTED_DB = -9.0 # EBU maximum permitted level: amber/red boundary
OVER_DB = -0.3          # peaks at or above this count as clipping

_CH_RE = re.compile(r"^lavfi\.astats\.(\d+)\.(Peak_level|RMS_level)$")


def to_db(value) -> float:
    """Parse one metadata value (a string from the filter) into a finite dB figure."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return SILENCE_FLOOR
    if math.isnan(f) or f < SILENCE_FLOOR:
        return SILENCE_FLOOR
    return min(f, 20.0)


def parse_astats(meta) -> tuple[list[float], list[float]]:
    """Return (peaks, rms) per channel in dBFS from mpv's ``af-metadata/stats`` map."""
    peaks: dict[int, float] = {}
    rms: dict[int, float] = {}
    if not meta:
        return [], []
    for key, value in meta.items():
        m = _CH_RE.match(str(key))
        if not m:
            continue
        idx = int(m.group(1))
        (peaks if m.group(2) == "Peak_level" else rms)[idx] = to_db(value)
    chans = sorted(set(peaks) | set(rms))
    return ([peaks.get(c, SILENCE_FLOOR) for c in chans],
            [rms.get(c, SILENCE_FLOOR) for c in chans])


def parse_r128(meta) -> tuple[float, float]:
    """Return (momentary, short-term) loudness in LUFS from ``af-metadata/r128``."""
    if not meta:
        return SILENCE_FLOOR, SILENCE_FLOOR
    return to_db(meta.get("lavfi.r128.M")), to_db(meta.get("lavfi.r128.S"))


def channel_labels(count: int, layout: str | None = None) -> list[str]:
    """Short channel names for a meter with ``count`` bars."""
    layout = (layout or "").lower()
    table = {
        1: ["M"],
        2: ["L", "R"],
        3: ["L", "R", "LFE"] if "2.1" in layout else ["L", "R", "C"],
        4: ["L", "R", "Ls", "Rs"],
        5: ["L", "R", "C", "Ls", "Rs"],
        6: ["L", "R", "C", "LFE", "Ls", "Rs"],
        7: ["L", "R", "C", "LFE", "Ls", "Rs", "Cb"],
        8: ["L", "R", "C", "LFE", "Ls", "Rs", "Lb", "Rb"],
    }
    return table.get(count) or [str(i + 1) for i in range(count)]


def format_db(value: float, digits: int = 1) -> str:
    if value <= SILENCE_FLOOR + 1:
        return "-inf"
    return f"{value:.{digits}f}"


@dataclass
class ChannelState:
    peak: float = SILENCE_FLOOR   # displayed peak (instant attack, timed release)
    rms: float = SILENCE_FLOOR    # displayed RMS (smoothed both ways)
    hold: float = SILENCE_FLOOR   # peak-hold marker
    hold_age: float = 0.0


class MeterBallistics:
    """Turns raw per-frame levels into what a PPM-style meter should display.

    Peaks rise instantly and fall at ``release_db_per_s``. The peak-hold marker sits at
    the highest recent peak for ``hold_seconds`` and then falls at the same rate. RMS is
    exponentially smoothed with a short time constant so it reads like a VU bar.
    """

    def __init__(self, release_db_per_s: float = 20.0, hold_seconds: float = 1.5,
                 rms_tau: float = 0.25):
        self.release = float(release_db_per_s)
        self.hold_seconds = float(hold_seconds)
        self.rms_tau = float(rms_tau)
        self.channels: list[ChannelState] = []

    def _resize(self, n: int) -> None:
        if len(self.channels) != n:
            self.channels = [ChannelState() for _ in range(n)]

    def update(self, dt: float, peaks: list[float], rms: list[float]) -> None:
        """Feed a fresh measurement. ``dt`` is the time since the previous call."""
        dt = max(0.0, float(dt))
        self._resize(len(peaks))
        a = 1.0 - math.exp(-dt / self.rms_tau) if dt > 0 else 1.0
        for st, p, r in zip(self.channels, peaks, rms):
            if p >= st.peak:
                st.peak = p
            else:
                st.peak = max(p, st.peak - self.release * dt)
            if p >= st.hold:
                st.hold = p
                st.hold_age = 0.0
            else:
                st.hold_age += dt
                if st.hold_age > self.hold_seconds:
                    st.hold = max(p, st.hold - self.release * dt)
            st.rms += (r - st.rms) * a

    def decay(self, dt: float) -> None:
        """No fresh data: let everything fall as if silence were being measured."""
        self.update(dt, [SILENCE_FLOOR] * len(self.channels), [SILENCE_FLOOR] * len(self.channels))

    def reset(self) -> None:
        self.channels = []


class SilenceDetector:
    """Raises an alarm when the loudest channel stays under ``threshold_db`` for ``hold_seconds``."""

    def __init__(self, threshold_db: float = -50.0, hold_seconds: float = 10.0):
        self.threshold_db = float(threshold_db)
        self.hold_seconds = float(hold_seconds)
        self.silent_for = 0.0

    def update(self, dt: float, peaks: list[float]) -> bool:
        level = max(peaks) if peaks else SILENCE_FLOOR
        if level < self.threshold_db:
            self.silent_for += max(0.0, dt)
        else:
            self.silent_for = 0.0
        return self.active

    @property
    def active(self) -> bool:
        return self.silent_for >= self.hold_seconds

    def reset(self) -> None:
        self.silent_for = 0.0


class OverDetector:
    """Latches an OVER indication for ``hold_seconds`` after any channel clips."""

    def __init__(self, over_db: float = OVER_DB, hold_seconds: float = 2.0):
        self.over_db = float(over_db)
        self.hold_seconds = float(hold_seconds)
        self.since_over = math.inf
        self.count = 0

    def update(self, dt: float, peaks: list[float]) -> bool:
        if peaks and max(peaks) >= self.over_db:
            self.since_over = 0.0
            self.count += 1
        else:
            self.since_over += max(0.0, dt)
        return self.active

    @property
    def active(self) -> bool:
        return self.since_over < self.hold_seconds

    def reset(self) -> None:
        self.since_over = math.inf
        self.count = 0
