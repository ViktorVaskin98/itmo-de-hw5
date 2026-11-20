$script:Tools = if ($env:HW5_TOOLS) { $env:HW5_TOOLS } else { "C:\itmo\tools" }
$script:KindVersion = "v0.33.0"
$script:Kind = Join-Path $script:Tools "kind-$script:KindVersion\kind.exe"
$script:Cluster = "hw5"
$script:Ctx = "kind-hw5"
$script:Image = "hw5-hhlake:0.3.0"
$env:AWS_ACCESS_KEY_ID = "labadmin"
$env:AWS_SECRET_ACCESS_KEY = "labsecret123"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$script:Root = Split-Path $PSScriptRoot -Parent
$script:LogDir = Join-Path $script:Root "logs"
$script:HostS3 = "http://127.0.0.1:9000"
$script:ClusterS3 = "http://127.0.0.1:9100"
New-Item -ItemType Directory -Force $script:LogDir | Out-Null

$script:Failed = $false

function kc {
    & kubectl --context $script:Ctx @args 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -ne "System.Management.Automation.RemoteException" }
    if ($LASTEXITCODE -ne 0) { "[exit code $LASTEXITCODE]" }
}

function kind {
    & $script:Kind @args 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -ne "System.Management.Automation.RemoteException" }
}

function uvpy {
    & uv run --project $script:Root --quiet python @args 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { "[exit code $LASTEXITCODE]"; $script:Failed = $true }
}

function Start-Log([string]$Name) {
    $script:CurrentLog = Join-Path $script:LogDir "$Name.txt"
    New-Item -ItemType Directory -Force (Split-Path $script:CurrentLog) | Out-Null
    Set-Content -Path $script:CurrentLog -Value "" -Encoding utf8
}

function Step([scriptblock]$Block) {
    $header = "PS> " + $Block.ToString().Trim()
    $body = ((& $Block 2>&1) | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { "$_" } else { $_ } } |
        Out-String -Width 250).TrimEnd()
    $text = "$header`n$body`n"
    Add-Content -Path $script:CurrentLog -Value $text -Encoding utf8
    Write-Host $text
}

function Note([string]$Text) {
    Add-Content -Path $script:CurrentLog -Value "# $Text`n" -Encoding utf8
    Write-Host "# $Text`n"
}

function Fail([string]$Text) {
    Note "ОШИБКА: $Text"
    $script:Failed = $true
}

function Finish {
    if ($script:Failed) {
        Write-Host "some steps failed, see $script:CurrentLog"
        exit 1
    }
}

function Stamp {
    (Get-Date).ToUniversalTime().ToString("HH:mm:ss") + " UTC"
}

