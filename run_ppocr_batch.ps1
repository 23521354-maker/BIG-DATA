# Overnight PP-OCR batch (offline ingestion step, takes hours). Safe to Ctrl+C and re-run (resumes).
# Creates its own virtualenv (.venv-ocr) and caches (.cache-ocr) next to this script; both are git-ignored.
param([string]$Until = "05:00", [switch]$Shutdown, [switch]$Extra)
$ErrorActionPreference = "Continue"
$root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$work  = Join-Path $root ".cache-ocr"; $venv = Join-Path $root ".venv-ocr"
$env:PIP_CACHE_DIR = Join-Path $work "pip_cache"
$env:PADDLE_PDX_CACHE_HOME = Join-Path $work "paddlex_cache"
$env:HF_HOME = Join-Path $work "hf_cache"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:FLAGS_use_mkldnn = "0"
$env:OMP_NUM_THREADS = "12"; $env:MKL_NUM_THREADS = "12"; $env:OPENBLAS_NUM_THREADS = "12"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "Creating virtualenv $venv and installing requirements-ingestion.txt (one time)..." -ForegroundColor Cyan
    python -m venv $venv
    & $vpy -m pip install -r (Join-Path $root "requirements-ingestion.txt") --timeout 60 --retries 10
}
& $vpy -c "import pymupdf" 2>$null
if ($LASTEXITCODE -ne 0) { & $vpy -m pip install pymupdf --timeout 60 --retries 10 }
# keep PC awake while plugged in
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 15 | Out-Null
Write-Host "Running until $Until. Progress prints every 10 pages." -ForegroundColor Cyan
$extraArg = @(); if ($Extra) { $extraArg = @("--extra") }
& $vpy (Join-Path $root "ppocr_batch.py") --until $Until @extraArg
$code = $LASTEXITCODE
if ($Shutdown) {
    $n = @(Get-ChildItem (Join-Path $root "ocr_batch\pages") -Filter *.json -ErrorAction SilentlyContinue).Count
    if ($n -gt 0) {
        Write-Host "Done ($n pages saved). Shutting down in 120s. To cancel run: shutdown /a" -ForegroundColor Yellow
        shutdown /s /t 120
    } else {
        Write-Host "No pages were saved (exit code $code) - NOT shutting down so you can read the error." -ForegroundColor Red
    }
}
