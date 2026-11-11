# Cap nhat DAG va file Spark cho Airflow (sua file xong chay lai script nay, khong can build lai image)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

Push-Location $root
try {
    # Khong dung pipe sang kubectl apply de tranh loi ma hoa tieng Viet trong file .py
    kubectl -n lakehouse delete configmap spark-jobs --ignore-not-found | Out-Null
    # Only the .py jobs go into the ConfigMap (Dockerfile and requirements.txt are used to build the image)
    $jobFiles = @(Get-ChildItem -Path "spark" -Filter *.py | ForEach-Object { "--from-file=spark\$($_.Name)" })
    kubectl -n lakehouse create configmap spark-jobs @jobFiles
    if ($LASTEXITCODE -ne 0) { throw "Tao configmap spark-jobs that bai." }

    kubectl -n lakehouse delete configmap airflow-dags --ignore-not-found | Out-Null
    kubectl -n lakehouse create configmap airflow-dags --from-file=airflow\dags
    if ($LASTEXITCODE -ne 0) { throw "Tao configmap airflow-dags that bai." }
}
finally { Pop-Location }

# ConfigMap gan truc tiep vao thu muc DAG lam Airflow bao loi "recursive loop" (symlink ..data),
# nen DAG duoc copy vao emptyDir luc pod khoi dong -> can restart de nhan DAG moi.
$dep = kubectl -n lakehouse get deployment airflow -o name 2>$null
if ($dep) {
    kubectl -n lakehouse rollout restart deployment/airflow
    kubectl -n lakehouse rollout status deployment/airflow --timeout=600s
    Write-Host "Da dong bo DAG + Spark jobs va restart Airflow." -ForegroundColor Green
}
else {
    Write-Host "Da tao ConfigMap DAG + Spark jobs (Airflow chua deploy)." -ForegroundColor Green
}
