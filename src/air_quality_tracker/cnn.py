"""Independent pollutant CNNs; 28-day window flags aligned to window end dates."""
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid

from .cli import inputs

WINDOW = 28
POLLUTANTS = {'pm25': 'pm25', 'ozone': 'ozone_8hr_max'}


def windows(frame, column, scaler):
    import numpy as np
    import pandas as pd
    values = frame[column].to_numpy(dtype=float)
    sequences, ends = [], []
    for end in range(WINDOW - 1, len(frame)):
        start = end - WINDOW + 1
        segment = values[start:end + 1]
        if frame.iloc[end].date - frame.iloc[start].date != pd.Timedelta(days=WINDOW - 1) or not np.isfinite(segment).all():
            continue
        sequences.append(scaler.transform(segment.reshape(-1, 1)))
        ends.append(end)
    return np.asarray(sequences, dtype='float32').reshape(-1, WINDOW, 1), ends


def build_model():
    import tensorflow as tf
    layers = tf.keras.layers
    model = tf.keras.Sequential([
        layers.Input((WINDOW, 1)),
        layers.Conv1D(16, 5, strides=2, padding='same', activation='relu'),
        layers.Dropout(.1),
        layers.Conv1D(8, 3, strides=2, padding='same', activation='relu'),
        layers.UpSampling1D(2), layers.Conv1D(8, 3, padding='same', activation='relu'),
        layers.UpSampling1D(2), layers.Conv1D(16, 5, padding='same', activation='relu'),
        layers.Conv1D(1, 3, padding='same'),
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss='mse')
    return model


def predictions(model, x):
    import numpy as np
    result = model.predict(x, batch_size=32, verbose=0)
    if not np.isfinite(result).all():
        raise ValueError('Nonfinite CNN reconstruction')
    return result, np.square(x - result).mean(axis=(1, 2))


def train(args):
    import joblib
    import numpy as np
    import pandas as pd
    import tensorflow as tf
    from sklearn.preprocessing import StandardScaler
    tf.keras.utils.set_random_seed(args.seed)
    tf.config.experimental.enable_op_determinism()
    frame = inputs(args.input, drop_incomplete=False)
    val, cal, test = map(pd.Timestamp, (args.validation_start, args.calibration_start, args.test_start))
    if not val < cal < test:
        raise ValueError('CNN split dates must increase: validation < calibration < test')
    groups = [frame[frame.date < val], frame[(frame.date >= val) & (frame.date < cal)],
              frame[(frame.date >= cal) & (frame.date < test)], frame[frame.date >= test]]
    scalers, models, histories, thresholds, evaluations = {}, {}, {}, {}, {}
    for pollutant, column in POLLUTANTS.items():
        observed = groups[0][column].dropna().to_numpy().reshape(-1, 1)
        if not len(observed):
            raise ValueError(f'No CNN training observations for {pollutant}')
        scaler = scalers[pollutant] = StandardScaler().fit(observed)
        sequences = [windows(group, column, scaler) for group in groups]
        if any(len(x) < 2 for x, _ in sequences):
            raise ValueError(f'Each split needs two complete 28-day {pollutant} windows')
        model = models[pollutant] = build_model()
        options = tf.data.Options()
        options.threading.private_threadpool_size = 1
        datasets = [tf.data.Dataset.from_tensor_slices((x, x)).batch(32).with_options(options) for x, _ in sequences[:2]]
        history = model.fit(datasets[0], validation_data=datasets[1], epochs=args.epochs, shuffle=False,
                            callbacks=[tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)], verbose=2)
        histories[pollutant] = history.history
        errors = [predictions(model, x)[1] for x, _ in sequences]
        thresholds[pollutant] = max(float(np.quantile(errors[2], .99)), 1e-8)
        evaluations[pollutant] = [pd.Series(e, index=group.iloc[ends].date) for group, (_, ends), e in zip(groups, sequences, errors)]
    metrics = {}
    for index, name in enumerate(('train', 'validation', 'calibration', 'test')):
        errors = pd.concat([evaluations[p][index].rename(p) for p in POLLUTANTS], axis=1, join='inner')
        if errors.empty:
            raise ValueError(f'No common pollutant window end dates in {name}')
        ratios = errors / pd.Series(thresholds)
        metrics[name] = {'rows': len(errors), 'mse': float(errors.to_numpy().mean()), 'anomaly_rate': float((ratios.max(axis=1) > 1).mean())}
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    bundle = args.models / run_id
    bundle.mkdir(parents=True, exist_ok=False)
    for pollutant, model in models.items():
        model.save(bundle / f'{pollutant}.keras')
    joblib.dump(scalers, bundle / 'scaler.joblib')
    history = {name: pd.concat([pd.Series(h[name]) for h in histories.values()], axis=1).mean(axis=1).tolist() for name in ('loss', 'val_loss')}
    meta = {'run_id': run_id, 'model_type': 'cnn', 'lookback': WINDOW, 'features': list(POLLUTANTS.values()),
            'threshold': 1., 'pollutant_thresholds': thresholds, 'threshold_method': '99th percentile of independent calibration window MSE',
            'seed': args.seed, 'epochs': args.epochs, 'validation_start': args.validation_start,
            'calibration_start': args.calibration_start, 'test_start': args.test_start,
            'dataset_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(), 'git_commit': os.environ.get('GIT_COMMIT', 'unknown'),
            'history': history, 'pollutant_history': histories, 'metrics': metrics}
    (bundle / 'metadata.json').write_text(json.dumps(meta, indent=2))
    print(f'CNN candidate saved at {bundle}. Promote explicitly after review.')


