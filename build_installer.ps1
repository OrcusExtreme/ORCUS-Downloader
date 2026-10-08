<#
.SYNOPSIS
    ORCUS Downloader - Self-Contained Windows Installer Build Script
.DESCRIPTION
    Automates the full pipeline:
    1. Verifies/Provisions FFmpeg & FFprobe binaries in ./bin/
    2. Builds standalone directory distribution using PyInstaller (--onedir)
    3. Compiles Inno Setup 6 installer (setup.iss)
    4. Outputs standalone installer into ./installer_output/
#>

[CmdletBinding()]
param (
    [switch]$SkipPyInstaller,
    [switch]$SkipInnoSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   ORCUS Downloader v1.0.4 - Build & Installer Packaging Pipeline " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# Step 1: Ensure bin/ffmpeg.exe and bin/ffprobe.exe exist
# -----------------------------------------------------------------------------
Write-Host "`n[1/4] Checking FFmpeg binaries in ./bin/..." -ForegroundColor Yellow
$BinDir = Join-Path $ProjectRoot "bin"
$FfmpegExe = Join-Path $BinDir "ffmpeg.exe"
$FfprobeExe = Join-Path $BinDir "ffprobe.exe"

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe)) {
    Write-Host "FFmpeg binaries not found in ./bin/. Running Python provisioning..." -ForegroundColor Gray
    python -c "import sys; sys.path.insert(0, 'src'); import ffmpeg_manager; ffmpeg_manager.ensure_ffmpeg()"
    
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

# -----------------------------------------------------------------------------
# Step 2: PyInstaller --onedir Build
# -----------------------------------------------------------------------------
if (-not $SkipPyInstaller) {
    Write-Host "`n[2/4] Running PyInstaller build (ORCUS_Downloader.spec)..." -ForegroundColor Yellow

    # Clean old build artifacts
    $DistAppDir = Join-Path $ProjectRoot "dist\ORCUS Downloader"
    if (Test-Path $DistAppDir) {
        Write-Host "Cleaning previous dist directory: $DistAppDir" -ForegroundColor Gray
        Remove-Item -Path $DistAppDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    # Execute PyInstaller
    python -m PyInstaller "$ProjectRoot\ORCUS_Downloader.spec" --clean --noconfirm

    $BuiltExe = Join-Path $ProjectRoot "dist\ORCUS Downloader\ORCUS Downloader.exe"
    if (-not (Test-Path $BuiltExe)) {
        Write-Error "PyInstaller build failed: $BuiltExe does not exist."
    }
    Write-Host " [OK] PyInstaller directory mode build successful." -ForegroundColor Green
} else {
    Write-Host "`n[2/4] Skipping PyInstaller (--SkipPyInstaller specified)." -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# Step 3: Verify Bundled Files in dist
# -----------------------------------------------------------------------------
Write-Host "`n[3/4] Verifying bundled distribution package..." -ForegroundColor Yellow
$TargetDist = Join-Path $ProjectRoot "dist\ORCUS Downloader"
$TargetFfmpeg = Join-Path $TargetDist "bin\ffmpeg.exe"
$TargetIcon = Join-Path $TargetDist "app_icon.ico"

# If bin folder wasn't automatically copied into dist, copy it now
if (-not (Test-Path $TargetFfmpeg)) {
    Write-Host "Copying bin/ into dist/ORCUS Downloader/bin/..." -ForegroundColor Gray
    $DistBin = Join-Path $TargetDist "bin"
    New-Item -ItemType Directory -Path $DistBin -Force | Out-Null
    Copy-Item $FfmpegExe -Destination (Join-Path $DistBin "ffmpeg.exe") -Force
    Copy-Item $FfprobeExe -Destination (Join-Path $DistBin "ffprobe.exe") -Force
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
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )

    $IsccPath = $null
    foreach ($cand in $IsccCandidates) {
        if ($cand -eq "ISCC.exe" -and (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue)) {
            $IsccPath = "ISCC.exe"
            break
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

    & $IsccPath "$ProjectRoot\setup.iss"

    $FinalInstaller = Join-Path $OutputDir "ORCUS_Downloader_v1.0.4_Setup.exe"
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
    Write-Host "`n[4/4] Skipping Inno Setup (--SkipInnoSetup specified)." -ForegroundColor DarkGray
}
