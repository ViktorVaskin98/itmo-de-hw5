. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

Start-Log "06_cpu"
Note "Этап 4а. Нехватка процессора: тот же map, но каждый под просит 1500m CPU, а у воркера allocatable 4 CPU - за вычетом 100m kindnet на узел помещается два пода (3 CPU), оставшиеся 0,9 CPU никому не подходят"
kc delete jobs -n hw5 -l hw5/run=cpu --ignore-not-found | Out-Null
$cpu = Run-Vars "cpu" @{ CPU = "1500m" }
Step { Start-Map $cpu }
Step { Wait-Running hw5 "hw5/run=cpu" 4 }
Start-Sleep 2
Step { Pods hw5 "hw5/run=cpu" | Select-Object -First 10 }
Step { kc -n hw5 get events --field-selector reason=FailedScheduling -o "custom-columns=LAST:.lastTimestamp,POD:.involvedObject.name,COUNT:.count,MESSAGE:.message" | Select-Object -First 5 }
Step { kc describe node hw5-worker | Select-String -Pattern "Allocatable:" -Context 0,6 }
Step { kc describe node hw5-worker | Select-String -Pattern "Allocated resources:" -Context 0,6 }
Step { Complete-Run $cpu }
Step { Show-Job hw5 cpu-map }
Step { uvpy tools\timeline.py logs\state\runs\cpu }
Step { uvpy tools\timeline.py logs\state\runs\par --brief }
Step { Show-Log hw5 job/cpu-commit | Select-Object -Last 15 }
Step { Select-String -Path logs\pods\hw3\hw3-tuned-1\*.log -Pattern "\[cpu\]" | ForEach-Object Line }
Step { Storage-Memory }
Finish
