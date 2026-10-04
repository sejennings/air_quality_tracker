import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid

from .retention import cleanup

FEATURES = ["pm25", "ozone_8hr_max", "doy_sin", "doy_cos"]


def inputs(path):
    import numpy as np
    import pandas as pd
    frame = pd.read_parquet(path)
    required = {"date", "pm25", "ozone_8hr_max"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing columns: {required - set(frame.columns)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise ValueError("Daily input must have unique, non-null dates")
    frame = frame.sort_values("date").copy()
    phase = 2 * np.pi * frame["date"].dt.dayofyear / 365.25
    frame["doy_sin"], frame["doy_cos"] = np.sin(phase), np.cos(phase)
    if np.isinf(frame[FEATURES].to_numpy(dtype=float)).any():
        raise ValueError("Infinite model inputs")
    return frame.dropna(subset=FEATURES)


def train(args):
    import joblib
    import numpy as np
    import pandas as pd
    import tensorflow as tf
    from sklearn.preprocessing import StandardScaler
    tf.keras.utils.set_random_seed(args.seed)
    tf.config.experimental.enable_op_determinism()
    frame = inputs(args.input)
    val_date, test_date = pd.Timestamp(args.validation_start), pd.Timestamp(args.test_start)
    if val_date >= test_date:
        raise ValueError("Validation must start before test")
    groups = [frame[frame.date < val_date], frame[(frame.date >= val_date) & (frame.date < test_date)], frame[frame.date >= test_date]]
    if any(len(group) < 2 for group in groups):
        raise ValueError("Train, validation, and untouched test splits each need at least two rows")
    scaler = StandardScaler().fit(groups[0][FEATURES])
    xs = [scaler.transform(group[FEATURES]) for group in groups]
    model = tf.keras.Sequential([tf.keras.layers.Input((4,)), tf.keras.layers.Dense(3, activation="relu"), tf.keras.layers.Dense(2, activation="relu", name="latent_space"), tf.keras.layers.Dense(3, activation="relu"), tf.keras.layers.Dense(4)])
    model.compile(optimizer="adam", loss="mse")
    history = model.fit(xs[0], xs[0], validation_data=(xs[1], xs[1]), epochs=args.epochs, batch_size=32, shuffle=False, callbacks=[tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=15, restore_best_weights=True)], verbose=2)
    errors = [np.mean((x - model.predict(x, verbose=0)) ** 2, axis=1) for x in xs]
    threshold = float(np.percentile(errors[0], 95))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    bundle = args.models / run_id
    bundle.mkdir(parents=True, exist_ok=False)
    model.save(bundle / "model.keras")
    joblib.dump(scaler, bundle / "scaler.joblib")
    metadata = {"run_id": run_id, "features": FEATURES, "threshold": threshold, "seed": args.seed, "epochs": args.epochs, "validation_start": args.validation_start, "test_start": args.test_start, "dataset_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(), "git_commit": os.environ.get("GIT_COMMIT", "unknown"), "history": history.history, "metrics": {name: {"rows": len(error), "mse": float(error.mean()), "anomaly_rate": float((error > threshold).mean())} for name, error in zip(("train", "validation", "test"), errors)}}
    (bundle / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata["metrics"], indent=2))
    print(f"Candidate saved at {bundle}. Promote explicitly after review.")


def score(args):
    import joblib
    import numpy as np
    import tensorflow as tf
    run_id = (args.models / "active.json").read_text()
    bundle = args.models / json.loads(run_id)["run_id"]
    if bundle.parent.resolve() != args.models.resolve():
        raise ValueError("Invalid model path")
    meta = json.loads((bundle / "metadata.json").read_text())
    frame = inputs(args.input)
    if frame.empty:
        raise ValueError("No complete observations to score")
    x = joblib.load(bundle / "scaler.joblib").transform(frame[meta["features"]])
    prediction = tf.keras.models.load_model(bundle / "model.keras").predict(x, verbose=0)
    errors = np.square(x - prediction)
    frame["reconstruction_error"] = errors.mean(axis=1)
    frame["pm25_reconstruction_error"] = errors[:, meta["features"].index("pm25")]
    frame["ozone_reconstruction_error"] = errors[:, meta["features"].index("ozone_8hr_max")]
    frame["anomaly"] = frame.reconstruction_error > meta["threshold"]
    frame["model_version"] = meta["run_id"]
    out = args.operational / "scores"
    out.mkdir(parents=True, exist_ok=True)
    target = out / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".parquet")
    frame.to_parquet(target, index=False)
    print(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, default=Path("/models"))
    parser.add_argument("--operational", type=Path, default=Path("/operational"))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("train", "score", "validate"):
        p = sub.add_parser(command)
        p.add_argument("--input", type=Path, required=True)
        if command == "train":
            p.add_argument("--validation-start", default="2024-01-01")
            p.add_argument("--test-start", default="2025-01-01")
            p.add_argument("--epochs", type=int, default=200)
            p.add_argument("--seed", type=int, default=42)
    p = sub.add_parser("promote")
    p.add_argument("run_id")
    sub.add_parser("cleanup")
    args = parser.parse_args()
    if args.command == "cleanup":
        print(f"Removed {cleanup(args.operational)} expired files")
    elif args.command == "train":
        train(args)
    elif args.command == "score":
        cleanup(args.operational)
        score(args)
    elif args.command == "validate":
        print(f"Valid rows: {len(inputs(args.input))}")
    else:
        bundle = args.models / args.run_id
        if bundle.parent.resolve() != args.models.resolve() or not all((bundle / f).is_file() for f in ("metadata.json", "model.keras", "scaler.joblib")):
            raise ValueError("Invalid or incomplete model bundle")
        pending = args.models / "active.pending"
        pending.write_text(json.dumps({"run_id": args.run_id}))
        pending.replace(args.models / "active.json")


if __name__ == "__main__":
    main()
