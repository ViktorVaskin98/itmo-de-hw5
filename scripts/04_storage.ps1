. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

Start-Log "04_storage"
Note "Этап 2. RustFS из ДЗ 2 внутри кластера: тот же образ 1.0.1, восемь томов (EC 4+4), StatefulSet на узле hw5/pool=storage"
Step { Get-Content k8s\20-rustfs.yaml | Select-Object -First 70 }
Step { kc apply -f k8s\00-namespace.yaml -f k8s\05-priority.yaml -f k8s\20-rustfs.yaml }
Step { kc -n hw5 rollout status statefulset/rustfs --timeout=300s }
Step { kc -n hw5 get statefulset,pod,svc -o wide }
Step { kc -n hw5 get pvc -o "custom-columns=PVC:.metadata.name,STATUS:.status.phase,SIZE:.status.capacity.storage,CLASS:.spec.storageClassName,VOLUME:.spec.volumeName" }
Step { kc get pv -o "custom-columns=PV:.metadata.name,CLAIM:.spec.claimRef.name,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0],PATH:.spec.hostPath.path" }
Step { kc -n hw5 logs rustfs-0 }

Note "Перенос данных: задание s3-migrate читает бакет hh-lake в rustfs-lab и пишет в RustFS кластера, md5 считается по потоку источника и по повторному чтению копии"
kc -n hw5 delete job s3-migrate --ignore-not-found | Out-Null
Step { kc apply -f k8s\21-migrate-job.yaml }
Step { "job/s3-migrate -> $(Wait-JobDone hw5 s3-migrate 900)" }
Step { Show-Log hw5 job/s3-migrate }
Step { (Get-FileHash C:\itmo\vk\task2\it_vacancies_2024.csv -Algorithm MD5).Hash.ToLower() }
Save-PodLogs "storage" hw5 "hw5/stage=migrate" | Out-Null

Note "Раскладка по дискам: на каждом из восьми томов около 1/4 объекта - 4 блока данных и 4 чётности"
Step { kc -n hw5 exec rustfs-0 '--' sh -c "du -sh /data/disk*; ls /data/disk1/hh-lake/raw/it_vacancies_2024.csv/*/ | head -4" }

Note "Данные перенесены - старое хранилище rustfs-lab больше не нужно заданиям; останавливаю его, дальше всё читается только из RustFS в кластере (run_all запускает его снова в конце)"
Step { docker stop rustfs-lab }
Step { Storage-Memory }

Note "С хоста RustFS кластера доступен через NodePort 30900 -> 127.0.0.1:9100 (extraPortMappings kind)"
$env:S3_ENDPOINT = $ClusterS3
Step { uvpy -m hhlake.kube.plan --chunk-mb 32 }
Finish
