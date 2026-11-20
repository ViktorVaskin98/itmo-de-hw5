. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

$Limit = (Get-Content (Join-Path $LogDir "hw3_limit.txt")).Trim()
$Urgent = @{ NAME = "urgent"; NAMESPACE = "hw5"; PRIORITY = "batch-high"; WORKERS = 8; MEMORY = $Limit
    S3_ENDPOINT = "http://rustfs.hw5.svc.cluster.local:9000"; CPU_REQUEST = "2"; CPU_LIMIT = "4" }

Start-Log "07_preemption"
Note "Этап 4б. Вытеснение: фоновый расчёт low (batch-low, по 1 CPU) занимает оба воркера - по 3 пода, свободно по 0,9 CPU; срочный расчёт из ДЗ 3 (batch-high, requests 2 CPU, предел $Limit из этапа 1) приходит, когда свободного CPU нет"
kc delete jobs -n hw5 -l "hw5/run in (low, urgent, urgent-verify)" --ignore-not-found | Out-Null
Step { kc get priorityclass -o "custom-columns=NAME:.metadata.name,VALUE:.value,PREEMPTION:.preemptionPolicy,DESCRIPTION:.description" }
$low = Run-Vars "low" @{ PRIORITY = "batch-low" }
Step { Start-Map $low }
Step { Wait-Running hw5 "hw5/run=low" 6 }
Step { Pods hw5 "hw5/run=low" | Select-Object -First 10 }
& uv run --quiet python -m hhlake.kube.clean --run urgent | Out-Null
Step { Submit "10-hw3-job.yaml" $Urgent "urgent"; "submitted at $(Stamp)" }
Start-Sleep 3
Step { Pods hw5 "hw5/run in (low, urgent)" | Select-Object -First 14 }
Step { kc -n hw5 get events --field-selector reason=Preempted -o "custom-columns=LAST:.lastTimestamp,POD:.involvedObject.name,MESSAGE:.message" }
Step { "job/urgent -> $(Wait-JobDone hw5 urgent)" }
Save-PodLogs "runs\urgent" hw5 "hw5/run=urgent" | Out-Null
Save-State "runs\urgent" hw5 "hw5/run=urgent"
Step { Show-Log hw5 job/urgent "^\[mem-json\]|^\[mem\] +\d|^ {3,}\d" }
Step { Submit "33-verify-job.yaml" @{ NAME = "urgent-verify"; NAMESPACE = "hw5"; PRIORITY = "batch-high"; PREFIX = "results/k8s/urgent" } "urgent-verify"; "job/urgent-verify -> $(Wait-JobDone hw5 urgent-verify)" }
Step { Show-Log hw5 job/urgent-verify }

Note "Фоновый расчёт после вытеснения: вытесненные поды получили условие DisruptionTarget, по правилу podFailurePolicy Ignore их индексы перезапущены без траты backoffLimitPerIndex"
Step { Complete-Run $low }
Step { kc -n hw5 get pods -l hw5/run=low --field-selector status.phase=Failed -o "custom-columns=POD:.metadata.name,NODE:.spec.nodeName,EXIT:.status.containerStatuses[0].state.terminated.exitCode,REASON:.status.conditions[?(@.type=='DisruptionTarget')].reason,MESSAGE:.status.conditions[?(@.type=='DisruptionTarget')].message" }
Step { Show-Job hw5 low-map }
Step { uvpy tools\timeline.py logs\state\runs\low logs\state\runs\urgent }
Step { Show-Log hw5 job/low-commit | Select-Object -Last 15 }
Step { Storage-Memory }
Finish
