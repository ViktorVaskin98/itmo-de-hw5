. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

$Limit = (Get-Content (Join-Path $LogDir "hw3_limit.txt")).Trim()
$Urgent = @{ NAME = "urgent"; NAMESPACE = "hw5"; PRIORITY = "batch-high"; WORKERS = 8; MEMORY = $Limit
    S3_ENDPOINT = "http://rustfs.hw5.svc.cluster.local:9000"; CPU_REQUEST = "2"; CPU_LIMIT = "4" }

Start-Log "07_preemption"
Note "Этап 4б. Вытеснение: фоновый расчёт low (batch-low, сплиты по 64 MiB - 13 задач подольше, по 1 CPU) занимает оба воркера: по 3 пода, свободно по 0,9 CPU. Срочный расчёт из ДЗ 3 (batch-high, requests 2 CPU, предел $Limit из этапа 1) приходит, когда места нет"
kc delete jobs -n hw5 -l "hw5/run in (low, urgent, urgent-verify)" --ignore-not-found | Out-Null
Step { kc get priorityclass -o "custom-columns=NAME:.metadata.name,VALUE:.value,PREEMPTION:.preemptionPolicy,GLOBAL_DEFAULT:.globalDefault" }
$low = Run-Vars "low" @{ PRIORITY = "batch-low"; CHUNK_MB = 64; SPLITS = 13 }
Step { Start-Map $low }
Step { Wait-Running hw5 "hw5/run=low" 6 }
Step { Pods hw5 "hw5/run=low" | Select-Object -First 10 }
& uv run --quiet python -m hhlake.kube.clean --run urgent | Out-Null
Step { "submit at $(Stamp)"; Submit "10-hw3-job.yaml" $Urgent "urgent" }
Step { Watch-Disruption hw5 "hw5/run=low" 10 "low" }
Step { Pods hw5 "hw5/run in (low, urgent)" }
Step { kc -n hw5 get events --field-selector reason=Preempted -o "custom-columns=LAST:.lastTimestamp,POD:.involvedObject.name,MESSAGE:.message" }
Step { "job/urgent -> $(Wait-JobDone hw5 urgent)" }
Save-PodLogs "runs\urgent" hw5 "hw5/run=urgent" | Out-Null
Save-State "runs\urgent" hw5 "hw5/run=urgent"
Step { Show-Log hw5 job/urgent "^\[mem-json\]|^\[mem\] +\d|^ {3,}\d" }
Step { Submit "33-verify-job.yaml" @{ NAME = "urgent-verify"; NAMESPACE = "hw5"; PRIORITY = "batch-high"; PREFIX = "results/k8s/urgent" } "urgent-verify"; "job/urgent-verify -> $(Wait-JobDone hw5 urgent-verify)" }
Step { Show-Log hw5 job/urgent-verify }

Note "Фоновый расчёт после вытеснения: обёртка memwatch переслала SIGTERM процессу map, вытесненные поды завершились с кодом 143 и условием DisruptionTarget; по правилу podFailurePolicy Ignore их индексы созданы заново без траты backoffLimitPerIndex, а сами поды Job-контроллер удалил"
Step { Complete-Run $low }
Step { kc -n hw5 get pods -l hw5/run=low -o "custom-columns=POD:.metadata.name,INDEX:.metadata.annotations.batch\.kubernetes\.io/job-completion-index,NODE:.spec.nodeName,PHASE:.status.phase" --sort-by=.metadata.creationTimestamp }
Step { Show-Job hw5 low-map }
Step { uvpy tools\timeline.py logs\state\runs\low logs\state\runs\urgent }
Step { Show-Log hw5 job/low-commit | Select-Object -Last 15 }
Step { Storage-Memory }
Finish
