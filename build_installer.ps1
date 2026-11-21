<#
.SYNOPSIS
    ORCUS Downloader - Self-Contained Windows Installer Build Script
.DESCRIPTION
    Automates the full pipeline:
    1. Verifies/Provisions FFmpeg, FFprobe & Deno binaries in ./bin/
    2. Builds standalone directory distribution using PyInstaller (--onedir)
    3. Verifies the bundled distribution
    4. Compiles Inno Setup 6 installer (setup.iss) into ./installer_output/
    Optional: -Portable also builds the single-file portable exe and copies it to
    ./ORCUS Downloader.exe (FFmpeg/Deno are auto-downloaded at runtime by that build).
.PARAMETER Python
    Python interpreter to build with (default: "python" on PATH). Python 3.11+ recommended.
.EXAMPLE
    .\build_installer.ps1
    .\build_installer.ps1 -Python C:\Python313\python.exe -Portable
#>

[CmdletBinding()]
param (
    [string]$Python = "python",
    [switch]$Portable,
    [switch]$SkipPyInstaller,
    [switch]$SkipInnoSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# Version is defined once in setup.iss (keep src/version.py in sync)
$IssContent = Get-Content (Join-Path $ProjectRoot "setup.iss") -Raw
if ($IssContent -notmatch '#define MyAppVersion "([^"]+)"') {
    Write-Error "Could not read MyAppVersion from setup.iss."
}
$AppVersion = $Matches[1]
$PyVersionFile = Get-Content (Join-Path $ProjectRoot "src\version.py") -Raw
if ($PyVersionFile -notmatch "__version__ = `"$([regex]::Escape($AppVersion))`"") {
    Write-Error "Version mismatch: setup.iss is $AppVersion but src/version.py differs. Update both."
}

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   ORCUS Downloader v$AppVersion - Build & Installer Packaging Pipeline " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Resolve the Python interpreter. Conda environments keep Tcl/Tk/OpenSSL DLLs in
# Library\bin; without it on PATH PyInstaller silently produces a broken build.
$PythonExe = (& $Python -c "import sys; print(sys.executable)").Trim()
if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
    Write-Error "Python interpreter not found: $Python (use -Python <path>)."
}
$PythonDir = Split-Path $PythonExe
$CondaLibBin = Join-Path $PythonDir "Library\bin"
if (Test-Path $CondaLibBin) {
    $env:PATH = "$PythonDir;$CondaLibBin;$(Join-Path $PythonDir 'DLLs');$env:PATH"
}
Write-Host "Using Python: $PythonExe ($(& $PythonExe --version))" -ForegroundColor Gray

# -----------------------------------------------------------------------------
# Step 1: Ensure bin/ffmpeg.exe, bin/ffprobe.exe and bin/deno.exe exist
# -----------------------------------------------------------------------------
Write-Host "`n[1/4] Checking FFmpeg & Deno binaries in ./bin/..." -ForegroundColor Yellow
$BinDir = Join-Path $ProjectRoot "bin"
$FfmpegExe = Join-Path $BinDir "ffmpeg.exe"
$FfprobeExe = Join-Path $BinDir "ffprobe.exe"
$DenoExe = Join-Path $BinDir "deno.exe"

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe)) {
    Write-Host "FFmpeg binaries not found in ./bin/. Running Python provisioning..." -ForegroundColor Gray
    & $PythonExe -c "import sys; sys.path.insert(0, 'src'); import ffmpeg_manager; ffmpeg_manager.ensure_ffmpeg()"

    # Check if downloaded to AppData and copy to local bin/
    $AppDataBin = Join-Path $env:LOCALAPPDATA "ORCUS Downloader\bin"
    if (Test-Path (Join-Path $AppDataBin "ffmpeg.exe")) {
        Copy-Item (Join-Path $AppDataBin "ffmpeg.exe") -Destination $FfmpegExe -Force
        Copy-Item (Join-Path $AppDataBin "ffprobe.exe") -Destination $FfprobeExe -Force
    }
}

