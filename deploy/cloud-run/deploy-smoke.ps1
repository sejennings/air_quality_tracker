param(
    [string]$Project = 'air-quality-tracker-510721',
    [string]$Region = 'us-east1',
    [string]$SourceImage = 'ghcr.io/sejennings/air-quality-tracker-runtime@sha256:d7318d7a8a8682c537a88b804c420bee0a10edb9292e6c0cbc941f0623262ae3',
    [string]$Gcloud = "$env:LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
)
$ErrorActionPreference = 'Stop'
$env:PATH = (Split-Path -Parent $Gcloud) + [IO.Path]::PathSeparator + $env:PATH
function Invoke-Gcloud {
    & $Gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed ($LASTEXITCODE)" }
}
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker failed ($LASTEXITCODE)" }
}
$billing = Invoke-Gcloud billing projects describe $Project --format='value(billingEnabled)'
if ($billing -ne 'True') { throw 'Enable project billing before deployment.' }
$repository = 'air-quality'
$bucket = "$Project-historical"
$serviceAccountName = 'air-quality-validate'
$serviceAccount = "$serviceAccountName@$Project.iam.gserviceaccount.com"
$image = "$Region-docker.pkg.dev/$Project/$repository/pipeline:verified-57146cb"
$dataset = Join-Path $PSScriptRoot '../../data/triangle_pm25_ozone_daily_2021_2025.parquet'
if (-not (Test-Path -LiteralPath $dataset)) { throw 'Historical dataset is missing.' }
Invoke-Gcloud services enable run.googleapis.com artifactregistry.googleapis.com storage.googleapis.com iam.googleapis.com --project=$Project --quiet
$repos = Invoke-Gcloud artifacts repositories list --project=$Project --location=$Region --format='value(name)'
if (-not ($repos -match "(^|/)$repository$")) {
    Invoke-Gcloud artifacts repositories create $repository --repository-format=docker --location=$Region --project=$Project --quiet
}
$buckets = Invoke-Gcloud storage buckets list --project=$Project --format='value(name)'
if (-not ($buckets -match "(^|/)$bucket/?$")) {
    Invoke-Gcloud storage buckets create "gs://$bucket" --project=$Project --location=$Region --uniform-bucket-level-access --public-access-prevention --quiet
}
$accounts = Invoke-Gcloud iam service-accounts list --project=$Project --format='value(email)'
if ($serviceAccount -notin $accounts) {
    Invoke-Gcloud iam service-accounts create $serviceAccountName --project=$Project --quiet
}
Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$bucket" --member="serviceAccount:$serviceAccount" --role=roles/storage.objectViewer --quiet
Invoke-Gcloud storage cp $dataset "gs://$bucket/triangle_pm25_ozone_daily_2021_2025.parquet" --quiet
$env:AIR_SOURCE_TOKEN = gh auth token
if ($LASTEXITCODE -ne 0) { throw 'GitHub registry authentication unavailable.' }
$env:AIR_DEST_TOKEN = Invoke-Gcloud auth print-access-token
try {
    $env:AIR_SOURCE_IMAGE = $SourceImage
    $env:AIR_DEST_IMAGE = $image
    $copyCommand = 'printf "%s" "$AIR_SOURCE_TOKEN" | crane auth login ghcr.io -u sejennings --password-stdin && printf "%s" "$AIR_DEST_TOKEN" | crane auth login us-east1-docker.pkg.dev -u oauth2accesstoken --password-stdin && crane copy "$AIR_SOURCE_IMAGE" "$AIR_DEST_IMAGE"'
    Invoke-Docker run --rm --entrypoint /busybox/sh -e AIR_SOURCE_TOKEN -e AIR_DEST_TOKEN -e AIR_SOURCE_IMAGE -e AIR_DEST_IMAGE gcr.io/go-containerregistry/crane@sha256:e78770b31258a3846f878036d9c1f63fbe4c871f9f56990bf77fd95c013e3c1b -c $copyCommand
} finally {
    Remove-Item Env:AIR_SOURCE_TOKEN,Env:AIR_DEST_TOKEN,Env:AIR_SOURCE_IMAGE,Env:AIR_DEST_IMAGE -ErrorAction SilentlyContinue
}
$digest = Invoke-Gcloud artifacts docker images describe $image --project=$Project --format='value(image_summary.digest)'
if ($digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Artifact Registry digest missing.' }
$immutableImage = "$Region-docker.pkg.dev/$Project/$repository/pipeline@$digest"
Invoke-Gcloud run jobs deploy air-quality-validate --project=$Project --region=$Region --image=$immutableImage --service-account=$serviceAccount --tasks=1 --parallelism=1 --max-retries=0 --cpu=1 --memory=2Gi --task-timeout=600s --args='validate,--input,/data/triangle_pm25_ozone_daily_2021_2025.parquet' --add-volume="name=historical,type=cloud-storage,bucket=$bucket,readonly=true" --add-volume-mount='volume=historical,mount-path=/data' --quiet
Invoke-Gcloud run jobs execute air-quality-validate --project=$Project --region=$Region --wait --quiet
