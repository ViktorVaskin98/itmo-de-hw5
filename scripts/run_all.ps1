$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Run([string]$Script) {
    Write-Host "=== $Script"
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\$Script"
    if ($LASTEXITCODE -ne 0) { throw "$Script failed" }
}

Remove-Item -Recurse -Force logs\pods, logs\state, logs\manifests -ErrorAction SilentlyContinue
Remove-Item logs\run_limits.json, logs\hw3_limit.txt -ErrorAction SilentlyContinue
docker start rustfs-lab | Out-Null
foreach ($s in "01_cluster", "02_image", "03_memory", "04_storage", "05_parallel", "06_cpu", "07_preemption", "08_quota") {
    Run "$s.ps1"
}
docker start rustfs-lab | Out-Null
