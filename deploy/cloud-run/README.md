# Cloud Run Jobs deployment

Status: validation, initial training, weekly scoring, daily cleanup and the public dashboard are deployed in us-east1. GitHub Actions tests and publishes private images, then uses Workload Identity Federation and [Terraform](../terraform/README.md) to update Cloud Run and Scheduler. The direct runtime deployment scripts here are legacy migration tools; avoid using them for Terraform-managed resources. Ubuntu deployment stays on hold.

Public dashboard: https://air-quality-dashboard-236256523935.us-east1.run.app

The first weekly run scored all seven days of September 28–October 4, 2026. Weekly scoring runs Monday at 08:00 America/New_York for the previous Monday–Sunday. Cleanup runs daily at 05:00. The retained model was trained once; weekly scoring does not retrain it.

## Runtime layout

Use private Artifact Registry for the already-tested Linux amd64 container. Copy the tested GHCR image into Artifact Registry rather than rebuilding during deployment. Select an immutable digest.

Create separate private Cloud Storage buckets for historical input, model bundles and operational results. Historical data and model bundles are retained. Apply operational-lifecycle.json only to the operational bucket, not the historical or model buckets. Disable operational bucket soft delete and versioning if deleted data must not remain recoverable beyond the retention window. Lifecycle processing is asynchronous, so age 30 is not a strict instantaneous deletion deadline. Logs need a separate Cloud Logging retention setting; bucket lifecycle does not expire logs.

The cloud adapter downloads inputs and models into execution-local scratch space and uploads complete outputs through the Storage API. Initial active-model pointer creation uses a generation precondition. Object-generation leases prevent overlapping job execution. Local CLI promotion still uses local rename; cloud jobs do not rely on mounted-bucket rename semantics.

## Jobs

- Initial smoke job: validate the maintained historical dataset; run once and inspect success.
- Training job: on demand initially; save a candidate bundle and metrics without automatically promoting it.
- Scoring job: use a promoted model and maintained daily input; do not schedule until live daily ingestion exists.
- Operational cleanup: use object creation metadata and the Storage API, with the lifecycle rule as a second line of cleanup. The current local last-modified-time cleanup must not be applied blindly to object-store mounts.

Start training/scoring at 2 CPUs and 4 GiB memory, one task, parallelism 1, no automatic retries for training until retry behavior is verified. Limits can be adjusted after a measured execution. Cloud Run task parallelism does not prevent overlapping job executions: add an object-generation-based lease or idempotency before scheduling.

Cloud Scheduler replaces the host timer. Use a dedicated scheduler service account with run.invoker on the target job and OAuth authentication to the Cloud Run Jobs run API. Leave schedules paused until a one-off execution has passed. Model promotion remains explicit.

## Credentials and CI/CD

Keep Artifact Registry and buckets private. Use separate least-privilege runtime identities: scoring reads history/models and writes operational results; training reads history and writes candidate bundles; promotion alone updates the active-model pointer. Store API keys in Secret Manager and inject them at runtime.

Use GitHub Actions Workload Identity Federation for deployment, bound to this repository and a trusted branch/environment. Do not commit service-account keys or add them to the image. Keep existing container tests and GHCR publishing; cloud deployment is a separate step after tested image publication. No private registry credentials are passed through Cloud Run command arguments.

## Before resource creation

The scripts provision cloud resources and require authenticated Google Cloud CLI access, enabled project billing and a tested immutable image digest. Validation and initial scoring passed before the schedules were enabled.

## Selected project and first deployment

Project: air-quality-tracker-510721 (number 236256523935). Region: us-east1 unless changed. CLI login and enabled project billing verified.

`deploy-smoke.ps1` is the concrete first deployment script. It refuses to proceed without billing; enables required APIs; creates a private Artifact Registry repository and historical bucket; grants a dedicated validation identity read-only data access; uploads the existing combined dataset; mirrors the tested image by digest; creates a one-task read-only validation job; and executes it once. It creates no scheduler, writes no model state, and uses no service-account key. It is safe to use a read-only Cloud Storage mount for validation; training and promotion still need the storage adapter described above.

```powershell
./deploy/cloud-run/deploy-smoke.ps1
```

