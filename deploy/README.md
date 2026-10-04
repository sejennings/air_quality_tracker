# Ubuntu deployment

This first milestone scores the existing daily PM2.5/ozone Parquet dataset. Live collection, automatic release polling, dashboard, MLflow, and vulnerability/provenance gates are follow-up work. Do not enable the scoring timer until its input is a maintained daily dataset: the supplied historical file is a smoke-test input and would be rescored every day.

## Initial host setup

Install Docker Engine and the Compose plugin using Docker's Ubuntu instructions: https://docs.docker.com/engine/install/ubuntu/

Place this repository at `/opt/air-quality-tracker`. Prepare persistent directories, owned by the container user:

```bash
sudo mkdir -p /srv/air-quality/{historical,models,operational}
sudo chown -R 10001:10001 /srv/air-quality/models /srv/air-quality/operational
sudo chmod 750 /srv/air-quality/models /srv/air-quality/operational
```

Copy the existing combined Parquet file into `/srv/air-quality/historical/`. Keep host secrets outside Git. Create `/opt/air-quality-tracker/.env` with:

```dotenv
AIR_QUALITY_IMAGE=ghcr.io/OWNER/REPO@sha256:VERIFIED_DIGEST
AIR_QUALITY_DATA=/srv/air-quality/historical
AIR_QUALITY_MODELS=/srv/air-quality/models
AIR_QUALITY_OPERATIONAL=/srv/air-quality/operational
```

Use the digest of a successful CI image, not a moving latest tag. If the package is private, log in on the host with a read-packages credential. Protect `.env` with mode 600. Build/publish uses the repository's GitHub token; no host credentials are required by CI.

## Train and explicitly activate a candidate

```bash
cd /opt/air-quality-tracker
docker compose pull
docker compose run --rm pipeline validate --input /data/triangle_pm25_ozone_daily_2021_2025.parquet
docker compose run --rm pipeline train --input /data/triangle_pm25_ozone_daily_2021_2025.parquet
# Review /srv/air-quality/models/RUN_ID/metadata.json before promotion.
docker compose run --rm pipeline promote RUN_ID
docker compose run --rm pipeline score --input /data/triangle_pm25_ozone_daily_2021_2025.parquet
```

Training defaults: before 2024 for training, 2024 for early-stopping validation, and 2025 onward for the untouched test period. The 95th-percentile threshold is calculated from training errors only. Missing model inputs are dropped; duplicate dates and infinities are rejected. This is an anomaly detector, not a forecaster. Metrics are reconstruction MSE and anomaly rates, not labeled detection accuracy. `metadata.json` includes epoch history for future visualization.

## Scheduling and retention

```bash
sudo cp deploy/air-quality-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now air-quality-cleanup.timer
# Enable this only after choosing a maintained daily input and editing the service path.
# sudo systemctl enable --now air-quality-score.timer
sudo systemctl list-timers 'air-quality-*'
```

Operational `scores`, `collected`, and `logs` files are deleted when their last-modified time is at least 30 days old. Cleanup runs daily, catches up after downtime, and precedes scoring. Daily cleanup permits up to one day of scheduling delay; it is not an instantaneous 30-day deletion guarantee. Models and historical inputs are outside cleanup's scope. Operational data must not be copied into permanent backups, since that would bypass retention. Docker logging is disabled for these short-lived jobs; systemd status/output follows the host journald policy. Configure journald `MaxRetentionSec=30day` if job logs are retained there; note that this is a host-wide setting. No new operational data is collected during host downtime.

Model candidates are retained for now along with the active model. Disk-capacity monitoring and a separate obsolete-model policy should be added before frequent automated retraining. Back up historical data and model bundles, and test restore.

## Release and rollback

Pull requests build and test the container. A successful main build publishes a commit-tagged image to GHCR. Deployment is intentionally manual in this milestone: update `AIR_QUALITY_IMAGE` to that image's digest, pull it, and run the validation and scoring smoke checks above. Record the previous digest and active run ID first. If checks fail, restore the previous image digest and run ID. No long-running app is switched in this milestone. The eventual host-side release poller will automate this procedure without inbound SSH or a general-purpose GitHub runner on the production machine.

For local development, create `runtime/models` and `runtime/operational`, then run `docker compose build` and the same commands. Docker Desktop on Windows uses the Linux image. Runtime dependencies are pinned in `pyproject.toml`; the existing notebook requirements are unchanged. Full transitive dependency locking and base-image digest pinning remain follow-up hardening.
