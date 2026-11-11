param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet("minio", "minio-api", "spark", "trino", "airflow", "superset")]
    [string]$Service
)

# kubectl port-forward hay bi dut (broken pipe / lost connection to pod) tren Docker Desktop.
# Script tu noi lai sau 2 giay. Dung hoan toan: Ctrl+C.
$ErrorActionPreference = "Continue"
switch ($Service) {
    "minio"    { $fwd = @("service/minio", "9001:9001") }
    "minio-api" { $fwd = @("service/minio", "9000:9000") }   # S3 API, used by python -m ai.store
    "spark"    { $fwd = @("service/spark-master", "8081:8080") }
    "trino"    { $fwd = @("service/trino", "8080:8080") }
    "airflow"  { $fwd = @("service/airflow", "8082:8080") }
    "superset" { $fwd = @("service/superset", "8088:8088") }
}

# Log to %TEMP%\lakehouse-pf-<service>.log so START.bat can show why a port did not open
$log = Join-Path $env:TEMP "lakehouse-pf-$Service.log"
"$(Get-Date -Format s) start port-forward $Service" | Out-File -FilePath $log -Encoding ascii
while ($true) {
    kubectl -n lakehouse port-forward @fwd 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
    Write-Host "[port-forward $Service] mat ket noi, noi lai sau 2 giay (Ctrl+C de dung)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
}
