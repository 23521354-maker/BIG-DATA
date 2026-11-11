# Run one SQL statement on Trino from the command line (no port-forward needed).
# Trino must be running: .\scripts\ops\mode-full.ps1 (run-vn30.ps1 switches Trino off through mode-etl.ps1).
#   .\scripts\ops\trino-query.ps1 "SELECT ticker, fiscal_year, net_profit_after_tax_bn FROM iceberg.vn30_gold.company_year_metrics WHERE ticker = 'VCB' ORDER BY fiscal_year"
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Sql
)
$ErrorActionPreference = "Stop"
$pods = @(kubectl -n lakehouse get pod -l "app=trino,role=coordinator" -o name 2>$null)
if ($pods.Count -eq 0) {
    throw "Trino chua chay. Chay .\scripts\ops\mode-full.ps1 (doi vai phut) roi thu lai."
}
$pod = ($pods[0] -replace '^pod/', '')
kubectl -n lakehouse exec $pod -- trino --execute $Sql
