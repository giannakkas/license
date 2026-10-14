#!/usr/bin/env bash
# Cross-builds MonitoringApp.exe on Linux with Wine, for when no Windows machine or runner is
# at hand. Verified on Ubuntu 24.04 with wine 9.0; the result passes the exe's own --self-test
# under Wine and is the same PyInstaller bundle the Windows build produces.
#
#   sudo apt install wine64 p7zip-full gcc-mingw-w64-x86-64 curl python3
#   monitor/build-wine.sh            # result: monitor/build-wine/dist/MonitoringApp.exe
#
# Steps: Windows Python (embeddable) + pip under Wine -> Windows wheels of PySide6, python-mpv
# and PyInstaller -> libmpv-2.dll from the mpv Windows builds -> a stub for the Windows system
# ICU library that Qt links against (Wine has none; the stub stays in the Wine prefix and is
# not shipped) -> unit tests -> PyInstaller -> the exe's self-test.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${BARPI_WINE_WORK:-$HERE/build-wine}"
PY_VER="${BARPI_WIN_PYTHON:-3.12.10}"
export WINEPREFIX="$WORK/prefix" WINEDEBUG="${WINEDEBUG:--all}" WINEDLLOVERRIDES="mscoree,mshtml="
unset DISPLAY
mkdir -p "$WORK/dl" "$WORK/py" "$WORK/stub" "$WORK/selftest" "$HERE/vendor"

for tool in wine 7z x86_64-w64-mingw32-gcc curl python3; do
    command -v "$tool" >/dev/null || { echo "missing: $tool (apt install wine64 p7zip-full gcc-mingw-w64-x86-64 curl python3)"; exit 1; }
done
# Note: Windows Python under Wine aborts when stdout is a file ("init_sys_streams"), so every
# call below reads stdin from /dev/null and writes through a pipe.
WPY="$WORK/py/python.exe"
wpy() { timeout "${BARPI_WINE_STEP_TIMEOUT:-1200}" wine "$WPY" "$@" </dev/null 2>&1; }

echo "== Windows Python $PY_VER under Wine"
[ -f "$WORK/dl/python-embed.zip" ] || curl -sSL -o "$WORK/dl/python-embed.zip" \
    "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
if [ ! -f "$WPY" ]; then
    python3 -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$WORK/dl/python-embed.zip" "$WORK/py"
    sed -i 's/^#import site/import site/' "$WORK"/py/python3*._pth   # let pip and site-packages work
fi
wineboot --init >/dev/null 2>&1 || true
wineserver -w   # let the prefix finish initialising before the first real process runs
if ! wpy -m pip --version | grep -q '^pip'; then
    [ -f "$WORK/dl/get-pip.py" ] || curl -sSL -o "$WORK/dl/get-pip.py" https://bootstrap.pypa.io/get-pip.py
    wpy "$WORK/dl/get-pip.py" --no-warn-script-location | tail -1
fi
wpy -m pip install --no-warn-script-location -r "$HERE/requirements.txt" | tail -1

