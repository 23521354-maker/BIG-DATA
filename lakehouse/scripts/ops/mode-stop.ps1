$ErrorActionPreference = "Stop"
# Close the port-forward windows opened by START.bat
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*port-forward*" -and $_.ProcessId -ne $PID -and ($_.Name -like "powershell*" -or $_.Name -like "kubectl*") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Scale every Deployment (MySQL, MinIO, Iceberg REST, Spark, Trino, Airflow, Superset) to 0. PVC data is kept.
kubectl -n lakehouse scale deployment --all --replicas=0
kubectl -n lakehouse get deployments
Write-Host "Tat ca Deployment da scale ve 0. PVC van duoc giu." -ForegroundColor Green
