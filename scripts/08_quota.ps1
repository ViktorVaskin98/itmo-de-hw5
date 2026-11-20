. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

Start-Log "08_quota"
Note "Этап 4в. Квота пространства имён hw5-quota: 3 CPU и 1Gi на всё пространство, хотя в кластере свободно 8 CPU"
kc delete namespace hw5-quota --ignore-not-found --wait=true | Out-Null
Step { Get-Content k8s\40-quota.yaml | Select-Object -Skip 18 }
Step { kc apply -f k8s\40-quota.yaml }
Step { kc -n hw5-quota describe resourcequota hw5-quota }

Note "Под без requests/limits в пространстве с квотой на cpu и memory не принимается"
Step { kc -n hw5-quota run bare --image=$Image --image-pull-policy=Never --restart=Never '--' python -c "print(1)" }
Note "LimitRange подставляет значения по умолчанию - тот же под проходит"
Step { kc apply -f k8s\41-limitrange.yaml }
Step { kc -n hw5-quota run bare --image=$Image --image-pull-policy=Never --restart=Never '--' python -c "print(1)" }
Step { kc -n hw5-quota get pod bare -o "jsonpath={.spec.containers[0].resources}"; "" }
Step { kc -n hw5-quota delete pod bare --wait=true }

Note "Map из 26 сплитов с parallelism 8 по 1 CPU: квота пропускает три пода одновременно"
$quota = Run-Vars "quota" @{ NAMESPACE = "hw5-quota" }
Step { Start-Map $quota }
Step { Wait-Running hw5-quota "hw5/run=quota" 3 }
Start-Sleep 3
Step { Pods hw5-quota "hw5/run=quota" }
Step { kc -n hw5-quota describe resourcequota hw5-quota }
Step { kc -n hw5-quota get events --field-selector reason=FailedCreate -o "custom-columns=LAST:.lastTimestamp,OBJECT:.involvedObject.name,COUNT:.count,MESSAGE:.message" | Select-Object -First 4 }
Step { kc describe node hw5-worker | Select-String -Pattern "Allocated resources:" -Context 0,6 }
Step { Complete-Run $quota }
Step { Show-Job hw5-quota quota-map }
Step { uvpy tools\timeline.py logs\state\runs\quota }
Step { Show-Log hw5-quota job/quota-commit | Select-Object -Last 15 }
Step { kc -n hw5-quota describe resourcequota hw5-quota }
Step { Storage-Memory }
Finish
