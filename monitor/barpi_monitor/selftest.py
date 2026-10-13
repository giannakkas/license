"""``BarpiMonitor.exe --self-test``: proves the packaged program can load libmpv, meter audio and draw.

Used by the CI build and handy on a new PC. Exit code 0 means every check passed.
"""
from __future__ import annotations

import array
import math
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

from . import APP_NAME, __version__
from .levels import SILENCE_FLOOR, MeterBallistics, SilenceDetector, parse_astats

# Two channels of 1 kHz sine: 0.5 full scale (-6.02 dBFS peak) and 0.25 (-12.04 dBFS peak).
EXPECTED_PEAKS = (-6.02, -12.04)
TOLERANCE_DB = 0.4
TONE_SECONDS = 6


def write_test_tone(path: Path, seconds: float = TONE_SECONDS, rate: int = 48000) -> None:
    """A stereo 16-bit WAV with a 1 kHz tone at 0.5 (left) and 0.25 (right) of full scale."""
    samples = array.array("h")
    step = 2 * math.pi * 1000 / rate
    for i in range(int(seconds * rate)):
        v = math.sin(i * step)
        samples.append(int(round(v * 0.5 * 32767)))
        samples.append(int(round(v * 0.25 * 32767)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def run_self_test(log_path: Path | None = None) -> int:
    lines: list[str] = [f"{APP_NAME} {__version__} self-test"]
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))

    # 1. pure maths
    peaks, rms = parse_astats({"lavfi.astats.1.Peak_level": "-6.0", "lavfi.astats.2.Peak_level": "-inf",
                               "lavfi.astats.1.RMS_level": "-9.0", "lavfi.astats.2.RMS_level": "-inf"})
    check("parse astats metadata", peaks == [-6.0, SILENCE_FLOOR] and rms == [-9.0, SILENCE_FLOOR], f"{peaks} {rms}")
    b = MeterBallistics(release_db_per_s=20)
    b.update(0, [-10.0], [-13.0])
    b.decay(1.0)
    check("meter release 20 dB/s", abs(b.channels[0].peak - (-30.0)) < 1e-6, f"{b.channels[0].peak:.2f}")
    s = SilenceDetector(-50, 2)
    s.update(1.5, [-70.0])
    quiet_early = s.active
    s.update(1.0, [-70.0])
    check("silence detector timing", not quiet_early and s.active)

    # 2. Qt (offscreen) and the meter widget
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication

        from .levels import ChannelState
        from .meter import LevelMeter

        app = QApplication.instance() or QApplication([sys.argv[0]])
        meter = LevelMeter()
        meter.resize(90, 320)
        meter.set_levels([ChannelState(peak=-12, rms=-18, hold=-10), ChannelState(peak=-30, rms=-36, hold=-28)],
                         ["L", "R"], True, False)
        meter.set_dim(False)
        img = QImage(meter.size(), QImage.Format_ARGB32)
        img.fill(0)
        meter.render(img)
        greens = sum(1 for x in range(img.width()) for y in range(img.height())
                     if (lambda c: c.green() > 150 and c.red() < 120)(img.pixelColor(x, y)))
        check("Qt renders the level meter", greens > 200, f"{greens} green pixels")
    except Exception as exc:  # noqa: BLE001
        check("Qt renders the level meter", False, repr(exc))
        app = None

    # 3. libmpv loads and meters a known signal through the real player class
    try:
        from .config import Settings, Source
        from .player import MonitorPlayer, import_mpv

        mpv = import_mpv()
        probe = mpv.MPV(vo="null", ao="null", idle="yes")
        version = probe._get_property("mpv-version")
        probe.terminate()
        check("libmpv loads", True, str(version))

        tone_dir = Path(tempfile.mkdtemp(prefix="barpi-monitor-"))
        tone = tone_dir / "tone.wav"
        write_test_tone(tone)
        collected: list[list[float]] = []
        states: list[str] = []
        player = MonitorPlayer(None, Settings(), headless=True)
        player.levels.connect(lambda snap: collected.append(list(snap.peaks)) if snap.has_audio else None)
        player.state.connect(lambda st, _d: states.append(st))
        player.load(Source(name="test tone", url=str(tone)))
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if app is not None:
                app.processEvents()
            time.sleep(0.02)
        player.close()
        try:
            tone.unlink()
            tone_dir.rmdir()
        except OSError:
            pass
        got = [max(p[i] for p in collected) for i in range(2)] if collected and all(len(p) == 2 for p in collected) else []
        ok = len(got) == 2 and all(abs(g - e) <= TOLERANCE_DB for g, e in zip(got, EXPECTED_PEAKS))
        check("meters read the test tone", ok,
              f"{len(collected)} frames, peaks {[round(g, 2) for g in got]} dBFS, expected {EXPECTED_PEAKS}")
        check("player reached PLAYING", "playing" in states, f"states {states}")
    except Exception as exc:  # noqa: BLE001
        check("libmpv loads", False, repr(exc))

    lines.append(f"{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
    report = "\n".join(lines)
    print(report)
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(report + "\n", encoding="utf-8")
        except OSError:
            pass
    return 0 if failures == 0 else 1
