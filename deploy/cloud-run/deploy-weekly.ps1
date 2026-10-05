param(
    [string]$Project = 'air-quality-tracker-510721',
    [string]$Region = 'us-east1',
    [Parameter(Mandatory=$true)][string]$PipelineImage,
    [Parameter(Mandatory=$true)][string]$DashboardImage,
    [Parameter(Mandatory=$true)][string]$Revision,
    [string]$Gcloud = "$env:LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
)
$ErrorActionPreference = 'Stop'
$env:PATH = (Split-Path -Parent $Gcloud) + [IO.Path]::PathSeparator + $env:PATH
function Invoke-Gcloud {
    & $Gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed ($LASTEXITCODE)" }
}
if ($PipelineImage -notmatch '@sha256:' -or $DashboardImage -notmatch '@sha256:') { throw 'Deploy tested images by digest.' }
Invoke-Gcloud services enable cloudscheduler.googleapis.com logging.googleapis.com --project=$Project --quiet
$models = "$Project-models"
$operational = "$Project-operational"
$buckets = Invoke-Gcloud storage buckets list --project=$Project --format='value(name)'
foreach ($bucket in @($models, $operational)) {
    if (-not ($buckets -match "(^|/)$bucket/?$")) {
        Invoke-Gcloud storage buckets create "gs://$bucket" --project=$Project --location=$Region --uniform-bucket-level-access --public-access-prevention --quiet
    }
}
Invoke-Gcloud storage buckets update "gs://$operational" --clear-soft-delete --no-versioning --lifecycle-file=(Join-Path $PSScriptRoot 'operational-lifecycle.json') --quiet
Invoke-Gcloud logging buckets update _Default --location=global --retention-days=30 --project=$Project --quiet
$names = @('air-quality-bootstrap','air-quality-weekly','air-quality-cleanup','air-quality-dashboard','air-quality-scheduler')
$accounts = Invoke-Gcloud iam service-accounts list --project=$Project --format='value(email)'
foreach ($name in $names) {
    $email = "$name@$Project.iam.gserviceaccount.com"
    if ($email -notin $accounts) { Invoke-Gcloud iam service-accounts create $name --project=$Project --quiet }
}
$bootstrap = "air-quality-bootstrap@$Project.iam.gserviceaccount.com"
$weekly = "air-quality-weekly@$Project.iam.gserviceaccount.com"
$cleanup = "air-quality-cleanup@$Project.iam.gserviceaccount.com"
$dashboard = "air-quality-dashboard@$Project.iam.gserviceaccount.com"
$scheduler = "air-quality-scheduler@$Project.iam.gserviceaccount.com"
Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$Project-historical" --member="serviceAccount:$bootstrap" --role=roles/storage.objectViewer --quiet
foreach ($identity in @($bootstrap, $weekly, $cleanup)) {
    Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$operational" --member="serviceAccount:$identity" --role=roles/storage.objectAdmin --quiet
}
Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$models" --member="serviceAccount:$bootstrap" --role=roles/storage.objectAdmin --quiet
foreach ($identity in @($weekly, $dashboard)) {
    Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$models" --member="serviceAccount:$identity" --role=roles/storage.objectViewer --quiet
}
Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$operational" --member="serviceAccount:$dashboard" --role=roles/storage.objectViewer --quiet
Invoke-Gcloud run jobs deploy air-quality-bootstrap --project=$Project --region=$Region --image=$PipelineImage --command=air-quality-cloud --args="bootstrap,--history-bucket,$Project-historical,--models-bucket,$models,--operational-bucket,$operational" --service-account=$bootstrap --tasks=1 --parallelism=1 --max-retries=0 --cpu=2 --memory=4Gi --task-timeout=3600s --set-env-vars="GIT_COMMIT=$Revision" --quiet
Invoke-Gcloud run jobs deploy air-quality-weekly --project=$Project --region=$Region --image=$PipelineImage --command=air-quality-cloud --args="weekly,--models-bucket,$models,--operational-bucket,$operational" --service-account=$weekly --tasks=1 --parallelism=1 --max-retries=0 --cpu=1 --memory=2Gi --task-timeout=1800s --quiet
Invoke-Gcloud run jobs deploy air-quality-cleanup --project=$Project --region=$Region --image=$PipelineImage --command=air-quality-cloud --args="cleanup,--operational-bucket,$operational" --service-account=$cleanup --tasks=1 --parallelism=1 --max-retries=0 --cpu=1 --memory=512Mi --task-timeout=600s --quiet
Invoke-Gcloud run jobs execute air-quality-bootstrap --project=$Project --region=$Region --wait --quiet
Invoke-Gcloud run jobs execute air-quality-weekly --project=$Project --region=$Region --wait --quiet
# Schedule only after the bootstrap and first real weekly execution pass.
foreach ($job in @('air-quality-weekly','air-quality-cleanup')) {
    Invoke-Gcloud run jobs add-iam-policy-binding $job --project=$Project --region=$Region --member="serviceAccount:$scheduler" --role=roles/run.invoker --quiet
}
$existingSchedules = Invoke-Gcloud scheduler jobs list --project=$Project --location=$Region --format='value(name)'
foreach ($job in @('air-quality-weekly','air-quality-cleanup')) {
    $cron = if ($job -eq 'air-quality-weekly') { '0 8 * * 1' } else { '0 5 * * *' }
    $operation = if ($existingSchedules -match "(^|/)$job$") { 'update' } else { 'create' }
    Invoke-Gcloud scheduler jobs $operation http $job --project=$Project --location=$Region --schedule=$cron --time-zone=America/New_York --uri="https://run.googleapis.com/v2/projects/$Project/locations/$Region/jobs/${job}:run" --http-method=POST --oauth-service-account-email=$scheduler --message-body='{}' --max-retry-attempts=0 --quiet
}
Invoke-Gcloud run deploy air-quality-dashboard --project=$Project --region=$Region --image=$DashboardImage --service-account=$dashboard --allow-unauthenticated --port=8080 --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=20 --timeout=3600s --set-env-vars="MODELS_BUCKET=$models,OPERATIONAL_BUCKET=$operational" --quiet
Invoke-Gcloud run services describe air-quality-dashboard --project=$Project --region=$Region --format='value(status.url)'
