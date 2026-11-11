$ErrorActionPreference = "Stop"
$ns = "lakehouse"

Write-Host "=== NODES ==="
kubectl get nodes -o wide

Write-Host "=== DEPLOYMENTS / PODS / PVC ==="
kubectl -n $ns get deployments
kubectl -n $ns get pods -o wide
kubectl -n $ns get pvc

Write-Host "=== BUCKETS ==="
$minioPod = (kubectl -n $ns get pod -l app=minio -o jsonpath='{.items[0].metadata.name}').Trim()
kubectl -n $ns exec $minioPod -- sh -lc 'mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc ls local'

Write-Host "=== MYSQL CATALOG TABLES ==="
$mysqlPod = (kubectl -n $ns get pod -l app=mysql -o jsonpath='{.items[0].metadata.name}').Trim()
kubectl -n $ns exec $mysqlPod -- mysql -uiceberg -piceberg123 iceberg -e "SHOW TABLES;"

$trinoPods = @(kubectl -n $ns get pod -l app=trino,role=coordinator -o name)
if ($trinoPods.Count -gt 0) {
    Write-Host "=== TRINO ==="
    $trinoPod = ($trinoPods[0] -replace '^pod/', '')
    kubectl -n $ns exec $trinoPod -- trino --execute "SHOW CATALOGS; SHOW SCHEMAS FROM iceberg;"

    $schemas = kubectl -n $ns exec $trinoPod -- trino --output-format TSV --execute "SHOW SCHEMAS FROM iceberg;"
    foreach ($schema in @("vn30_bronze", "vn30_silver", "vn30_gold")) {
        if ($schemas -contains $schema) {
            Write-Host "--- iceberg.$schema ---"
            kubectl -n $ns exec $trinoPod -- trino --execute "SHOW TABLES FROM iceberg.$schema;"
        }
        else {
            Write-Host "Schema iceberg.$schema chua co (binh thuong neu chua chay pipeline)." -ForegroundColor Yellow
        }
    }
}

Write-Host "VERIFY HOAN TAT" -ForegroundColor Green
