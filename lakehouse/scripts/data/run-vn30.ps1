# Run the VN30 Spark jobs by hand (without Airflow): Raw -> Bronze -> Silver -> Gold -> check.
#   .\scripts\data\run-vn30.ps1                         all four jobs
#   .\scripts\data\run-vn30.ps1 -Jobs vn30_silver,vn30_gold,vn30_check
param(
    [string[]]$Jobs = @("vn30_bronze", "vn30_silver", "vn30_gold", "vn30_check")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

& (Join-Path $root "scripts\ops\mode-etl.ps1")
$sparkPod = (kubectl -n lakehouse get pod -l "app=spark,role=master" -o jsonpath='{.items[0].metadata.name}').Trim()

$submitTemplate = @'
export AWS_REGION=us-east-1 AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=password123
cd /tmp
IP=$(hostname -i)
/opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --driver-memory 512m \
  --executor-memory 512m \
  --total-executor-cores 1 \
  --conf spark.driver.host=$IP \
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
  --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
  --conf spark.hadoop.fs.s3a.access.key=admin \
  --conf spark.hadoop.fs.s3a.secret.key=password123 \
  --conf spark.hadoop.fs.s3a.path.style.access=true \
  --conf spark.hadoop.fs.s3a.connection.ssl.enabled=false \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.lakehouse.type=rest \
  --conf spark.sql.catalog.lakehouse.uri=http://iceberg-rest:8181 \
  --conf spark.sql.catalog.lakehouse.warehouse=s3://warehouse/ \
  --conf spark.sql.defaultCatalog=lakehouse \
  --conf spark.sql.catalog.lakehouse.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
  --conf spark.sql.catalog.lakehouse.s3.endpoint=http://minio:9000 \
  --conf spark.sql.catalog.lakehouse.s3.path-style-access=true \
  /tmp/__JOB__.py
'@

foreach ($job in $Jobs) {
    Write-Host "=== $job ===" -ForegroundColor Cyan
    Push-Location $root
    try { kubectl cp "spark\$job.py" "lakehouse/${sparkPod}:/tmp/$job.py" } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "kubectl cp that bai: $job" }
    kubectl -n lakehouse exec $sparkPod -- sh -lc ($submitTemplate -replace "__JOB__", $job)
    if ($LASTEXITCODE -ne 0) { throw "Spark job that bai: $job" }
}
Write-Host "VN30 SPARK JOBS HOAN TAT: $($Jobs -join ', ')" -ForegroundColor Green
