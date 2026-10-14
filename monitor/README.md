# Monitoring Application (MonitoringApp.exe)

A Windows desktop program that plays several video sources at once for monitoring
and shows **live audio level meters** for each one. It is a small multiviewer: streams
or files in a grid, one of them audible, every one metered, with SILENCE and NO SIGNAL
alarms.

Python, Qt and libmpv, packaged as a single `MonitoringApp.exe`, licensed through the
platform in `../platform` (https://license.oncue.cy). The Python package is still called
`barpi_monitor`, after the project it started in.

![Monitoring Application](assets/screenshot.png)

## Download

Customers download the latest build from the licensing platform:
https://license.oncue.cy/download/monitoring-application (upload new builds on the
software's page there).

Every push that touches `monitor/` also builds the exe on GitHub Actions and self-tests it.
Builds from `main` (and manual runs of the workflow) are published as the
**`monitor-latest`** pre-release of this repository. Builds from other branches are kept as a workflow artifact instead: open the run under
*Actions → Build Monitoring Application (Windows exe)* and download `MonitoringApp-<version>-win64`.

Take `MonitoringApp.exe` (or the zip, which adds a short README). It needs nothing
installed. The exe is not code-signed, so SmartScreen will ask once: *More info → Run anyway*.

## What it does

| | |
| --- | --- |
| Sources | Files (any format FFmpeg reads), RTSP, SRT, UDP/RTP multicast, RTMP, HLS, HTTP(S) |
| Layout | Automatic grid (1, 2×2, 3×3, 4×4…) or a fixed column count; double-click a tile to show it alone |
| Audio | One tile audible at a time (click or keys 1–9), monitor volume, output device selection, mute-all that keeps metering |
| Meters | Per-channel peak (PPM ballistics) + RMS + peak hold in dBFS, zone-coloured at −18 / −9 dBFS, OVER indicator, EBU R128 momentary & short-term loudness |
| Channels | Mono, stereo, 5.1, 7.1: one bar per channel of the *source*, even when the sound card is stereo |
| Playback | Play/Pause, Stop, Loop and a position bar per tile; Space, arrow keys, Home; pause everything with Ctrl+Space |
| Alarms | NO SIGNAL (drop / error / stall, with auto-reconnect), NO VIDEO, FROZEN, BLACK, OVER (clipping), TOO LOUD (short-term LUFS or repeated peaks), SILENCE, L / R MISSING, LOW LEVEL; all thresholds configurable, per-source on/off, optional beep |
| Alarm log | Every alarm start and end with a timestamp in a panel under the tiles and in `alarms.csv` next to the config file |
| Status | Resolution, frame rate, codecs, sample rate, layout and bitrate under each tile; alarm list in the status bar and window title |
| Persistence | Sources, layout, volume, device and window position are saved per user |

## Licensing

The program needs a serial key from the licensing platform in `../platform`
(https://license.oncue.cy). `barpi_monitor/license.py` activates the key with a hashed
computer id, stores the activation token in `license.json` next to the config, and checks
in every few minutes (`LicenseMonitor` in `license_ui.py`). The platform answers *active*
or *locked* with a message; *revoked*, *expired* and *unknown* send the operator back to the
activation dialog. While not allowed to run, the window shows a lock screen and every tile
is stopped. If the platform is unreachable the last answer holds for 72 hours.
`--license-server URL` (or `BARPI_LICENSE_SERVER`) points a build at another platform.

Computers without internet import an *offline licence file* (`.lic`) instead of a key: the
platform signs a payload (key, software slug, customer, computer id, expiry) with its RSA-2048
key and the program verifies it with the public modulus in `license.py` (`PUBLIC_KEY_N`,
pure-Python RSASSA-PKCS1-v1_5/SHA-256, no extra dependency). An imported file puts the client
in `offline` mode: no grace rule, valid until the file's expiry, and the file's signature
serves as the check-in token so a computer that does get a connection can still be locked
from the platform. A clock set back more than an hour before the last run locks the program
until the clock is right (`clock_mark` in `license.json`). Rotating the platform key means
re-issuing every offline file and rebuilding the exe with the new modulus.

## How the alarms work

Audio alarms come from the same per-frame peak, RMS and loudness figures as the meters
(`barpi_monitor/tile.py`, detectors in `barpi_monitor/levels.py`): OVER is any frame
whose sample peak reaches −0.3 dBFS; TOO LOUD is short-term loudness above a threshold
for a few seconds, or several peaks above a second threshold within ten seconds;
SILENCE, LOW LEVEL and L/R MISSING are sustained conditions on the loudest channel.

Picture alarms sample one raw frame per second (`screenshot-raw` in mpv, about 20 ms
and a few percent of a core per 1080p source) and keep a sparse pixel signature of it.
Two identical signatures in a row mean the picture did not change (FROZEN after N s);
a low mean brightness means BLACK; a grab that fails while playing means NO VIDEO.
Alarms are suspended while a source is paused, stopped or reconnecting.

## Threading rule

Each tile embeds mpv's own video window inside a Qt window, and mpv drives that window
from its own threads. On Windows a parent and child window owned by different threads
exchange synchronous messages, so if the GUI thread ever waits for mpv's core while
mpv's window thread waits for the GUI thread, both stop for good. Two rules keep that
from happening: the GUI thread only ever *queues* commands to mpv (`command_async`,
never a blocking property set or command; the poll thread does all the reading), and
tiles are never re-parented or hidden/shown during a layout change unless their
visibility really changes.

## How the meters work

Each tile is its own libmpv instance. Two FFmpeg audio filters are inserted into mpv's
filter chain:

```
astats=metadata=1:reset=1:measure_perchannel=Peak_level+RMS_level
ebur128=metadata=1
```

`astats` tags every decoded audio frame with per-channel peak and RMS level, `ebur128`
with R128 loudness. mpv exposes those tags through its `af-metadata/<label>` property,
which a thread reads 25 times a second (`barpi_monitor/player.py`). The filters run
before mute, volume and the down-mix to the output device, so a muted 5.1 stream still
meters six channels. The widget applies PPM ballistics (instant attack, 20 dB/s release,
1.5 s peak hold) in `barpi_monitor/levels.py`, which is pure Python and unit-tested.

## Running from source

```bash
cd monitor
pip install -r requirements.txt
# Windows: put libmpv-2.dll in monitor/vendor/ (build.ps1 downloads it)
# Linux:   apt install libmpv2
python run_monitor.py                     # or: python -m barpi_monitor
python run_monitor.py --self-test         # checks libmpv, metering and Qt without a window
python -m pytest tests
```

## Building the exe

**On GitHub:** *Actions → Build Barpi Monitor (Windows exe) → Run workflow*. The job
downloads the current libmpv Windows build, runs the unit tests, runs PyInstaller, runs
`MonitoringApp.exe --self-test` on the result, and publishes the release.

**On a Windows PC** with Python 3.11+:

```powershell
powershell -ExecutionPolicy Bypass -File monitor\build.ps1
```

The result is `monitor\dist\MonitoringApp.exe`. The script fetches `libmpv-2.dll` from
the mpv Windows builds on GitHub (zhongfly/mpv-winbuild, falling back to
shinchiro/mpv-winbuild-cmake); pass `-MpvArchiveUrl` to pin a particular archive.

**On Linux (cross-build with Wine)**, when no Windows machine or runner is available:

```bash
sudo apt install wine64 p7zip-full gcc-mingw-w64-x86-64
monitor/build-wine.sh        # result: monitor/build-wine/dist/MonitoringApp.exe
```

It runs the Windows Python and PyInstaller under Wine, builds a stub for the Windows
system ICU library that Qt links against (Wine has none; the stub is not shipped), and
finishes by running the exe's own `--self-test` under Wine. The output is the same bundle
the Windows build produces.

## Files

| | |
| --- | --- |
| `barpi_monitor/levels.py` | dBFS parsing, meter ballistics, silence and over detectors (no Qt, no mpv) |
| `barpi_monitor/player.py` | libmpv wrapper: poll thread, state machine, stall detection, reconnect |
| `barpi_monitor/meter.py` | the meter widget |
| `barpi_monitor/tile.py` | video surface + meter + transport bar + footer + alarm logic for one source |
| `barpi_monitor/window.py` | grid, toolbar, transport keys, alarm log (panel and CSV), drag & drop, persistence |
| `barpi_monitor/selftest.py` | `--self-test` |
| `MonitoringApp.spec` | PyInstaller recipe |
| `build.ps1` | local Windows build |
| `../.github/workflows/build-monitor.yml` | CI build and release |

The logo at the left of the toolbar is `assets/logo.png` (transparent PNG, any size; it is
scaled to the bar). `tools/key_logo.py` cuts a logo out of a baked-in checkerboard background.

Settings and sources: `%APPDATA%\BarpiMonitor\config.json` (the folder keeps its original name so existing installs keep their licence and settings). Log: `monitor.log` next to it; alarms: `alarms.csv`.

## Troubleshooting

- **The Actions job fails after a few seconds with no log**: open the run and read the
  annotation. "The job was not started because recent account payments have failed or
  your spending limit needs to be increased" means GitHub is refusing to start a hosted
  Windows runner for this private repository (Windows minutes are billed at 2×). Fix it
  under *GitHub → Settings → Billing & plans* (payment method or spending limit) and
  re-run the workflow, or build on a Windows PC with `monitor\build.ps1`.

- **No sound**: pick the device in *Audio out*; check *Mute all* is off and the right tile is selected (blue border, AUDIO badge).
- **RTSP will not connect**: the program forces TCP transport; make sure the camera allows it. The tile's status shows mpv's last error.
- **High CPU with many tiles**: hardware decoding is on by default (Settings); lower the source resolution if the GPU cannot keep up.
- **"libmpv-2.dll could not be loaded"**: the exe is corrupt or blocked; download it again, or put `libmpv-2.dll` next to it.
