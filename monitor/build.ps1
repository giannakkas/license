# Builds BarpiMonitor.exe on a Windows PC.  Needs Python 3.11+ on PATH.
#   powershell -ExecutionPolicy Bypass -File monitor\build.ps1
# Result: monitor\dist\BarpiMonitor.exe
param(
    # A libmpv "mpv-dev-x86_64-*.7z" archive. Leave empty to fetch the latest build from GitHub.
    [string]$MpvArchiveUrl = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt

New-Item -ItemType Directory -Force vendor | Out-Null
if (-not (Test-Path vendor\libmpv-2.dll)) {
    if (-not $MpvArchiveUrl) {
        Write-Host "Looking up the latest libmpv Windows build..."
        $headers = @{ "User-Agent" = "barpi-monitor-build" }
        foreach ($repo in @("zhongfly/mpv-winbuild", "shinchiro/mpv-winbuild-cmake")) {
            try {
                $rel = Invoke-RestMethod -Headers $headers "https://api.github.com/repos/$repo/releases/latest"
                $asset = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d' -and $_.name -notmatch 'v3' -and $_.name -like '*.7z' } | Select-Object -First 1
                if ($asset) { $MpvArchiveUrl = $asset.browser_download_url; break }
            } catch { Write-Warning "$repo lookup failed: $_" }
        }
        if (-not $MpvArchiveUrl) { throw "Could not find a libmpv build. Pass -MpvArchiveUrl or copy libmpv-2.dll into monitor\vendor." }
    }
    Write-Host "Downloading $MpvArchiveUrl"
    Invoke-WebRequest -Headers @{ "User-Agent" = "barpi-monitor-build" } $MpvArchiveUrl -OutFile vendor\mpv-dev.7z
    $sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
    if (-not $sevenZip -and (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) { $sevenZip = "$env:ProgramFiles\7-Zip\7z.exe" }
    if ($sevenZip) {
        & $sevenZip e vendor\mpv-dev.7z libmpv-2.dll -ovendor -y | Out-Null
    } else {
        Write-Host "7-Zip not found; extracting with py7zr"
        python -m pip install py7zr | Out-Null
        python -c "import py7zr; a=py7zr.SevenZipFile('vendor/mpv-dev.7z'); a.extract(path='vendor', targets=['libmpv-2.dll']); a.close()"
    }
    Split-Path -Leaf $MpvArchiveUrl | Set-Content vendor\LIBMPV-VERSION.txt
    Remove-Item vendor\mpv-dev.7z
}
if (-not (Test-Path vendor\libmpv-2.dll)) { throw "vendor\libmpv-2.dll is still missing" }

python -m pytest tests -q
pyinstaller BarpiMonitor.spec --noconfirm --clean

Write-Host "Running the self-test..."
$cfg = Join-Path $env:TEMP "BarpiMonitorSelfTest\config.json"
$p = Start-Process -FilePath (Resolve-Path dist\BarpiMonitor.exe) -ArgumentList @("--self-test", "--config", "`"$cfg`"") -Wait -PassThru
Get-Content (Join-Path (Split-Path $cfg) "self-test.log")
if ($p.ExitCode -ne 0) { throw "Self-test failed with exit code $($p.ExitCode)" }
Write-Host "Built dist\BarpiMonitor.exe"
