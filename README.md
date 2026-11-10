# Air Quality Tracker

Air Quality Tracker follows daily PM2.5 and ozone concentrations across North Carolina's Triangle region. It compares observations with three autoencoders to highlight patterns that deserve a closer look.

The [public dashboard](https://air-quality-dashboard-236256523935.us-east1.run.app) shows recent observations, model scores, coverage, and historical evaluation results. An anomaly flag means the model found a pattern difficult to reconstruct. It does not confirm a pollution event or predict tomorrow's air quality.

## How it works

Every Monday at 8:00 a.m. America/New_York, a Cloud Run job collects AirNow observations for the previous Monday through Sunday, validates the inputs, and scores them with the active models. Daily cleanup runs at 5:00 a.m. Operational data expires after 30 days; historical inputs and model bundles are retained.

The inputs are regional daily PM2.5 means in ug/m3 and ozone 8-hour peaks in ppb, aggregated from available monitors in Wake, Durham, and Orange counties. AirNow observations are preliminary and can differ from the EPA AQS data used for training. Missing values are never filled in to manufacture a score.

Weekly updates use existing models. Training and model promotion are separate steps.

## Models

| Model | Input | How a flag is chosen |
| --- | --- | --- |
| Dense autoencoder | One day of pollutants and seasonal features | Reconstruction MSE above the training 95th percentile |
| LSTM autoencoder | 14 consecutive days of pollutants and seasonal features | Either pollutant's end-day standardized absolute error exceeds its validation 99th percentile |
| Independent pollutant CNNs | 28 consecutive days for each pollutant | Either network's window MSE exceeds its calibration 99th percentile |

Training uses 2021–2023, validation uses 2024, and held-out testing uses 2025. The CNN divides 2024 into January–June for early stopping and July–December for threshold calibration. Sequence windows stay inside their split and cannot cross missing dates or pollutant values.

The LSTM needs 13 preceding days of context; the CNN needs 27. Missing context can reduce their coverage even when the dense model scores every day. CNN flags describe a whole window. End-day reconstructions do not turn them into confirmed events on that date. Raw losses and anomaly scores differ across architectures and should not be ranked against one another.

## Local development

Install Python 3.11 or later and the package:

```powershell
pip install -e .
air-quality --help
```

Validate the maintained dataset:

```powershell
air-quality validate --input data/triangle_pm25_ozone_daily_2021_2025.parquet
```

Train a candidate and explicitly promote the run you have reviewed:

```powershell
air-quality --models runtime/models --model lstm train --input data/triangle_pm25_ozone_daily_2021_2025.parquet --epochs 100
air-quality --models runtime/models --model lstm promote RUN_ID
air-quality --models runtime/models --model lstm --operational runtime/operational score --input data/triangle_pm25_ozone_daily_2021_2025.parquet
```

Use `--model dense` or `--model cnn` for the other architectures. Each has its own active pointer; promoting one leaves the others unchanged. To score a weekly subset with a sequence model, include its preceding context and pass `--score-start YYYY-MM-DD`.

With Docker Desktop running, `./scripts/test-container.ps1` builds the runtime and runs the pipeline tests. [Container instructions](scripts/README.md) cover private image pulls. CI also tests the dashboard and Terraform configuration, then publishes the tested images and deploys through Terraform.

## Checking updates and deciding when to retrain

Start with the weekly coverage report, then inspect each model's coverage and version. A successful job can still produce partial sequence coverage. Fix missing observations, unit changes, or monitor aggregation problems before treating an unusual score pattern as model drift.

Review reconstruction MAE, RMSE, bias, and flag rates over several complete weeks against a seasonally comparable baseline for the same model. A sustained change after input checks is a reason to investigate a new training candidate. A single flagged week or a model's age alone is not enough evidence.

The dashboard's observed-concentration comparison is a separate benchmark, not a set of verified event labels. Historical reconstruction loss does not establish live detection accuracy. There is currently no automated drift test or retraining trigger, so a green deployment does not certify model quality.

Before replacing a model, evaluate the candidate and active model on the same later, untouched period. Keep training, threshold calibration, and evaluation separate; record coverage and pollutant-unit errors as well as flag rates. Preserve the previous active version for rollback. Bootstrap commands only initialize missing pointers and cannot replace an existing active model.

See the [latest operational review](docs/operational-review.md) for the dated checks and retraining assessment.

## Deployment and further reading

- [Cloud Run operations](deploy/cloud-run/README.md): live collection, schedules, retention, and model initialization.
- [Terraform deployment](deploy/terraform/README.md): infrastructure and CI deployment.
- [Model development notes](notebooks/model_development.md): maintained architectures and evaluation boundaries.
- [Ubuntu deployment](deploy/README.md): an alternative host setup, currently on hold.