if ((Test-Path $FfmpegExe) -and (Test-Path $FfprobeExe)) {
    $FfmpegSizeMB = [math]::Round(((Get-Item $FfmpegExe).Length / 1MB), 2)
    $FfprobeSizeMB = [math]::Round(((Get-Item $FfprobeExe).Length / 1MB), 2)
    Write-Host " [OK] FFmpeg found: $FfmpegExe ($FfmpegSizeMB MB)" -ForegroundColor Green
    Write-Host " [OK] FFprobe found: $FfprobeExe ($FfprobeSizeMB MB)" -ForegroundColor Green
} else {
    Write-Error "Failed to locate or download FFmpeg & FFprobe binaries in ./bin/."
}

# Deno JS runtime (required by yt-dlp for YouTube formats above 360p)
if (-not (Test-Path $DenoExe)) {
    Write-Host "Deno not found in ./bin/. Downloading..." -ForegroundColor Gray
    $DenoZip = Join-Path $BinDir "deno.zip"
    Invoke-WebRequest -Uri "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -OutFile $DenoZip -UseBasicParsing
    Expand-Archive -Path $DenoZip -DestinationPath $BinDir -Force
    Remove-Item $DenoZip -Force
}
if (Test-Path $DenoExe) {
    $DenoSizeMB = [math]::Round(((Get-Item $DenoExe).Length / 1MB), 2)
    Write-Host " [OK] Deno found: $DenoExe ($DenoSizeMB MB)" -ForegroundColor Green
} else {
    Write-Error "Failed to locate or download deno.exe in ./bin/."
}

