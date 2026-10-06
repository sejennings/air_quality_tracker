# Terraform deployment

GitHub Actions builds and tests both images, verifies private GHCR publishing and pulls, authenticates to Google using Workload Identity Federation, mirrors the exact tested digests into private Artifact Registry, then plans and applies Terraform. Cloud Run pulls those images from Artifact Registry. Terraform does not execute training or scoring on deployment.

This root manages the three existing Cloud Run jobs, the dashboard service and the weekly/daily Scheduler jobs. Import blocks adopt those resources. Historical/model/operational storage, data access identities, public dashboard IAM and 30-day retention remain in their existing configuration; this migration does not recreate them. The operational cleanup schedule remains daily 05:00 Eastern and scoring remains Monday 08:00 Eastern for the completed week.

`bootstrap.ps1` is the one-time administrator setup for a private, versioned Terraform state bucket, a scoped deployment role and a GitHub OIDC identity provider. It also configures the production GitHub environment and **non-secret variables**: `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`. No user-created GitHub secrets, personal tokens, service-account keys or credential files are required. The existing built-in short-lived `GITHUB_TOKEN` reads the private GHCR package.

OIDC trust is bound to numeric repository/owner IDs, this exact workflow, push/manual events, the production environment and the `main` and `codex/container-ci` branches. PRs, including forks, run tests and Terraform validation without cloud credentials. Both branches currently deploy; after merging this migration, narrow the workflow, environment policy and provider trust to `main` if that is the desired release policy.

Deployments serialize without interrupting an apply, use remote GCS state locking, pinned Terraform/provider/action versions and checksum locks, and reject deletion/replacement plans. No plans, state or credentials are uploaded to public Actions artifacts. Plan output stays in an ephemeral runner file, and generated credentials/plan files are excluded from Git and the Docker context. The state bucket is private infrastructure metadata retained separately from 30-day operational data.

An administrator initially imports the current resources using their existing image digests and reviews the plan before applying it. Later deployments run through Actions; do not use `deploy-weekly.ps1` to change Terraform-managed resources. Model promotion remains independent, and the historical data and active model stay retained. To roll back, dispatch CI on a trusted branch containing the desired code revision; it rebuilds, tests and deploys that revision through Terraform.

The deployment identity can update the existing runtime resources, write images to this one registry, access this one state bucket and act as the five named runtime/scheduler service accounts. It cannot edit project IAM, read training/model/result buckets directly or delete runtime resources. Bootstrap administration is not delegated to CI.

Local checks:

```powershell
terraform -chdir=deploy/terraform fmt -check
terraform -chdir=deploy/terraform init -backend=false -lockfile=readonly
terraform -chdir=deploy/terraform validate
python deploy/terraform/test_plan.py
```

For authenticated administration, supply an ephemeral Google credential through the environment or Application Default Credentials. Never pass a token as a Terraform variable or backend argument, since those can be persisted to disk/state. The remote backend is initialized with `-backend-config="bucket=air-quality-tracker-510721-terraform" -backend-config="prefix=production/runtime"`. Select full immutable image digests through `TF_VAR_pipeline_image`, `TF_VAR_dashboard_image` and the tested full commit through `TF_VAR_revision`.
