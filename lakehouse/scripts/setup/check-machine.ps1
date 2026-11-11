$ErrorActionPreference = "Stop"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Khong tim thay lenh '$Name'. Hay cai dat/bo sung PATH truoc."
    }
}

Assert-Command docker
Assert-Command kubectl

Write-Host "[1/4] Kiem tra Docker Engine"
docker info | Out-Null

Write-Host "[2/4] Kiem tra context docker-desktop"
$contexts = @(kubectl config get-contexts -o name)
if ($contexts -notcontains "docker-desktop") {
    throw "Khong co context docker-desktop. Hay bat Kubernetes trong Docker Desktop."
}
kubectl config use-context docker-desktop | Out-Null

Write-Host "[3/4] Kiem tra node"
$nodes = @(kubectl get nodes -o custom-columns=NAME:.metadata.name --no-headers | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($nodes.Count -lt 2) {
    throw "Can toi thieu 2 node Kubernetes. Hien tai chi co $($nodes.Count) node."
}
kubectl get nodes

Write-Host "[4/4] Kiem tra RAM Windows"
$os = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
Write-Host "RAM tong: $totalGB GB; RAM trong: $freeGB GB"
if ($totalGB -lt 12) {
    Write-Warning "May duoi 12 GB RAM. Chi nen bat luan phien Spark va Trino."
}

Write-Host "May da san sang." -ForegroundColor Green
