param(
    [string]$Project = 'air-quality-tracker-510721',
    [string]$Region = 'us-east1',
    [string]$Gcloud = "$env:LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
)
$ErrorActionPreference = 'Stop'
function Cloud {
    & $Gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "Google setup failed: $($args[0])" }
}
Cloud services enable iamcredentials.googleapis.com sts.googleapis.com --project=$Project --quiet
$stateBucket = "$Project-terraform"
$buckets = Cloud storage buckets list --project=$Project --format='value(name)'
if (-not ($buckets -match "(^|/)$stateBucket/?$")) {
    Cloud storage buckets create "gs://$stateBucket" --project=$Project --location=$Region --uniform-bucket-level-access --public-access-prevention --quiet
}
Cloud storage buckets update "gs://$stateBucket" --versioning --quiet
$account = "air-quality-deploy@$Project.iam.gserviceaccount.com"
$accounts = Cloud iam service-accounts list --project=$Project --format='value(email)'
if ($account -notin $accounts) { Cloud iam service-accounts create air-quality-deploy --project=$Project --quiet }
$pool = 'air-quality-github'
$pools = Cloud iam workload-identity-pools list --project=$Project --location=global --format='value(name)'
if (-not ($pools -match "/$pool$")) { Cloud iam workload-identity-pools create $pool --project=$Project --location=global --display-name='Air quality GitHub CI' --quiet }
$providers = Cloud iam workload-identity-pools providers list --workload-identity-pool=$pool --project=$Project --location=global --format='value(name)'
$operation = if ($providers -match '/github$') { 'update-oidc' } else { 'create-oidc' }
# Numeric IDs prevent a renamed/deleted repository being impersonated. Trust only
# this workflow, these existing branches, and push/manual runs in production.
$subjectConfig = gh api repos/sejennings/air_quality_tracker/actions/oidc/customization/sub | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the repository OIDC subject configuration.' }
$subjectPrefix = if ($subjectConfig.sub_claim_prefix) { $subjectConfig.sub_claim_prefix } else { 'repo:sejennings/air_quality_tracker' }
$condition = "assertion.repository_id == '1377518824' && assertion.repository_owner_id == '89467945' && assertion.ref in ['refs/heads/main', 'refs/heads/codex/container-ci'] && assertion.event_name in ['push', 'workflow_dispatch'] && assertion.sub == '${subjectPrefix}:environment:production' && assertion.workflow_ref in ['sejennings/air_quality_tracker/.github/workflows/ci.yaml@refs/heads/main', 'sejennings/air_quality_tracker/.github/workflows/ci.yaml@refs/heads/codex/container-ci']"
Cloud iam workload-identity-pools providers $operation github --workload-identity-pool=$pool --project=$Project --location=global --issuer-uri=https://token.actions.githubusercontent.com --attribute-mapping='google.subject=assertion.sub,attribute.repository_id=assertion.repository_id' --attribute-condition=$condition --quiet
$projectNumber = Cloud projects describe $Project --format='value(projectNumber)'
Cloud iam service-accounts add-iam-policy-binding $account --project=$Project --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/$projectNumber/locations/global/workloadIdentityPools/$pool/attribute.repository_id/1377518824" --quiet
$permissions = 'run.jobs.get,run.jobs.update,run.services.get,run.services.update,run.operations.get,run.operations.list,cloudscheduler.jobs.get,cloudscheduler.jobs.update,resourcemanager.projects.get,serviceusage.services.use'
$roles = Cloud iam roles list --project=$Project --format='value(name)'
$roleOperation = if ($roles -match '/airQualityRuntimeDeployer$') { 'update' } else { 'create' }
Cloud iam roles $roleOperation airQualityRuntimeDeployer --project=$Project --title='Air Quality Runtime Deployer' --permissions=$permissions --stage=GA --quiet
Cloud projects add-iam-policy-binding $Project --member="serviceAccount:$account" --role="projects/$Project/roles/airQualityRuntimeDeployer" --quiet
Cloud artifacts repositories add-iam-policy-binding air-quality --project=$Project --location=$Region --member="serviceAccount:$account" --role=roles/artifactregistry.writer --quiet
Cloud storage buckets add-iam-policy-binding "gs://$stateBucket" --member="serviceAccount:$account" --role=roles/storage.objectAdmin --quiet
foreach ($runtime in @('bootstrap', 'weekly', 'cleanup', 'dashboard', 'scheduler')) {
    Cloud iam service-accounts add-iam-policy-binding "air-quality-$runtime@$Project.iam.gserviceaccount.com" --project=$Project --member="serviceAccount:$account" --role=roles/iam.serviceAccountUser --quiet
}
# Non-secret repository variables; no service account keys or stored access tokens.
gh api --method PUT repos/sejennings/air_quality_tracker/environments/production --input "$PSScriptRoot/production-environment.json"
if ($LASTEXITCODE -ne 0) { throw 'GitHub environment setup failed.' }
$branchPolicies = gh api repos/sejennings/air_quality_tracker/environments/production/deployment-branch-policies --jq '.branch_policies[].name'
foreach ($branchName in @('main', 'codex/container-ci')) {
    if ($branchName -notin $branchPolicies) {
        gh api --silent --method POST repos/sejennings/air_quality_tracker/environments/production/deployment-branch-policies -f name=$branchName -f type=branch
        if ($LASTEXITCODE -ne 0) { throw 'GitHub deployment branch policy setup failed.' }
    }
}
foreach ($entry in @{
    GCP_WORKLOAD_IDENTITY_PROVIDER = "projects/$projectNumber/locations/global/workloadIdentityPools/$pool/providers/github"
    GCP_DEPLOY_SERVICE_ACCOUNT = $account
    TF_STATE_BUCKET = $stateBucket
}.GetEnumerator()) {
    gh variable set $entry.Key --repo sejennings/air_quality_tracker --body $entry.Value
    if ($LASTEXITCODE -ne 0) { throw 'GitHub variable setup failed.' }
}
