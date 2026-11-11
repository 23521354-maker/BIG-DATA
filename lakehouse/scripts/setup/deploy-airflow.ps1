# Deploy Airflow (LocalExecutor, metadata trong MySQL co san, chay Spark bang KubernetesPodOperator)
# Chay lai khi mang loi: .\scripts\setup\deploy-airflow.ps1   (docker pull tai tiep phan con thieu)
# Da co image tren may: .\scripts\setup\deploy-airflow.ps1 -SkipImage
param(
    [switch]$SkipImage
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$image = "apache/airflow:2.11.2"

Write-Host "[1/5] MySQL: tao database va user cho Airflow"
kubectl -n lakehouse scale deployment mysql --replicas=1 | Out-Null
kubectl -n lakehouse rollout status deployment/mysql --timeout=180s
$mysqlPod = (kubectl -n lakehouse get pod -l app=mysql -o jsonpath='{.items[0].metadata.name}').Trim()
$sql = @"
CREATE DATABASE IF NOT EXISTS airflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'airflow'@'%' IDENTIFIED BY 'airflow123';
GRANT ALL PRIVILEGES ON airflow.* TO 'airflow'@'%';
FLUSH PRIVILEGES;
"@
$sql | kubectl -n lakehouse exec -i $mysqlPod -- mysql -uroot -proot123
if ($LASTEXITCODE -ne 0) { throw "Khong tao duoc database airflow trong MySQL." }

if (-not $SkipImage) {
    Write-Host "[2/5] Tai image $image (kha nang nang ~1GB, mang yeu co the lau)"
    docker pull $image
    if ($LASTEXITCODE -ne 0) { throw "docker pull that bai (mang?). Chay lai script de tai tiep." }

    Write-Host "[3/5] Nap image vao cac node Kubernetes"
    $nodes = @(kubectl get nodes -o custom-columns=NAME:.metadata.name --no-headers | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $archive = Join-Path $env:TEMP "lakehouse-airflow.tar"
    try {
        docker image save -o $archive $image
        if ($LASTEXITCODE -ne 0) { throw "docker image save that bai." }
        foreach ($node in $nodes) {
            Write-Host "Import $image vao node $node"
            docker cp $archive "${node}:/var/lakehouse-image.tar"
            docker exec $node ctr --namespace k8s.io images import /var/lakehouse-image.tar
            if ($LASTEXITCODE -ne 0) { throw "Import vao node $node that bai." }
            docker exec $node rm -f /var/lakehouse-image.tar
        }
    }
    finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    }
}
else {
    Write-Host "[2-3/5] Bo qua tai image (-SkipImage)"
}

Write-Host "[4/5] Tao ConfigMap: spark-jobs (spark\) va airflow-dags (airflow\dags\)"
& (Join-Path $root "scripts\dev\sync-airflow.ps1")

Write-Host "[5/5] Deploy Airflow"
kubectl apply -f (Join-Path $root "k8s\06-airflow.yaml")
kubectl -n lakehouse rollout status deployment/airflow --timeout=600s
kubectl -n lakehouse get pods -l app=airflow

Write-Host "AIRFLOW DEPLOY HOAN TAT" -ForegroundColor Green
Write-Host "Mo giao dien: .\scripts\ops\port-forward.ps1 airflow  ->  http://localhost:8082  (admin / admin)"
