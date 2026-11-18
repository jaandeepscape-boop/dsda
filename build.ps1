# ==============================================================================
# HypeClipper One-Click PyInstaller Build Script
# Creates a lightweight standalone Windows .exe (~20-35MB)
# ==============================================================================

Write-Host "==================================================" -ForegroundColor Cipher
Write-Host "⚡ HypeClipper - 1-Click PyInstaller Build Script" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cipher

# 1. Install Requirements
Write-Host "`n[1/3] Installing Python dependencies from requirements.txt..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 2. Verify PyInstaller installation
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] PyInstaller failed to install. Exiting." -ForegroundColor Red
    exit 1
}

# 3. Build Standalone Executable
Write-Host "`n[2/3] Building HypeClipper.exe via PyInstaller..." -ForegroundColor Yellow

pyinstaller --noconfirm --onefile --windowed `
    --name "HypeClipper" `
    --exclude-module "matplotlib" `
    --exclude-module "scipy" `
    --exclude-module "numpy" `
    --exclude-module "pandas" `
    --exclude-module "PIL" `
    --exclude-module "tkinter.test" `
    --collect-all "customtkinter" `
    main.py

# 4. Verify Build Output
$exePath = "dist/HypeClipper.exe"
if (Test-Path $exePath) {
    $fileSizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 2)
    Write-Host "`n==================================================" -ForegroundColor Green
    Write-Host " ✨ BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host " Output Binary: $exePath" -ForegroundColor Cyan
    Write-Host " File Size: $fileSizeMB MB (Lightweight Standalone Exe)" -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Green
} else {
    Write-Host "`n[ERROR] PyInstaller build failed. Check logs above." -ForegroundColor Red
}
