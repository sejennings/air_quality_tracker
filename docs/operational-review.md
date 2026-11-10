# Operational review — November 9, 2026

The scheduled updates are working. There is no clear evidence from the retained live scores that an immediate retrain is needed. This is a point-in-time review, not an automated drift assessment.

## Deployment and scheduled runs

The latest five GitHub Actions runs passed. The [latest run](https://github.com/sejennings/air_quality_tracker/actions/runs/41154301528), for commit `5ca3d37be91d60a15b8e640101915807b2b63274`, passed its Terraform, test, and deployment jobs.

The November 9 weekly Cloud Run execution, `air-quality-weekly-n45cg`, completed successfully at 8:01 a.m. Eastern. It scored November 2–8 with all seven days available for dense, LSTM, and CNN models. The November 9 cleanup execution, `air-quality-cleanup-bwvzb`, also succeeded. Both Scheduler jobs are enabled, with weekly scoring at Monday 8:00 a.m. and cleanup daily at 5:00 a.m., America/New_York.

All five retained weekly reports show seven dense scores and no missing daily inputs. All three reports containing sequence-model results show seven scores for each sequence model.

## Active versions

| Model | Active run |
| --- | --- |
| Dense | `20261005T225047Z-b9711751` |
| LSTM | `20261031T010143Z-2f6dad5e` |
| CNN | `20261031T010055Z-d4687d2b` |

These are artifact creation dates. Their training observations are from 2021–2023, not October 2026. A newly created bundle does not mean its training data is recent.

## Recent reconstruction errors

The following MAEs were calculated directly from retained score files. PM2.5 errors are in ug/m3; ozone errors are in ppb. Each weekly row contains seven scored days. CNN values describe end-day reconstructions, while its anomaly decisions use whole-window errors.

| Week starting | Model | PM2.5 MAE | Ozone MAE | Flags |
| --- | --- | ---: | ---: | ---: |
| October 19 | Dense | 3.335 | 6.810 | 0 |
| October 26 | Dense | 1.767 | 6.303 | 0 |
| November 2 | Dense | 1.334 | 3.686 | 0 |
| October 19 | LSTM | 1.881 | 3.758 | 0 |
| October 26 | LSTM | 2.045 | 7.752 | 0 |
| November 2 | LSTM | 0.873 | 3.781 | 0 |
| October 19 | CNN | 0.810 | 1.217 | 0 |
| October 26 | CNN | 0.398 | 0.949 | 0 |
| November 2 | CNN | 0.340 | 0.569 | 0 |

Errors do not show a sustained increase across these weeks. Zero flags does not establish that events were detected correctly: verified event labels are unavailable, and the three models use different thresholds and decision intervals.

The retained 2025 historical exports give LSTM MAEs of 2.192 and 5.647 (338 days, 3 flags), and CNN MAEs of 0.476 and 0.894 (310 windows, 40 flags). These full-year results are context, not seasonally matched live baselines. The CNN metadata reports a 12.9% test flag rate versus 1.47% on calibration; investigate that difference before interpreting its threshold as stable across years. The dense historical score export was not present in the retained files inspected.

## Retraining assessment

Keep the current models for now and review performance again as more complete weeks accumulate. Three shared live weeks are too short and seasonally narrow to establish long-term stability. AirNow monitor coverage and aggregation also differ from historical AQS inputs, so source changes need to be checked before attributing changes to the models.

A retraining review becomes useful if errors, bias, or flag rates change persistently against a seasonally comparable baseline after input checks, or if newer quality-controlled historical data becomes available. Missing sequence context needs an ingestion or coverage fix; retraining does not restore missing observations.

For a candidate, use newer quality-controlled data, chronological splits, separate threshold calibration, and a later untouched evaluation period. Compare candidate and active models on the same dates and retain the active version for rollback. Do not train on the existing 2025 test set and continue calling its results held out. Bootstrap commands leave existing active pointers unchanged; replacement requires explicit promotion.

## Verification limits

The cloud execution states, Scheduler states, active pointers, model metadata, weekly reports, and retained score files were inspected read-only using the authenticated Google Cloud CLI. Recent CI results were checked through GitHub CLI. No production model was retrained or promoted, and no cloud configuration was changed. The 22 local pipeline tests passed, including temporary model training and promotion fixtures. Historical input validation passed with 1,811 valid rows; the documentation whitespace check passed.

Docker Desktop's engine was unavailable locally, and the local dashboard test could not run because Streamlit is missing. The latest deployed CI run passed the container and dashboard checks. Documentation changes remain local until committed and deployed through the usual workflow.
