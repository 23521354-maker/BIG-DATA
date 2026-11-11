# Build the Spark image (spark/Dockerfile), load it into every Kubernetes node and redeploy Spark.
# Internet is only needed for the build (jars from Maven Central, libraries from PyPI).
#   .\scripts\dev\build-spark.ps1              build + load into nodes + redeploy Spark
#   .\scripts\dev\build-spark.ps1 -SkipBuild   image already built: only load into nodes + redeploy
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$image = "lakehouse/spark-iceberg:1.0"

if (-not $SkipBuild) {
    Write-Host "[1/3] Build $image (jar hadoop-aws, aws-sdk, pypdf, openpyxl...)"
    docker build -t $image (Join-Path $root "spark")
    if ($LASTEXITCODE -ne 0) { throw "docker build that bai (mang?)." }
}
else {
    Write-Host "[1/3] Bo qua build (-SkipBuild)"
}

Write-Host "[2/3] Nap image vao cac node Kubernetes"
$nodes = @(kubectl get nodes -o custom-columns=NAME:.metadata.name --no-headers | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$archive = Join-Path $env:TEMP "lakehouse-spark.tar"
try {
    docker image save -o $archive $image
    if ($LASTEXITCODE -ne 0) { throw "docker image save that bai (chua build image?)." }
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

Write-Host "[3/3] Deploy Spark"
kubectl apply -f (Join-Path $root "k8s\04-spark.yaml")
kubectl -n lakehouse rollout restart deployment/spark-master deployment/spark-worker
kubectl -n lakehouse rollout status deployment/spark-master --timeout=300s
if ($LASTEXITCODE -ne 0) { throw "spark-master chua san sang: kubectl -n lakehouse describe pod -l app=spark" }
kubectl -n lakehouse rollout status deployment/spark-worker --timeout=300s
if ($LASTEXITCODE -ne 0) { throw "spark-worker chua san sang: kubectl -n lakehouse describe pod -l app=spark" }
kubectl -n lakehouse get pods -l app=spark

Write-Host "SPARK BUILD + DEPLOY HOAN TAT" -ForegroundColor Green
Write-Host "Cap nhat DAG: .\scripts\dev\sync-airflow.ps1   |   Chay thu: .\scripts\data\run-pipeline.ps1"
