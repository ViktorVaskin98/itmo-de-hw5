. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

$env:S3_ENDPOINT = $ClusterS3
$Splits = [int](& uv run --quiet python -m hhlake.kube.plan --chunk-mb 32 --quiet)

Start-Log "05_parallel"
Note "Этап 3. Расчёт параллельными заданиями: Indexed Job map (индекс пода = номер сплита по 32 MiB), Indexed Job reduce (индекс = партиция), задание commit сводит счётчики и сверяет результат с ДЗ 3"
Step { Get-Content k8s\30-map-job.yaml }
Step { "splits: $Splits" }
kc delete jobs -n hw5 -l "hw5/run in (probe, par)" --ignore-not-found | Out-Null

Note "Пробный прогон с пределом 512Mi на под: замер пика map и reduce"
$probe = Run-Vars "probe" @{ SPLITS = $Splits; MEMORY = "512Mi"; REDUCE_MEMORY = "512Mi" }
Step { Start-Map $probe }
Step { Complete-Run $probe }
Step { uvpy -m hhlake.kube.sizing (Get-ChildItem logs\pods\runs\probe\probe-map-*.log).FullName }
Step { uvpy -m hhlake.kube.sizing (Get-ChildItem logs\pods\runs\probe\probe-reduce-*.log).FullName }
$mapLimit = (& uv run --quiet python -m hhlake.kube.sizing (Get-ChildItem logs\pods\runs\probe\probe-map-*.log).FullName --quiet).Trim()
$reduceLimit = (& uv run --quiet python -m hhlake.kube.sizing (Get-ChildItem logs\pods\runs\probe\probe-reduce-*.log).FullName --quiet).Trim()
@{ SPLITS = $Splits; MEMORY = $mapLimit; REDUCE_MEMORY = $reduceLimit } | ConvertTo-Json | Set-Content (Join-Path $LogDir "run_limits.json") -Encoding ascii
Note "Пределы по пику: map $mapLimit, reduce $reduceLimit; сохранены в logs/run_limits.json для этапов 4-6"

$par = Run-Vars "par" @{ SPLITS = $Splits; MEMORY = $mapLimit; REDUCE_MEMORY = $reduceLimit }
Step { Start-Map $par }
Note "Одновременно работают 6 подов, а не 8: у воркера allocatable 4 CPU, но 100m уже запросил под kindnet (DaemonSet сети), и четвёртый под с 1 CPU не помещается"
Step { Wait-Running hw5 "hw5/run=par" 6 }
Step { kc describe node hw5-worker | Select-String -Pattern "Non-terminated Pods:" -Context 0,10 }
Step { Pods hw5 "hw5/run=par" | Select-Object -First 12 }
Step { Complete-Run $par }
Step { Show-Job hw5 par-map; Show-Job hw5 par-reduce }
Step { kc -n hw5 get pods -l hw5/run=par -o "custom-columns=POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,INDEX:.metadata.annotations.batch\.kubernetes\.io/job-completion-index" | Select-Object -First 8 }
Step { uvpy tools\timeline.py logs\state\runs\par }
Step { Get-Content logs\pods\runs\par\par-map-7-*.log | Where-Object { $_ -notmatch "^\[mem-json\]" } }
Step { Get-Content logs\pods\runs\par\par-reduce-0-*.log | Where-Object { $_ -notmatch "^\[mem-json\]" } }
Step { Show-Log hw5 job/par-commit }
Note "Прямая сверка с файлом из репозитория ДЗ 3: выгружаю частоты пар этого прогона тем же способом, что в ДЗ 3 (--export), и сравниваю побайтно"
$env:S3_ENDPOINT = $ClusterS3
Remove-Item -Recurse -Force work\par_stacks -ErrorAction SilentlyContinue
Step { uvpy -m hhlake.verify --a results/k8s/par --b results/hw3/mapreduce --export work\par_stacks | Select-Object -Last 2 }
Step { foreach ($n in "skills", "pairs", "triples") { "$n.csv: $((Get-FileHash work\par_stacks\$n.csv).Hash -eq (Get-FileHash (Join-Path $Hw3Stacks "$n.csv")).Hash)" } }
Step { Get-Content work\par_stacks\pairs.csv -TotalCount 11 -Encoding UTF8 }
Step { Storage-Memory }
Finish
