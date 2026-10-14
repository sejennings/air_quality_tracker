# air_quality_tracker
Want to try github actions

             HISTORICAL TRAINING
                    │
                    ▼
              EPA AQS data
          + historical weather
                    │
                    ▼
           Feature engineering
                    │
                    ▼
          TensorFlow model
          / anomaly detector
                    │
                    ▼
           Saved production model


              LIVE PIPELINE
              
                    │
              Google Cloud Run Jobs
              runs every week
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    AirNow PM2.5         Weather data
          │                   │
          └─────────┬─────────┘
                    ▼
               Data validation
                    ▼
              Feature pipeline
                    ▼
             TensorFlow model
                    ▼
          Expected PM2.5 value
          + anomaly score
                    ▼
                Dashboard

## Standalone runtime

The Python package, Docker image, and GitHub Actions workflow now support validated daily inputs, training, explicit model promotion, scoring, and 30-day operational retention. See [Ubuntu deployment instructions](deploy/README.md) for persistent storage, scheduling, releases, and rollback.

Historical inputs and models are retained. Training results and per-epoch loss are saved in each model bundle's `metadata.json`. Live ingestion and a dashboard are not implemented yet.

## Current local verification workflow

Host deployment is on hold. Build and test with `./scripts/test-container.ps1`; private GHCR publishing and local pull instructions are in [scripts/README.md](scripts/README.md). CI publishes the tested image without rebuilding it and reruns the tests after pulling it from the registry.
# Second model: LSTM autoencoder

The standalone pipeline also supports the architecture from
`notebooks/LSTM Autoencoder.py`: LSTM 32/16 encoder, repeated latent vector,
LSTM 16/32 decoder, and four reconstructed features across 14 calendar days.
The real input column is `ozone_8hr_max`. Both models use training years
2021–2023, validation 2024, and held-out test 2025; sequence windows stay
entirely within their split. Missing dates or pollutants invalidate a window.

Use `air-quality --models /models --model lstm train --input /data/daily.parquet
--epochs 100` to create a candidate, then explicitly promote it with
`air-quality --models /models --model lstm promote RUN_ID`. LSTM bundles live
under `/models/lstm`; the existing dense pointer is preserved. Score with
`air-quality --models /models --model lstm score --input /data/daily.parquet`.
For a weekly subset, provide the preceding 13 days in the input and add
`--score-start YYYY-MM-DD` to emit only the requested period.

The LSTM scores the last day of each window using absolute standardized
pollutant errors. Separate 99th-percentile validation thresholds determine
flags; the displayed score is the largest error/threshold ratio (flagged
above 1). This matches the source LSTM approach, rather than copying the
dense model's training 95th-percentile threshold. Neither model forecasts
future concentrations. Raw loss values are not directly comparable.

After deploying this code through CI, initialize the second cloud model once
by executing the existing bootstrap job with its arguments overridden to
`bootstrap-lstm --epochs 100`, for example:

```powershell
gcloud run jobs execute air-quality-bootstrap --project=air-quality-tracker-510721 --region=us-east1 --args=bootstrap-lstm,--epochs,100 --wait
```

This uses the bootstrap job's existing private bucket access. It creates
`lstm/active.json` only if absent and never replaces the dense model. No
extra infrastructure, service-account key, or GitHub secret is needed.
Weekly jobs automatically score both initialized models and collect the
LSTM context locally. Results remain subject to 30-day operational expiry.
The dashboard gains a model selector and a comparison on common historical
test dates, including reconstruction MAE and independently computed
observed-exceedance confusion counts. Each test split loses at least its
first 13 days to sequence context; additional gaps reduce coverage.

## Third model: independent pollutant CNN autoencoders

`notebooks/1D CNN Autoencoder.py` is now a runnable entry point to the maintained
implementation in `src/air_quality_tracker/cnn.py`. It loads the real parquet
dataset and uses `pm25` and `ozone_8hr_max`. After `pip install -e .`, run
`python "notebooks/1D CNN Autoencoder.py" --epochs 100` to save a local candidate.
The default output is ignored under `runtime/cnn-candidates/cnn`.

The CNN uses the source's 28-day windows, independent PM2.5 and ozone networks,
strided Conv1D compression, dropout and upsampling decoder. Each pollutant's
scaler is fit only on its observed training values. Windows stay inside their
split and cannot cross gaps. Training uses 2021–2023, early stopping uses
January–June 2024, separate threshold calibration uses July–December 2024,
and the untouched test period is 2025. Separate calibration 99th-percentile
window MSE thresholds define flags; the combined score is the maximum
window-MSE/threshold ratio. A flag refers to a window, not a confirmed event
on its end date. End-day pollutant reconstructions are also saved.

The container CLI accepts `--model cnn` before `train`, `promote`, or `score`.
CNN candidates and their separate active pointer live under `/models/cnn`;
promotion never changes the dense or LSTM pointers. Scoring emits dates where
both pollutants have complete windows. Weekly runs collect 27 preceding days
as context, emit only the target week, and report partial coverage when gaps
prevent scoring. Operational scores still expire after 30 days.

After merge and successful CI deployment, initialize the CNN once:

```powershell
gcloud run jobs execute air-quality-bootstrap --project=air-quality-tracker-510721 --region=us-east1 --args=bootstrap-cnn,--epochs,100 --wait
```

This uses existing infrastructure and permissions, retains the original models,
and makes the CNN available in the dashboard. No new secrets are required.
The dashboard shows both pollutant training curves. For CNN window flags,
the independent concentration reference is any observed exceedance within
that window; reconstructed-concentration evaluation remains end-day only.
Window counts are aligned to end dates and are not unique event counts.
