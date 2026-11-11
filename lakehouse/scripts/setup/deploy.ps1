$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$image = "lakehouse/iceberg-rest-mysql:1.6.0"
$images = @(
    $image,
    "lakehouse/spark-iceberg:1.0",
    "trinodb/trino:475"
)

& (Join-Path $root "scripts\setup\check-machine.ps1")
$nodes = @(kubectl get nodes -o custom-columns=NAME:.metadata.name --no-headers | ForEach-Object { $_.Trim() } | Where-Object { $_ })

Write-Host "Deploy namespace, MySQL va MinIO"
kubectl apply -f (Join-Path $root "k8s\00-namespace.yaml")
kubectl apply -f (Join-Path $root "k8s\01-mysql.yaml")
kubectl apply -f (Join-Path $root "k8s\02-minio.yaml")
kubectl -n lakehouse rollout status deployment/mysql --timeout=240s
kubectl -n lakehouse rollout status deployment/minio --timeout=240s
kubectl -n lakehouse wait --for=condition=complete job/minio-create-buckets --timeout=240s

Write-Host "Build va pull images"
docker build -t $image (Join-Path $root "iceberg-rest")
docker build -t "lakehouse/spark-iceberg:1.0" (Join-Path $root "spark")
if ($LASTEXITCODE -ne 0) { throw "docker build spark that bai." }
docker pull "trinodb/trino:475"

foreach ($containerImage in $images) {
    $safeName = $containerImage -replace '[^a-zA-Z0-9_.-]', '_'
    $archive = Join-Path $env:TEMP ("lakehouse-" + $safeName + ".tar")
    try {
        docker image save -o $archive $containerImage
        foreach ($node in $nodes) {
            Write-Host "Import $containerImage vao node $node"
            docker cp $archive "${node}:/var/lakehouse-image.tar"
            docker exec $node ctr --namespace k8s.io images import /var/lakehouse-image.tar
            docker exec $node rm -f /var/lakehouse-image.tar
        }
    }
    finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    }
}

Write-Host "Deploy Iceberg REST, Spark va Trino"
kubectl apply -f (Join-Path $root "k8s\03-iceberg-rest.yaml")
kubectl -n lakehouse rollout status deployment/iceberg-rest --timeout=300s
kubectl apply -f (Join-Path $root "k8s\04-spark.yaml")
kubectl apply -f (Join-Path $root "k8s\05-trino.yaml")
kubectl -n lakehouse rollout status deployment/spark-master --timeout=300s
kubectl -n lakehouse rollout status deployment/spark-worker --timeout=300s
kubectl -n lakehouse rollout status deployment/trino-coordinator --timeout=300s
kubectl -n lakehouse rollout status deployment/trino-worker --timeout=300s

kubectl -n lakehouse get deployments
kubectl -n lakehouse get pods -o wide
Write-Host "DEPLOY HOAN TAT" -ForegroundColor Green
