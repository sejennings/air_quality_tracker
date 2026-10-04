param([string]$Image = 'air-quality-tracker:local', [switch]$Pull)
$ErrorActionPreference = 'Stop'
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed ($LASTEXITCODE)" }
}
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    Invoke-Docker info --format '{{.OSType}}'
    if ($Pull) {
        Invoke-Docker pull --platform linux/amd64 $Image
    } else {
        Invoke-Docker build --platform linux/amd64 -t $Image .
    }
    Invoke-Docker run --rm $Image --help
    Invoke-Docker run --rm --read-only --tmpfs /tmp:size=512m --entrypoint python --mount "type=bind,source=$PWD/tests,target=/tests,readonly" $Image -m unittest discover -s /tests -v
    Invoke-Docker compose config --quiet
} finally {
    Pop-Location
}
