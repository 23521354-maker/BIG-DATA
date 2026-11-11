# One command: start Docker Desktop (if needed) -> start every service -> open port-forwards -> open web UIs.
# Run by double-clicking START.bat in the project root, or: .\scripts\ops\start-all.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$ns = "lakehouse"

function Test-Cluster {
    kubectl get nodes 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-Port([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $Port)
        $c.Close()
        return $true
    }
    catch { return $false }
}

Write-Host "[1/4] Kiem tra Docker Desktop + Kubernetes" -ForegroundColor Cyan
if (-not (Test-Cluster)) {
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path -LiteralPath $dd) {
        Write-Host "Docker Desktop chua chay, dang mo..."
        Start-Process $dd
    }
    else {
        Write-Host "Khong tim thay Docker Desktop. Hay mo no bang tay." -ForegroundColor Yellow
    }
    $ready = $false
    for ($i = 1; $i -le 48; $i++) {
        Start-Sleep -Seconds 5
        if (Test-Cluster) { $ready = $true; break }
        Write-Host "  cho Kubernetes san sang... ($($i * 5)s)"
    }
    if (-not $ready) { throw "Kubernetes chua san sang sau 4 phut. Mo Docker Desktop, doi bieu tuong xanh roi chay lai START.bat." }
}
kubectl config use-context docker-desktop | Out-Null

Write-Host "[2/4] Bat tat ca dich vu (3-6 phut neu moi mo may)" -ForegroundColor Cyan
& (Join-Path $root "scripts\ops\mode-full.ps1")

Write-Host "[3/4] Mo cac cong (port-forward) trong cua so thu nho" -ForegroundColor Cyan
$pf = Join-Path $root "scripts\ops\port-forward.ps1"
$services = @(
    @{ Name = "minio";    Deploy = "minio";        Port = 9001; Path = "" },
    @{ Name = "spark";    Deploy = "spark-master"; Port = 8081; Path = "" },
    @{ Name = "trino";    Deploy = "trino-coordinator"; Port = 8080; Path = "" },
    @{ Name = "airflow";  Deploy = "airflow";      Port = 8082; Path = "" },
    @{ Name = "superset"; Deploy = "superset";     Port = 8088; Path = "" }
)
# Close old port-forward windows first so ports are free
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*port-forward*" -and $_.ProcessId -ne $PID -and ($_.Name -like "powershell*" -or $_.Name -like "kubectl*") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$opened = @()
foreach ($s in $services) {
    $exists = kubectl -n $ns get deployment $s.Deploy -o name 2>$null
    if (-not $exists) { Write-Host "  bo qua $($s.Name) (chua cai)"; continue }
    # The script path MUST be quoted: the project folder name contains a space ("lakehouse-AI embedded")
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$pf`" $($s.Name)"
    $opened += $s
}

Write-Host "[4/4] Mo giao dien tren trinh duyet (cho toi da 2 phut)" -ForegroundColor Cyan
# Wait for all ports together (not 40 s each one after another); open each UI as soon as its port answers.
$pending = [System.Collections.ArrayList]@($opened)
$until = (Get-Date).AddSeconds(120)
while ($pending.Count -gt 0 -and (Get-Date) -lt $until) {
    foreach ($s in @($pending)) {
        if (Test-Port $s.Port) {
            Start-Process "http://localhost:$($s.Port)"
            Write-Host ("  {0,-9} http://localhost:{1}" -f $s.Name, $s.Port) -ForegroundColor Green
            $pending.Remove($s) | Out-Null
        }
    }
    if ($pending.Count -gt 0) { Start-Sleep -Seconds 1 }
}
foreach ($s in $pending) {
    Write-Host ("  {0,-9} chua mo duoc cong {1}. Loi gan nhat cua port-forward:" -f $s.Name, $s.Port) -ForegroundColor Yellow
    $log = Join-Path $env:TEMP "lakehouse-pf-$($s.Name).log"
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 3 | ForEach-Object { Write-Host "      $_" } }
    else { Write-Host "      (khong co log: cua so port-forward khong khoi dong duoc)" }
}
if ($pending.Count -gt 0) { Write-Host "  Chup man hinh phan loi tren de kiem tra, hoac chay lai START.bat." -ForegroundColor Yellow }

Write-Host ""
Write-Host "LAKEHOUSE DA SAN SANG" -ForegroundColor Green
Write-Host "  MinIO    admin / password123     Airflow  admin / admin"
Write-Host "  Superset admin / admin           Trino    user: admin (khong mat khau)"
Write-Host "Cac cua so PowerShell thu nho dang giu ket noi: dung dong chung. Tat het: .\scripts\ops\mode-stop.ps1"
