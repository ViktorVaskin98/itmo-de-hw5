. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

function Mark-Kernel([string]$Node, [string]$Mark) {
    docker exec $Node sh -c "echo hw5-mark-$Mark > /dev/kmsg"
}

function Kernel-Oom([string]$Node, [string]$Mark) {
    $lines = @(docker exec $Node dmesg)
    $from = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match "hw5-mark-$Mark$") { $from = $i } }
    $lines | Select-Object -Skip ($from + 1) | ForEach-Object {
        if ($_ -match 'invoked oom-killer|memory: usage|Memory cgroup out of memory|oom-kill:') {
            $_ -replace 'oom_memcg=\S+?(kubepods-burstable-pod[^,/]+)\S*?,', 'oom_memcg=.../$1,' -replace ',task_memcg=\S+', ''
        }
    }
}

function Run-Hw3([string]$Name, [string]$Memory) {
    Submit "10-hw3-job.yaml" ($Hw3 + @{ NAME = $Name; MEMORY = $Memory }) $Name
    $state = Wait-JobDone hw5 $Name
    Save-PodLogs "hw3\$Name" hw5 "hw5/run=$Name" | Out-Null
    Save-State "hw3\$Name" hw5 "hw5/run=$Name"
    "job/$Name -> $state"
}

$Hw3 = @{ NAMESPACE = "hw5"; PRIORITY = "batch-low"; WORKERS = 8; S3_ENDPOINT = "http://rustfs-lab:9000"; CPU_REQUEST = "2"; CPU_LIMIT = "4" }

Start-Log "03_memory"
Note "Этап 1. Расчёт из ДЗ 3 как задание Kubernetes: мастер и 8 воркеров в одном контейнере, хранилище пока снаружи кластера (rustfs-lab). Обёртка hhlake.kube.memwatch читает память своего cgroup каждые 0.1 с"
kc delete jobs -n hw5 -l hw5/stage=hw3-job --ignore-not-found | Out-Null
Step { kc apply -f k8s\00-namespace.yaml -f k8s\05-priority.yaml }
Note "Мастер ДЗ 3 перед расчётом удаляет свой выходной префикс в rustfs-lab по одному объекту (~1 с на объект в RustFS); выводы прошлых прогонов удаляю заранее пакетом, чтобы это не попадало в замер"
$env:S3_ENDPOINT = $HostS3
Step { uvpy -m hhlake.kube.clean --prefix results/k8s }
Step { Get-Content k8s\10-hw3-job.yaml }

Note "Запуск 1: предел 256Mi. В ДЗ 3 пик одного процесса был 91-97 MiB, но процессов в контейнере десять"
$nodes = "hw5-worker", "hw5-worker2"
foreach ($n in $nodes) { Mark-Kernel $n "hw3-256mi" }
Step { Run-Hw3 "hw3-256mi" "256Mi" }
Step { Show-Job hw5 hw3-256mi }
Step { kc -n hw5 get pods -l hw5/run=hw3-256mi -o "custom-columns=POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,REASON:.status.containerStatuses[0].state.terminated.reason,EXIT:.status.containerStatuses[0].state.terminated.exitCode,QOS:.status.qosClass" }
Step { Show-Log hw5 job/hw3-256mi }
Step { kc -n hw5 get events --field-selector involvedObject.name=hw3-256mi }
$oomNode = & kubectl --context $Ctx -n hw5 get pods -l hw5/run=hw3-256mi -o "jsonpath={.items[0].spec.nodeName}"
Note "Ядро на узле ${oomNode}: OOM внутри cgroup пода; memory.oom.group=1, поэтому убиты все процессы контейнера, а не самый большой"
Step { Kernel-Oom $oomNode "hw3-256mi" }

Note "Замер пика: три запуска с пределом 2Gi (заведомо с запасом)"
foreach ($i in 1..3) {
    Step ([scriptblock]::Create("Run-Hw3 hw3-measure-$i 2Gi"))
}
Step { Show-Log hw5 job/hw3-measure-1 }
Step { uvpy -m hhlake.kube.sizing logs\pods\hw3\hw3-measure-1 logs\pods\hw3\hw3-measure-2 logs\pods\hw3\hw3-measure-3 }
$Limit = (& uv run --quiet python -m hhlake.kube.sizing logs\pods\hw3\hw3-measure-1 logs\pods\hw3\hw3-measure-2 logs\pods\hw3\hw3-measure-3 --quiet).Trim()
$Anon = [int](& uv run --quiet python -m hhlake.kube.sizing logs\pods\hw3\hw3-measure-1 logs\pods\hw3\hw3-measure-2 logs\pods\hw3\hw3-measure-3 --anon-only)
Note "Подобранный предел: $Limit (requests = limits по памяти). Проверка: три запуска с ним"

foreach ($i in 1..3) {
    Step ([scriptblock]::Create("Run-Hw3 hw3-tuned-$i $Limit"))
}
Step { kc -n hw5 get jobs -l hw5/stage=hw3-job -o "custom-columns=JOB:.metadata.name,SUCCEEDED:.status.succeeded,FAILED:.status.failed,START:.status.startTime,END:.status.completionTime" }
Step { uvpy -m hhlake.kube.sizing logs\pods\hw3\hw3-tuned-1 logs\pods\hw3\hw3-tuned-2 logs\pods\hw3\hw3-tuned-3 }
Step { Select-String -Path logs\pods\hw3\hw3-tuned-*\*.log -Pattern "memory.events|\[cpu\]" | ForEach-Object { "$($_.Filename): $($_.Line)" } }
Step { Show-Log hw5 job/hw3-tuned-1 "^\[mem-json\]|^\[mem\] +\d" }
Note "Результат запуска с подобранным пределом против вывода ДЗ 3 в том же rustfs-lab"
Step { uvpy -m hhlake.verify --a results/k8s/hw3-tuned-1 --b results/mapreduce --top 10 }

$Below = "$([int]([math]::Floor($Anon / 64) * 64))Mi"
Note "Граница снизу: предел $Below - ниже пика анонимной памяти ($Anon MiB), которую ядро не может вытеснить, как кэш файлов"
foreach ($n in $nodes) { Mark-Kernel $n "hw3-below" }
Step ([scriptblock]::Create("Run-Hw3 hw3-below $Below"))
Step { kc -n hw5 get pods -l hw5/run=hw3-below -o "custom-columns=POD:.metadata.name,NODE:.spec.nodeName,REASON:.status.containerStatuses[0].state.terminated.reason,EXIT:.status.containerStatuses[0].state.terminated.exitCode" }
Step { Show-Log hw5 job/hw3-below | Select-Object -Last 6 }
$oomNode = & kubectl --context $Ctx -n hw5 get pods -l hw5/run=hw3-below -o "jsonpath={.items[0].spec.nodeName}"
Step { Kernel-Oom $oomNode "hw3-below" | Select-Object -First 3 }
Set-Content (Join-Path $LogDir "hw3_limit.txt") $Limit -Encoding ascii
Finish