def score(args, bundle, meta):
    import joblib
    import pandas as pd
    import tensorflow as tf
    frame = inputs(args.input, drop_incomplete=False)
    scalers = joblib.load(bundle / 'scaler.joblib')
    parts = []
    for pollutant, column in POLLUTANTS.items():
        x, ends = windows(frame, column, scalers[pollutant])
        if not len(x):
            raise ValueError('No complete 28-day windows to score; missing days are never filled')
        prediction, errors = predictions(tf.keras.models.load_model(bundle / f'{pollutant}.keras'), x)
        part = pd.DataFrame(index=frame.iloc[ends].date)
        part[f'{pollutant}_reconstructed'] = scalers[pollutant].inverse_transform(prediction[:, -1, :])[:, 0]
        part[f'{pollutant}_reconstruction_error'] = errors
        part[f'{pollutant}_anomaly'] = errors > meta['pollutant_thresholds'][pollutant]
        part[f'{pollutant}_window_threshold'] = meta['pollutant_thresholds'][pollutant]
        part[f'{pollutant}_window_observed_max'] = [float(frame[column].iloc[end - WINDOW + 1:end + 1].max()) for end in ends]
        parts.append(part)
    result = parts[0].join(parts[1], how='inner').join(frame.set_index('date')).reset_index()
    if getattr(args, 'score_start', None):
        result = result[result.date >= pd.Timestamp(args.score_start)]
    if result.empty:
        raise ValueError('No complete windows in requested scoring period')
    result['reconstruction_error'] = (result.pm25_reconstruction_error / meta['pollutant_thresholds']['pm25']).combine(result.ozone_reconstruction_error / meta['pollutant_thresholds']['ozone'], max)
    result['anomaly'] = result.pm25_anomaly | result.ozone_anomaly
    result['anomaly_threshold'] = 1.
    result['model_version'] = meta['run_id']
    result['model_type'] = 'cnn'
    result['flag_scope'] = '28-day window ending on date; not a confirmed anomaly on that day'
    output = args.operational / 'scores'
    output.mkdir(parents=True, exist_ok=True)
    target = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8] + '.parquet')
    result.to_parquet(target, index=False)
    print(target)