Billing and your project permissions must be verified before running. This script provisions billable cloud resources. It has been executed against the project. Execution air-quality-validate-svjwl succeeded with one completed task. The registry mirror preserves source digest sha256:d7318d7a8a8682c537a88b804c420bee0a10edb9292e6c0cbc941f0623262ae3. Registry copy uses a pinned crane container with temporary credentials removed on exit; no credentials are included in the deployed image.


## Weekly scoring and public dashboard

`air-quality-cloud bootstrap` stages historical input locally, trains the dense autoencoder with 2024 validation and untouched 2025 testing, uploads a complete model bundle, creates the initial active pointer with a generation precondition, and seeds historical test scores. Repeated bootstrap runs retain the existing active model. It does not retrain weekly.

`air-quality-cloud weekly` scores the previous Monday?Sunday using America/New_York week boundaries. The public AirNow daily files provide monitor concentrations for Wake, Durham and Orange counties: PM2.5 24-hour means in ug/m3 and ozone daily 8-hour peaks in ppb, averaged per pollutant across available sites. The historical ozone dataset is also ppb. AQI values are not used as model inputs. AirNow is preliminary; its monitor coverage and aggregation can differ from AQS. Counts and missing dates are stored alongside scores. Missing inputs are never imputed.

Cloud writes use the Storage API, with execution-local scratch files. A generation-based lease prevents overlapping weekly runs. Output keys include the week start, so reruns update one result rather than creating duplicates. Job retries are disabled. Completed model bundles and historical inputs are retained; all operational objects expire after 30 days. Daily API cleanup supplements bucket lifecycle deletion. Operational soft delete and versioning are disabled. Lifecycle deletion and daily cleanup have scheduling delay and do not guarantee deletion at the exact 30-day second. Cloud Logging's default bucket is set to 30-day retention.

`deploy-weekly.ps1` requires tested Artifact Registry image digests, provisions separate least-privilege job and dashboard identities, runs bootstrap and the first weekly score, and only then creates schedules: Monday 08:00 America/New_York for weekly scoring, daily 05:00 for cleanup. Scheduler invokes private jobs using OAuth. The Streamlit service is publicly accessible but its backing buckets and model artifacts remain private; it has read-only storage access and displays only score tables, run coverage and model metadata. It scales from zero to at most one instance.

The dashboard exposes recent real-week scores and clearly labeled historical 2025 test results, plus training and validation loss curves, anomaly thresholds and split metrics. Reconstruction metrics are not labeled detection accuracy or health-risk predictions. Operational records and historical test score exports age out after 30 days; the active model's training metrics remain available.

AirNow format reference: https://docs.airnowapi.org/docs/DailyDataFactSheet.pdf

## Historical decisions and concentration comparisons

The dashboard also computes an independent observed-exceedance reference from regional concentrations, defaulting to PM2.5 >=35.5 ug/m3 or ozone >=71 ppb. These defaults come from the start of EPA's Unhealthy for Sensitive Groups AQI concentration category; applying them to regional averages is a benchmark, not an official AQI calculation. Users can compare either reconstructed concentration exceedances (the same limits applied to outputs) or the existing autoencoder flags against that observed reference. Counts, accuracy, precision, recall and every daily outcome are displayed for the entire held-out test set. Undefined precision/recall are shown explicitly; no observed positives triggers a warning. Limits are configurable and should be selected independently of evaluation performance.

The Historical flags tab defaults to flagged days in the held-out 2025 period and can display all days. Each row distinguishes the model decision from an independently verified event label (currently unavailable). Scoring saves inverse-scaled PM2.5 and ozone reconstructions, the per-result anomaly threshold and standardized reconstruction errors. Dashboard comparisons show observed/reconstructed concentrations and MAE, RMSE and mean bias in pollutant units for the selected days. These are same-day reconstructions, not forecasts or labeled anomaly-detection accuracy. Flagged-only errors are selected by the model's error threshold and are not an independent evaluation set.

`refresh-score-artifacts.ps1 -Image <tested-digest>` refreshes retained score files with the existing active model, without training or promotion. It stages private data under ignored runtime scratch storage and removes it afterward. Refreshing replaces operational objects and starts their 30-day creation-age retention again; use this as a one-off schema migration, not a schedule. `mirror-images.ps1 -Revision <tested-commit>` copies the two private tested images into Artifact Registry using ephemeral credentials.
