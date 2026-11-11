# One command to finish: close port-forward windows, stop every service (data is kept),
# then optionally quit Docker Desktop to free RAM. Run by double-clicking STOP.bat.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

Write-Host "[1/2] Tat cac dich vu va dong cua so port-forward" -ForegroundColor Cyan
& (Join-Path $root "scripts\ops\mode-stop.ps1")

Write-Host ""
$answer = Read-Host "[2/2] Tat luon Docker Desktop de giai phong RAM? (y = co, Enter = khong)"
if ($answer -match '^(y|yes|c|co)$') {
    Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    wsl --shutdown
    Write-Host "Da tat Docker Desktop va WSL." -ForegroundColor Green
}
else {
    Write-Host "Giu Docker Desktop. Du lieu van con nguyen." -ForegroundColor Green
}
Write-Host "XONG. Lan sau bam START.bat de bat lai." -ForegroundColor Green