function Render([string]$Template, [hashtable]$Vars, [string]$Name) {
    $text = Get-Content (Join-Path $script:Root "k8s\$Template") -Raw -Encoding utf8
    $text = [regex]::Replace($text, '\$\{(\w+)\}', {
        param($m)
        $key = $m.Groups[1].Value
        if (-not $Vars.ContainsKey($key)) { throw "no value for `${$key} in $Template" }
        [string]$Vars[$key]
    })
    $dir = Join-Path $script:LogDir "manifests"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $path = Join-Path $dir "$Name.yaml"
    [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
    return $path
}

function Submit([string]$Template, [hashtable]$Vars, [string]$Name) {
    $path = Render $Template $Vars $Name
    kc apply -f $path
}

function Wait-JobDone([string]$Namespace, [string]$Job, [int]$Timeout = 900) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        $state = & kubectl --context $script:Ctx -n $Namespace get job $Job `
            -o "jsonpath={range .status.conditions[?(@.status=='True')]}{.type}{' '}{end}" 2>$null
        if ($state -match "\bComplete\b") { return "Complete" }
        if ($state -match "\bFailed\b") { return "Failed" }
        Start-Sleep -Milliseconds 500
    }
    return "Timeout"
}

function Show-Job([string]$Namespace, [string]$Job) {
    kc -n $Namespace get job $Job -o "custom-columns=JOB:.metadata.name,COMPLETIONS:.spec.completions,SUCCEEDED:.status.succeeded,FAILED:.status.failed,START:.status.startTime,END:.status.completionTime"
    kc -n $Namespace get job $Job -o "jsonpath={range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{'\n'}{end}"
}

function Save-State([string]$Name, [string]$Namespace, [string]$Selector) {
    $dir = Join-Path $script:LogDir "state\$Name"
    New-Item -ItemType Directory -Force $dir | Out-Null
    & kubectl --context $script:Ctx -n $Namespace get pods -l $Selector -o json 2>$null | Set-Content (Join-Path $dir "pods.json") -Encoding utf8
    & kubectl --context $script:Ctx -n $Namespace get jobs -l $Selector -o json 2>$null | Set-Content (Join-Path $dir "jobs.json") -Encoding utf8
    & kubectl --context $script:Ctx -n $Namespace get events -o json 2>$null | Set-Content (Join-Path $dir "events.json") -Encoding utf8
    & kubectl --context $script:Ctx get nodes -o json 2>$null | Set-Content (Join-Path $dir "nodes.json") -Encoding utf8
}

function Save-PodLogs([string]$Name, [string]$Namespace, [string]$Selector) {
    $dir = Join-Path $script:LogDir "pods\$Name"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $pods = & kubectl --context $script:Ctx -n $Namespace get pods -l $Selector -o "jsonpath={.items[*].metadata.name}" 2>$null
    foreach ($pod in ($pods -split " " | Where-Object { $_ })) {
        & kubectl --context $script:Ctx -n $Namespace logs $pod 2>&1 | ForEach-Object { "$_" } |
            Set-Content (Join-Path $dir "$pod.log") -Encoding utf8
    }
    return $dir
}

function Show-Log([string]$Namespace, [string]$Target, [string]$Drop = "^\[mem-json\]") {
    kc -n $Namespace logs $Target | Where-Object { $_ -notmatch $Drop }
}

function Remove-Run([string]$Namespace, [string]$Selector) {
    & kubectl --context $script:Ctx -n $Namespace delete jobs -l $Selector --ignore-not-found --wait=true 2>&1 | Out-Null
}

$script:RunDefaults = @{
    NAMESPACE = "hw5"; PRIORITY = "batch-low"; CHUNK_MB = 32; REDUCERS = 4; SPLITS = 26; PARALLELISM = 8
    CPU = "1"; MEMORY = "128Mi"; REDUCE_CPU = "1"; REDUCE_MEMORY = "128Mi"
}
$limitsFile = Join-Path $script:LogDir "run_limits.json"
if (Test-Path $limitsFile) {
    $saved = Get-Content $limitsFile -Raw | ConvertFrom-Json
    foreach ($p in $saved.PSObject.Properties) { $script:RunDefaults[$p.Name] = $p.Value }
}

function Run-Vars([string]$Run, [hashtable]$Override = @{}) {
    $v = $script:RunDefaults.Clone()
    foreach ($k in $Override.Keys) { $v[$k] = $Override[$k] }
    $v["RUN"] = $Run
    return $v
}

function Start-Map([hashtable]$V) {
    $env:S3_ENDPOINT = $script:ClusterS3
    & uv run --project $script:Root --quiet python -m hhlake.kube.clean --run $V.RUN 2>&1 | Where-Object { $_ -notmatch "removed 0 old" }
    Submit "30-map-job.yaml" $V "$($V.RUN)-map"
}

function Complete-Run([hashtable]$V) {
    $ns, $run = $V.NAMESPACE, $V.RUN
    "map: $(Wait-JobDone $ns "$run-map")"
    Submit "31-reduce-job.yaml" $V "$run-reduce"
    "reduce: $(Wait-JobDone $ns "$run-reduce")"
    Submit "32-commit-job.yaml" $V "$run-commit"
    "commit: $(Wait-JobDone $ns "$run-commit")"
    Save-PodLogs "runs\$run" $ns "hw5/run=$run" | Out-Null
    Save-State "runs\$run" $ns "hw5/run=$run"
}

function Wait-Running([string]$Namespace, [string]$Selector, [int]$Count, [int]$Timeout = 120) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        $phases = & kubectl --context $script:Ctx -n $Namespace get pods -l $Selector -o "jsonpath={.items[*].status.phase}" 2>$null
        $running = @($phases -split " " | Where-Object { $_ -eq "Running" }).Count
        if ($running -ge $Count) { return "$running pods Running at $(Stamp)" }
        Start-Sleep -Milliseconds 300
    }
    return "timeout waiting for $Count Running pods"
}

function Pods([string]$Namespace, [string]$Selector) {
    kc -n $Namespace get pods -l $Selector --sort-by=.metadata.creationTimestamp -o "custom-columns=POD:.metadata.name,PRIORITY:.spec.priorityClassName,PHASE:.status.phase,NODE:.spec.nodeName,NOMINATED:.status.nominatedNodeName,CPU:.spec.containers[0].resources.requests.cpu"
}

function Storage-Memory {
    $restarts = & kubectl --context $script:Ctx -n hw5 get pod rustfs-0 -o "jsonpath={.status.containerStatuses[0].restartCount}" 2>$null
    $cmd = 'm=/sys/fs/cgroup; set -- $(head -1 $m/memory.stat); echo rustfs-0: restarts RS, memory.current $(( $(cat $m/memory.current) >> 20 )) MiB, anon $(( $2 >> 20 )) MiB, memory.peak $(( $(cat $m/memory.peak) >> 20 )) MiB, memory.max $(( $(cat $m/memory.max) >> 20 )) MiB, memory.events $(tr \\n , < $m/memory.events)'
    kc -n hw5 exec rustfs-0 '--' sh -c $cmd.Replace("RS", "$restarts")
}

function Watch-Disruption([string]$Namespace, [string]$Selector, [int]$Seconds, [string]$Name) {
    $seen = @{}
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $raw = & kubectl --context $script:Ctx -n $Namespace get pods -l $Selector -o json 2>$null | Out-String
        foreach ($pod in ($raw | ConvertFrom-Json).items) {
            $cond = $pod.status.conditions | Where-Object { $_.type -eq "DisruptionTarget" -and $_.status -eq "True" }
            if (-not $cond) { continue }
            if (-not $seen.ContainsKey($pod.metadata.name)) {
                "$($cond.lastTransitionTime) $($pod.metadata.name) on $($pod.spec.nodeName), phase $($pod.status.phase): DisruptionTarget $($cond.reason) - $($cond.message)"
            }
            $seen[$pod.metadata.name] = $pod
        }
        Start-Sleep -Milliseconds 250
    }
    foreach ($pod in $seen.Values) {
        $term = $pod.status.containerStatuses[0].state.terminated
        if ($term) { "$($pod.metadata.name): last seen $($pod.status.phase), container exit code $($term.exitCode) ($($term.reason)), finished $($term.finishedAt)" }
        else { "$($pod.metadata.name): last seen $($pod.status.phase), container still stopping" }
    }
    $dir = Join-Path $script:LogDir "state\runs\$Name"
    New-Item -ItemType Directory -Force $dir | Out-Null
    @{ items = @($seen.Values) } | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $dir "disrupted.json") -Encoding utf8
    "pods with DisruptionTarget: $($seen.Count)"
}
