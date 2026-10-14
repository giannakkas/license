# Builds MonitoringApp.exe on a Windows PC.  Needs Python 3.11+ on PATH.
#   powershell -ExecutionPolicy Bypass -File monitor\build.ps1
# Result: monitor\dist\MonitoringApp.exe
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
        if (-not $MpvArchiveUrl) {
            # The same builds are mirrored on SourceForge (the download link mpv.io points to).
            try {
                [xml]$rss = Invoke-WebRequest -Headers $headers "https://sourceforge.net/projects/mpv-player-windows/rss?path=/libmpv" | Select-Object -ExpandProperty Content
                $link = $rss.rss.channel.item | ForEach-Object { $_.link } | Where-Object { $_ -match 'mpv-dev-x86_64-\d.*\.7z/download$' } | Select-Object -First 1
                if ($link) { $MpvArchiveUrl = $link }
            } catch { Write-Warning "SourceForge lookup failed: $_" }
        }
        if (-not $MpvArchiveUrl) { throw "Could not find a libmpv build. Pass -MpvArchiveUrl or copy libmpv-2.dll into monitor\vendor." }
    }
    Write-Host "Downloading $MpvArchiveUrl"
    Invoke-WebRequest -Headers @{ "User-Agent" = "barpi-monitor-build" } -MaximumRedirection 10 $MpvArchiveUrl -OutFile vendor\mpv-dev.7z
    $sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
    if (-not $sevenZip -and (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) { $sevenZip = "$env:ProgramFiles\7-Zip\7z.exe" }
    if ($sevenZip) {
        & $sevenZip e vendor\mpv-dev.7z libmpv-2.dll -ovendor -y | Out-Null
    } else {
        # Windows 10/11 ship bsdtar, which reads 7z archives (including their BCJ2 filter).
        Write-Host "7-Zip not found; extracting with tar"
        tar -xf vendor\mpv-dev.7z -C vendor libmpv-2.dll
    }
    ($MpvArchiveUrl -replace '/download$', '' | Split-Path -Leaf) | Set-Content vendor\LIBMPV-VERSION.txt
    Remove-Item vendor\mpv-dev.7z
}
if (-not (Test-Path vendor\libmpv-2.dll)) { throw "vendor\libmpv-2.dll is still missing" }
if (-not (Test-Path vendor\vulkan-1.dll)) {
    # The official Khronos/LunarG loader, bundled for PCs whose graphics driver installs none.
    Write-Host "Downloading the Vulkan loader"
    $zip = Join-Path $env:TEMP "vulkan-runtime-components.zip"
    $dir = Join-Path $env:TEMP "vulkan-runtime-components"
    Invoke-WebRequest -MaximumRedirection 10 "https://sdk.lunarg.com/sdk/download/latest/windows/vulkan-runtime-components.zip" -OutFile $zip
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    Expand-Archive $zip -DestinationPath $dir
    $dll = Get-ChildItem $dir -Recurse -Filter vulkan-1.dll | Where-Object { $_.Directory.Name -eq "x64" } | Select-Object -First 1
    Copy-Item $dll.FullName vendor\vulkan-1.dll
    Get-ChildItem $dir -Recurse -Filter VulkanRT-License.txt | Select-Object -First 1 | ForEach-Object { Copy-Item $_.FullName vendor\VULKAN-LICENSE.txt }
    $dll.Directory.Parent.Name | Set-Content vendor\VULKAN-VERSION.txt
}

python -m pytest tests -q
pyinstaller MonitoringApp.spec --noconfirm --clean

Write-Host "Running the self-test..."
$cfg = Join-Path $env:TEMP "MonitoringAppSelfTest\config.json"
$p = Start-Process -FilePath (Resolve-Path dist\MonitoringApp.exe) -ArgumentList @("--self-test", "--config", "`"$cfg`"") -Wait -PassThru
Get-Content (Join-Path (Split-Path $cfg) "self-test.log")
if ($p.ExitCode -ne 0) { throw "Self-test failed with exit code $($p.ExitCode)" }
Write-Host "Built dist\MonitoringApp.exe"
