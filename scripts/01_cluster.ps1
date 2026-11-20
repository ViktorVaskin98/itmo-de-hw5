. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

$KindUrl = "https://github.com/kubernetes-sigs/kind/releases/download/$KindVersion/kind-windows-amd64"
$Dl = Join-Path $Tools "_dl"
New-Item -ItemType Directory -Force $Dl, (Split-Path $Kind) | Out-Null
if (-not (Test-Path "$Dl\kind-windows-amd64")) {
    curl.exe -sSL -o "$Dl\kind-windows-amd64" $KindUrl
    curl.exe -sSL -o "$Dl\kind-windows-amd64.sha256sum" "$KindUrl.sha256sum"
}

Start-Log "01_cluster"
Note "Этап 0. kind $KindVersion с GitHub, проверка sha256; kubectl - из Docker Desktop"
Step { (Get-FileHash "$Dl\kind-windows-amd64" -Algorithm SHA256).Hash.ToLower() -eq (Get-Content "$Dl\kind-windows-amd64.sha256sum").Split(" ")[0] }
if (-not (Test-Path $Kind)) { Copy-Item "$Dl\kind-windows-amd64" $Kind }
Step { kind version; kubectl version --client }
Step { $cs = Get-CimInstance Win32_ComputerSystem; "host: $($cs.NumberOfLogicalProcessors) logical CPU, $([math]::Round($cs.TotalPhysicalMemory / 1GB, 1)) GiB RAM, $((Get-CimInstance Win32_OperatingSystem).Caption)" }
Step { docker info --format "Docker {{.ServerVersion}}, VM: {{.NCPU}} CPU, {{.MemTotal}} bytes RAM, cgroup v{{.CgroupVersion}}, kernel {{.KernelVersion}}" }

Note "Кластер: control-plane (на нём же хранилище) и два воркера; у воркеров system-reserved cpu=8, memory=5Gi, остаётся по 4 CPU для заданий"
if ((& $Kind get clusters 2>$null) -contains $Cluster) { kind delete cluster --name $Cluster | Out-Null }
Step { Get-Content cluster\kind.yaml }
Step { kind create cluster --config cluster\kind.yaml }
Step { kc wait --for=condition=Ready nodes --all --timeout=180s }
Step { kc get nodes -o wide }
Step { kc get nodes -o "custom-columns=NODE:.metadata.name,POOL:.metadata.labels.hw5/pool,CPU:.status.capacity.cpu,ALLOC_CPU:.status.allocatable.cpu,MEMORY:.status.capacity.memory,ALLOC_MEMORY:.status.allocatable.memory,TAINTS:.spec.taints[*].key" }
Step { kc get storageclass }

Note "Хранилище из ДЗ 2-3 (контейнер rustfs-lab, бакет hh-lake) подключаю к docker-сети kind: до переноса задания читают его по имени rustfs-lab"
Step { docker ps --filter name=rustfs-lab --format "{{.Names}} {{.Image}} {{.Status}}" }
& docker network disconnect kind rustfs-lab 2>$null
Step { docker network connect kind rustfs-lab; docker network inspect kind --format "{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}" }
kc delete pod dnscheck --ignore-not-found | Out-Null
Step { kc run dnscheck --image=busybox:1.37 --restart=Never --command '--' sh -c "nslookup rustfs-lab. | tail -3; wget -q -O - http://rustfs-lab:9000/health" }
Step { kc wait --for=jsonpath="{.status.phase}=Succeeded" pod/dnscheck --timeout=120s }
Step { kc logs dnscheck }
$dns = & kubectl --context $Ctx logs dnscheck 2>$null
kc delete pod dnscheck | Out-Null
if (-not ($dns -match '"status":"ok"')) { Fail "rustfs-lab недоступен из пода" }
Finish
