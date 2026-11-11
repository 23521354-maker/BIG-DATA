# Bat toan bo: MySQL, MinIO, Iceberg REST, Spark, Trino (+ Airflow neu da deploy)
# Can ~16GB RAM cho WSL. Tat bot: mode-etl.ps1 / mode-bi.ps1 / mode-stop.ps1
$ErrorActionPreference = "Stop"
$core = @("mysql", "minio", "iceberg-rest", "spark-master", "spark-worker", "trino-coordinator", "trino-worker")
$extra = @()
foreach ($name in @("airflow", "superset")) {
    $found = kubectl -n lakehouse get deployment $name -o name 2>$null
    if ($found) { $extra += $name }
}
$all = $core + $extra
kubectl -n lakehouse scale deployment $all --replicas=1
foreach ($d in $all) {
    kubectl -n lakehouse rollout status "deployment/$d" --timeout=600s
}
kubectl -n lakehouse get pods