# -----------------------------------------------------------------------------
# Step 2: PyInstaller --onedir Build (+ optional --onefile portable)
# -----------------------------------------------------------------------------
if (-not $SkipPyInstaller) {
    Write-Host "`n[2/4] Running PyInstaller build (ORCUS_Downloader.spec)..." -ForegroundColor Yellow

    # Clean old build artifacts
    $DistAppDir = Join-Path $ProjectRoot "dist\ORCUS Downloader"
    if (Test-Path $DistAppDir) {
        Write-Host "Cleaning previous dist directory: $DistAppDir" -ForegroundColor Gray
        Remove-Item -Path $DistAppDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    & $PythonExe -m PyInstaller "$ProjectRoot\ORCUS_Downloader.spec" --clean --noconfirm --log-level WARN
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller onedir build failed (exit $LASTEXITCODE)." }

    $BuiltExe = Join-Path $ProjectRoot "dist\ORCUS Downloader\ORCUS Downloader.exe"
    if (-not (Test-Path $BuiltExe)) {
        Write-Error "PyInstaller build failed: $BuiltExe does not exist."
    }
    Write-Host " [OK] PyInstaller directory mode build successful." -ForegroundColor Green

    if ($Portable) {
        Write-Host "Building single-file portable executable..." -ForegroundColor Gray
        $PortableDist = Join-Path $ProjectRoot "dist\portable"
        & $PythonExe -m PyInstaller --noconsole --onefile --clean --noconfirm --log-level WARN `
            --icon "$ProjectRoot\app_icon.ico" `
            --add-data "$ProjectRoot\app_icon.png;." `
            --add-data "$ProjectRoot\app_icon.ico;." `
            --add-data "$ProjectRoot\assets;assets" `
            --collect-all customtkinter `
            --collect-all yt_dlp_ejs `
            --hidden-import pystray._win32 `
            --paths "$ProjectRoot\src" `
            --name "ORCUS Downloader" `
            --distpath $PortableDist `
            --workpath (Join-Path $ProjectRoot "build\portable") `
            --specpath (Join-Path $ProjectRoot "build\portable") `
            "$ProjectRoot\main.py"
        if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller onefile build failed (exit $LASTEXITCODE)." }
        Copy-Item (Join-Path $PortableDist "ORCUS Downloader.exe") -Destination (Join-Path $ProjectRoot "ORCUS Downloader.exe") -Force
        Write-Host " [OK] Portable exe copied to: $(Join-Path $ProjectRoot 'ORCUS Downloader.exe')" -ForegroundColor Green
    }
} else {
    Write-Host "`n[2/4] Skipping PyInstaller (-SkipPyInstaller specified)." -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# Step 3: Verify Bundled Files in dist
# -----------------------------------------------------------------------------
Write-Host "`n[3/4] Verifying bundled distribution package..." -ForegroundColor Yellow
$TargetDist = Join-Path $ProjectRoot "dist\ORCUS Downloader"
$TargetIcon = Join-Path $TargetDist "app_icon.ico"

if (-not (Test-Path (Join-Path $TargetDist "ORCUS Downloader.exe"))) {
    Write-Error "dist\ORCUS Downloader\ORCUS Downloader.exe not found. Run without -SkipPyInstaller first."
}

# The spec bundles bin/ into _internal\bin; fall back to copying next to the exe.
foreach ($Name in @("ffmpeg.exe", "ffprobe.exe", "deno.exe")) {
    $Bundled = (Test-Path (Join-Path $TargetDist "_internal\bin\$Name")) -or (Test-Path (Join-Path $TargetDist "bin\$Name"))
    if (-not $Bundled) {
        Write-Host "Copying $Name into dist/ORCUS Downloader/bin/..." -ForegroundColor Gray
        $DistBin = Join-Path $TargetDist "bin"
        New-Item -ItemType Directory -Path $DistBin -Force | Out-Null
        Copy-Item (Join-Path $BinDir $Name) -Destination (Join-Path $DistBin $Name) -Force
    }
}

$RequiredFiles = @(
    "_internal\assets\fonts\MaterialIconsOutlined-Regular.otf",
    "_internal\customtkinter\assets\fonts\Roboto\Roboto-Regular.ttf",
    "_internal\yt_dlp_ejs",
    "_internal\tk86t.dll"
)
foreach ($Rel in $RequiredFiles) {
    if (-not (Test-Path (Join-Path $TargetDist $Rel))) {
        Write-Error "Bundle is missing required file: $Rel"
    }
}

if (-not (Test-Path $TargetIcon)) {
    Copy-Item (Join-Path $ProjectRoot "app_icon.ico") -Destination $TargetIcon -Force
}

Write-Host " [OK] Bundled executables and assets confirmed in: $TargetDist" -ForegroundColor Green

# -----------------------------------------------------------------------------
# Step 4: Compile Inno Setup Installer (setup.iss)
# -----------------------------------------------------------------------------
if (-not $SkipInnoSetup) {
    Write-Host "`n[4/4] Compiling Inno Setup 6 installer (setup.iss)..." -ForegroundColor Yellow

    # Find iscc.exe
    $IsccCandidates = @(
        "ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )

    $IsccPath = $null
    foreach ($cand in $IsccCandidates) {
        if ($cand -eq "ISCC.exe") {
            $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
            if ($cmd) { $IsccPath = $cmd.Source; break }
        } elseif (Test-Path $cand) {
            $IsccPath = $cand
            break
        }
    }

    if (-not $IsccPath) {
        Write-Error "Inno Setup compiler (ISCC.exe) not found. Install via: winget install JRSoftware.InnoSetup"
    }

    Write-Host "Using Inno Setup compiler: $IsccPath" -ForegroundColor Gray

    $OutputDir = Join-Path $ProjectRoot "installer_output"
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }

    & $IsccPath /Q "$ProjectRoot\setup.iss"
    if ($LASTEXITCODE -ne 0) { Write-Error "Inno Setup compilation failed (exit $LASTEXITCODE)." }

    $FinalInstaller = Join-Path $OutputDir "ORCUS_Downloader_v${AppVersion}_Setup.exe"
    if (Test-Path $FinalInstaller) {
        $InstallerSizeMB = [math]::Round(((Get-Item $FinalInstaller).Length / 1MB), 2)
        Write-Host "`n=================================================================" -ForegroundColor Green
        Write-Host " SUCCESS: Self-contained installer created successfully!" -ForegroundColor Green
        Write-Host " File: $FinalInstaller" -ForegroundColor Green
        Write-Host " Size: $InstallerSizeMB MB" -ForegroundColor Green
        Write-Host " Target PC: Any Windows 10/11 x64 PC (Zero dependencies needed)" -ForegroundColor Green
        Write-Host "=================================================================" -ForegroundColor Green
    } else {
        Write-Error "Inno Setup compilation finished but installer file was not found."
    }
} else {
    Write-Host "`n[4/4] Skipping Inno Setup (-SkipInnoSetup specified)." -ForegroundColor DarkGray
}
