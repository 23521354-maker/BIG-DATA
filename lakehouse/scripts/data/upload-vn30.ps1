# Upload the VN30 source files to MinIO bucket raw (raw/vn30/).
#   extract\text\*.json                  page text of every annual report (text layer + OCR)   -> raw/vn30/extract/text/
#   extract\financial_indicators.csv     extractor output before the CafeF cross-check
#   extract\cafef_bctc_nam_*.csv         CafeF annual figures
#   pdf\<TICKER>\*.pdf                   the 154 annual-report PDFs (about 2 GB)               -> raw/vn30/pdf/<TICKER>/
#
#   .\scripts\data\upload-vn30.ps1                  everything (PDFs already in MinIO are skipped)
#   .\scripts\data\upload-vn30.ps1 -SkipPdf         only the small files that the Bronze job reads
#   .\scripts\data\upload-vn30.ps1 -DataRoot "E:\BIG DATA"   if the data lives somewhere else
param(
    [string]$DataRoot,
    [switch]$SkipPdf
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (-not $DataRoot) { $DataRoot = Split-Path -Parent $root }   # data (extract/, pdf/) sits one level above the lakehouse folder
$ex = Join-Path $DataRoot "extract"
if (-not (Test-Path -LiteralPath (Join-Path $ex "financial_indicators.csv"))) { throw "Khong tim thay $ex\financial_indicators.csv (dung -DataRoot)." }

kubectl -n lakehouse scale deployment minio --replicas=1 | Out-Null
kubectl -n lakehouse rollout status deployment/minio --timeout=180s
$minioPod = (kubectl -n lakehouse get pod -l app=minio -o jsonpath='{.items[0].metadata.name}').Trim()
kubectl -n lakehouse exec $minioPod -- sh -lc 'mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mb --ignore-existing local/raw'
if ($LASTEXITCODE -ne 0) { throw "Khong dat duoc mc alias." }

function Send-File([string]$Path, [string]$Target) {
    # MinIO image has no tar, so kubectl cp does not work: stream the file through stdin into mc pipe
    cmd /c "kubectl -n lakehouse exec -i $minioPod -- mc pipe local/raw/$Target < `"$Path`""
    if ($LASTEXITCODE -ne 0) { throw "Upload $Path that bai." }
}

# 1) the small files read by vn30_bronze.py
$csvs = @("financial_indicators.csv", "cafef_bctc_nam_2022_2025.csv", "cafef_bctc_nam_2020_2021.csv")
foreach ($c in $csvs) {
    Write-Host "Upload extract/$c"
    Send-File (Join-Path $ex $c) "vn30/extract/$c"
}
$jsons = @(Get-ChildItem -LiteralPath (Join-Path $ex "text") -Filter *.json)
Write-Host "Upload $($jsons.Count) file page-text JSON (extract/text/)"
$i = 0
foreach ($f in $jsons) {
    Send-File $f.FullName "vn30/extract/text/$($f.Name)"
    $i++
    if ($i % 20 -eq 0) { Write-Host "  $i / $($jsons.Count)" }
}

# 2) the raw PDFs (skipped when already in MinIO)
if (-not $SkipPdf) {
    $pdfRoot = Join-Path $DataRoot "pdf"
    $pdfs = @(Get-ChildItem -LiteralPath $pdfRoot -Recurse -Filter *.pdf)
    $existing = @(kubectl -n lakehouse exec $minioPod -- mc ls --recursive local/raw/vn30/pdf/ 2>$null | ForEach-Object { ($_ -split '\s+')[-1] })
    Write-Host "PDF: $($pdfs.Count) file, $($existing.Count) da co trong MinIO"
    $n = 0
    foreach ($p in $pdfs) {
        $rel = "$($p.Directory.Name)/$($p.Name)"
        if ($existing -contains $rel) { continue }
        Write-Host "Upload pdf/$rel ($([math]::Round($p.Length / 1MB, 1)) MB)"
        Send-File $p.FullName "vn30/pdf/$rel"
        $n++
    }
    Write-Host "Da upload them $n PDF."
}

kubectl -n lakehouse exec $minioPod -- sh -lc 'mc ls local/raw/vn30/ && mc du local/raw/vn30/'
Write-Host "UPLOAD VN30 HOAN TAT" -ForegroundColor Green
