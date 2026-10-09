"""Cloud jobs stage artifacts locally and use Storage generation preconditions."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import uuid


from .live import previous_week, collect_week


def write_json(blob, data, generation=None):
    blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json", if_generation_match=generation)


def expire(bucket, now=None):
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    removed = 0
    for blob in bucket.list_blobs():
        if blob.time_created <= cutoff:
            blob.delete(if_generation_match=blob.generation)
            removed += 1
    return removed


@contextmanager
def lease(bucket, name, hours=1):
    from google.api_core.exceptions import NotFound, PreconditionFailed
    blob = bucket.blob(f"locks/{name}.json")
    now = datetime.now(timezone.utc)
    generation = 0
    try:
        blob.reload()
        generation = blob.generation
        existing = json.loads(blob.download_as_text(if_generation_match=generation))
        if datetime.fromisoformat(existing["expires_at"]) > now:
            raise RuntimeError("Another execution is already running")
    except NotFound:
        pass
    write_json(blob, {"owner": uuid.uuid4().hex, "expires_at": (now + timedelta(hours=hours)).isoformat()}, generation)
    blob.reload()
    owned_generation = blob.generation
    try:
        yield
    finally:
        try:
            blob.delete(if_generation_match=owned_generation)
        except (NotFound, PreconditionFailed):
            pass


def download_model(bucket, local, model_type='dense'):
    prefix = 'lstm/' if model_type == 'lstm' else ''
    pointer = json.loads(bucket.blob(prefix + "active.json").download_as_text())
    run_id = pointer["run_id"]
    if not run_id or Path(run_id).name != run_id or run_id in (".", ".."):
        raise ValueError("Invalid active model identifier")
    folder = local / run_id
    folder.mkdir(parents=True)
    for name in ("metadata.json", "model.keras", "scaler.joblib"):
        bucket.blob(f"{prefix}{run_id}/{name}").download_to_filename(folder / name)
    (local / "active.json").write_text(json.dumps(pointer))
    return run_id


def bootstrap(args, history, models, operational, local):
    from .cli import train, score
    import pandas as pd
    model_type = 'lstm' if args.command == 'bootstrap-lstm' else 'dense'
    prefix = 'lstm/' if model_type == 'lstm' else ''
    if models.blob(prefix + "active.json").exists():
        print("Active model already exists; bootstrap left it unchanged")
        return
    data = local / "historical.parquet"
    history.blob("triangle_pm25_ozone_daily_2021_2025.parquet").download_to_filename(data)
    model_dir = local / "models"
    train(SimpleNamespace(input=data, models=model_dir, model_type=model_type, seed=42, epochs=args.epochs, validation_start="2024-01-01", test_start="2025-01-01"))
    bundle = next(model_dir.iterdir())
    meta = json.loads((bundle / "metadata.json").read_text())
    meta["input_units"] = {"pm25": "ug/m3", "ozone_8hr_max": "ppb"}
    meta["training_source"] = "EPA AQS historical Triangle daily aggregates"
    (bundle / "metadata.json").write_text(json.dumps(meta, indent=2))
    for path in bundle.iterdir():
        models.blob(f"{prefix}{bundle.name}/{path.name}").upload_from_filename(path, if_generation_match=0)
    # Only initial creation is allowed; candidate training never replaces an active model.
    write_json(models.blob(prefix + "active.json"), {"run_id": bundle.name}, 0)
    (model_dir / "active.json").write_text(json.dumps({"run_id": bundle.name}))
    test = pd.read_parquet(data)
    test = test[pd.to_datetime(test.date) >= "2025-01-01"].copy()
    test["input_source"] = "Historical test period (2025); not current observations"
    test_path = local / "test.parquet"
    test.to_parquet(test_path, index=False)
    score(SimpleNamespace(input=test_path, models=model_dir, operational=local / "operational"))
    output = next((local / "operational" / "scores").iterdir())
    operational.blob(f"scores/{prefix}historical/2025-test.parquet").upload_from_filename(output, if_generation_match=0)
    print(f"Bootstrapped active model {bundle.name}")


def weekly(args, models, operational, local):
    from .cli import score
    start, end = previous_week()
    key = f"{start:%Y-%m-%d}"
    frame = collect_week(start, end)
    source = local / "week.parquet"
    frame.to_parquet(source, index=False)
    operational.blob(f"collected/{key}.parquet").upload_from_filename(source)
    complete = frame.dropna(subset=["pm25", "ozone_8hr_max"])
    missing = [str(d.date()) for d in frame.loc[frame[["pm25", "ozone_8hr_max"]].isna().any(axis=1), "date"]]
    report = {"week_start": str(start), "week_end": str(end - timedelta(days=1)), "completed_at": datetime.now(timezone.utc).isoformat(), "expected_days": 7, "scored_days": len(complete), "missing_dates": missing, "source": "AirNow preliminary observations", "status": "complete" if len(complete) == 7 else "partial" if len(complete) else "no-data"}
    if len(complete):
        run_id = download_model(models, local / "models")
        report["model_version"] = run_id
        score(SimpleNamespace(input=source, models=local / "models", operational=local / "operational"))
        result = next((local / "operational" / "scores").iterdir())
        operational.blob(f"scores/live/{key}.parquet").upload_from_filename(result)
    if models.blob('lstm/active.json').exists():
        # A seven-day run needs thirteen preceding calendar days for its first window.
        context = collect_week(start - timedelta(days=13), start)
        import pandas as pd
        lstm_source = local / 'lstm-input.parquet'
        pd.concat([context, frame], ignore_index=True).to_parquet(lstm_source, index=False)
        run_id = download_model(models, local / 'lstm-models', 'lstm')
        report['lstm_model_version'] = run_id
        try:
            score(SimpleNamespace(input=lstm_source, models=local / 'lstm-models', operational=local / 'lstm-operational', score_start=str(start)))
        except ValueError as error:
            if not str(error).startswith(('No complete 14-day windows', 'No complete windows in requested')):
                raise
            report['lstm_status'] = 'no-complete-windows'
            report['lstm_scored_days'] = 0
        else:
            result = next((local / 'lstm-operational' / 'scores').iterdir())
            scored = pd.read_parquet(result)
            report['lstm_scored_days'] = len(scored)
            report['lstm_status'] = 'complete' if len(scored) == 7 else 'partial'
            operational.blob(f'scores/lstm/live/{key}.parquet').upload_from_filename(result)
    write_json(operational.blob(f"reports/{key}.json"), report)
    print(json.dumps(report))
    if not len(complete):
        raise RuntimeError("No complete daily observations available; no scores were fabricated")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("bootstrap", "bootstrap-lstm", "weekly", "cleanup"))
    parser.add_argument("--history-bucket", default="air-quality-tracker-510721-historical")
    parser.add_argument("--models-bucket", default="air-quality-tracker-510721-models")
    parser.add_argument("--operational-bucket", default="air-quality-tracker-510721-operational")
    parser.add_argument("--epochs", type=int, default=200)
    args = parser.parse_args()
    from google.cloud import storage
    client = storage.Client()
    operational = client.bucket(args.operational_bucket)
    if args.command == "cleanup":
        print(f"Expired operational objects: {expire(operational)}")
        return
    models = client.bucket(args.models_bucket)
    history = client.bucket(args.history_bucket)
    # Separate daily cleanup avoids relying on weekly executions alone.
    expire(operational)
    with lease(operational, args.command, hours=2 if args.command.startswith('bootstrap') else 1):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            if args.command.startswith('bootstrap'):
                bootstrap(args, history, models, operational, local)
            else:
                weekly(args, models, operational, local)


if __name__ == "__main__":
    main()
