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
              GitHub Actions
              runs every hour
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
