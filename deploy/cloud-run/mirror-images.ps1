param(
    [Parameter(Mandatory=$true)][string]$Revision,
    [string]$Project = 'air-quality-tracker-510721',
    [string]$Region = 'us-east1',
    [string]$Gcloud = "$env:LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
)
$ErrorActionPreference = 'Stop'
if ($Revision -notmatch '^[a-f0-9]{40}$') { throw 'Use the full tested commit SHA.' }
$env:AIR_SOURCE_TOKEN = gh auth token
if ($LASTEXITCODE -ne 0) { throw 'GitHub authentication failed.' }
$env:AIR_DEST_TOKEN = & $Gcloud auth print-access-token
if ($LASTEXITCODE -ne 0) { throw 'Google authentication failed.' }
try {
    $env:AIR_REVISION = $Revision
    $env:AIR_DEST_PREFIX = "$Region-docker.pkg.dev/$Project/air-quality"
    $mirrorCommand = 'printf "%s" "$AIR_SOURCE_TOKEN" | crane auth login ghcr.io -u sejennings --password-stdin && printf "%s" "$AIR_DEST_TOKEN" | crane auth login us-east1-docker.pkg.dev -u oauth2accesstoken --password-stdin && crane copy "ghcr.io/sejennings/air-quality-tracker-runtime:$AIR_REVISION" "$AIR_DEST_PREFIX/pipeline:$AIR_REVISION" && crane copy "ghcr.io/sejennings/air-quality-tracker-runtime:dashboard-$AIR_REVISION" "$AIR_DEST_PREFIX/dashboard:$AIR_REVISION"'
    docker run --rm --entrypoint /busybox/sh -e AIR_SOURCE_TOKEN -e AIR_DEST_TOKEN -e AIR_REVISION -e AIR_DEST_PREFIX gcr.io/go-containerregistry/crane@sha256:e78770b31258a3846f878036d9c1f63fbe4c871f9f56990bf77fd95c013e3c1b -c $mirrorCommand
    if ($LASTEXITCODE -ne 0) { throw 'Registry mirror failed.' }
} finally {
    Remove-Item Env:AIR_SOURCE_TOKEN,Env:AIR_DEST_TOKEN,Env:AIR_REVISION,Env:AIR_DEST_PREFIX -ErrorAction SilentlyContinue
}
