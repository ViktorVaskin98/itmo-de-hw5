. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root

Start-Log "02_image"
Note "Образ с программой из ДЗ 3: две стадии - в первой uv ставит зависимости по uv.lock и пакет в /opt/venv, во вторую копируется только /opt/venv; пользователь uid 10001"
Step { Get-Content Dockerfile }
Step { docker build -q -t $Image . }
Step { docker image ls $Image --format "{{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}" }
Step { docker run --rm $Image sh -c "du -sh /opt/venv; cd /opt/venv/lib/python3.13/site-packages; du -sh * | sort -h | tail -4" }
Step { docker run --rm $Image sh -c "id; python --version; python -c 'import boto3, duckdb, pyarrow; print(boto3.__version__, duckdb.__version__, pyarrow.__version__)'; python -m hhlake.mapreduce --help | head -3" }

Note "Реестра нет: образ копируется прямо в containerd узлов, в манифестах imagePullPolicy: Never"
Step { kind load docker-image $Image --name $Cluster }
Step { docker exec hw5-worker crictl images | Select-String "hhlake|IMAGE" }
Finish