echo "== libmpv"
if [ ! -f "$HERE/vendor/libmpv-2.dll" ]; then
    if [ -z "${MPV_ARCHIVE_URL:-}" ]; then
        # The mpv Windows builds are mirrored on SourceForge (where mpv.io's download link points).
        MPV_ARCHIVE_URL="$(curl -sSL 'https://sourceforge.net/projects/mpv-player-windows/rss?path=/libmpv' \
            | python3 -I -c 'import re, sys; m = re.findall(r"<link>(https://[^<]*mpv-dev-x86_64-\d[^<]*\.7z/download)</link>", sys.stdin.read()); print(m[0] if m else "")')"
    fi
    [ -n "$MPV_ARCHIVE_URL" ] || { echo "no libmpv build found; set MPV_ARCHIVE_URL"; exit 1; }
    echo "   $MPV_ARCHIVE_URL"
    curl -sSL -A barpi-monitor-build -o "$WORK/dl/mpv-dev.7z" "$MPV_ARCHIVE_URL"
    7z e -y -o"$WORK/dl/mpv" "$WORK/dl/mpv-dev.7z" libmpv-2.dll >/dev/null
    cp "$WORK/dl/mpv/libmpv-2.dll" "$HERE/vendor/"
    basename "${MPV_ARCHIVE_URL%/download}" > "$HERE/vendor/LIBMPV-VERSION.txt"
fi

echo "== Vulkan loader (bundled for PCs whose graphics driver installs none)"
if [ ! -f "$HERE/vendor/vulkan-1.dll" ]; then
    curl -sSL -o "$WORK/dl/vulkan-runtime.zip" "https://sdk.lunarg.com/sdk/download/latest/windows/vulkan-runtime-components.zip"
    python3 -I - "$WORK/dl/vulkan-runtime.zip" "$HERE/vendor" <<'PY'
import pathlib, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
out = pathlib.Path(sys.argv[2])
names = z.namelist()
dll = next(n for n in names if n.endswith("/x64/vulkan-1.dll"))
lic = next(n for n in names if n.endswith("VulkanRT-License.txt"))
(out / "vulkan-1.dll").write_bytes(z.read(dll))
(out / "VULKAN-LICENSE.txt").write_bytes(z.read(lic))
(out / "VULKAN-VERSION.txt").write_text(dll.split("/")[0] + " (sdk.lunarg.com vulkan-runtime-components.zip)\n")
print("   " + dll)
PY
fi

echo "== ICU stub for the Wine prefix"
if [ ! -f "$WINEPREFIX/drive_c/windows/system32/icuuc.dll" ]; then
    # Qt6Core.dll imports the ICU that ships inside Windows 10/11; list those imports with the
    # pefile that PyInstaller installed, and export them from a do-nothing DLL.
    wpy -c "
import pefile, sys
pe = pefile.PE(r'$(winepath -w "$WORK/py/Lib/site-packages/PySide6/Qt6Core.dll")', fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
names = sorted({i.name.decode() for e in pe.DIRECTORY_ENTRY_IMPORT if e.dll.lower() == b'icuuc.dll' for i in e.imports if i.name})
print('\n'.join(f'__declspec(dllexport) long long {n}(void) {{ return 0; }}' for n in names))" \
        | tr -d '\r' | grep '__declspec' > "$WORK/stub/icuuc_stub.c"
    x86_64-w64-mingw32-gcc -shared -O1 -o "$WORK/stub/icuuc.dll" "$WORK/stub/icuuc_stub.c"
    cp "$WORK/stub/icuuc.dll" "$WINEPREFIX/drive_c/windows/system32/"
fi
wpy -c "from PySide6 import QtCore; print('Qt', QtCore.qVersion(), 'imports under Wine')" | tail -1

echo "== unit tests"
wpy -m pytest "$(winepath -w "$HERE/tests")" -q | tail -1

echo "== PyInstaller"
rm -rf "$WORK/dist" "$WORK/build"
( cd "$HERE" && wpy -m PyInstaller MonitoringApp.spec --noconfirm --clean \
    --distpath "$(winepath -w "$WORK/dist")" --workpath "$(winepath -w "$WORK/build")" ) \
    | tee "$WORK/pyinstaller.log" | grep -E 'ERROR|Build complete' || true
[ -f "$WORK/dist/MonitoringApp.exe" ] || { echo "build failed; see $WORK/pyinstaller.log"; exit 1; }

echo "== self-test of the built exe (under Wine)"
rm -f "$WORK/selftest/self-test.log"
timeout 600 wine "$WORK/dist/MonitoringApp.exe" --self-test --config "$(winepath -w "$WORK/selftest/config.json")" </dev/null >/dev/null 2>&1 || true
cat "$WORK/selftest/self-test.log"
grep -q '^ALL PASSED' "$WORK/selftest/self-test.log"
ls -la "$WORK/dist/MonitoringApp.exe"
