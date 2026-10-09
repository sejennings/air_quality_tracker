"""14-day LSTM reconstruction; thresholds calibrated without touching test data."""
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid

from .cli import FEATURES, inputs

LOOKBACK = 14


def windows(frame, scaler, lookback=LOOKBACK):
    """Skip gaps and incomplete sequences; score each window's last calendar day."""
    import numpy as np
    import pandas as pd
    x = scaler.transform(frame[FEATURES]).astype('float32')
    sequences, ends = [], []
    for end in range(lookback - 1, len(frame)):
        start = end - lookback + 1
        if frame.iloc[end].date - frame.iloc[start].date != pd.Timedelta(days=lookback - 1):
            continue
        window = x[start:end + 1]
        if np.isfinite(window).all():
            sequences.append(window)
            ends.append(end)
    return np.asarray(sequences, dtype='float32').reshape(-1, lookback, len(FEATURES)), ends


def build_model():
    import tensorflow as tf
    model = tf.keras.Sequential([
        tf.keras.layers.Input((LOOKBACK, len(FEATURES))),
        tf.keras.layers.LSTM(32, return_sequences=True),
        tf.keras.layers.LSTM(16),
        tf.keras.layers.RepeatVector(LOOKBACK),
        tf.keras.layers.LSTM(16, return_sequences=True),
        tf.keras.layers.LSTM(32, return_sequences=True),
        tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(len(FEATURES))),
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=.001), loss='mse')
    return model


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
        raise ValueError('Validation must start before test')
    groups = [frame[frame.date < val_date], frame[(frame.date >= val_date) & (frame.date < test_date)], frame[frame.date >= test_date]]
    if groups[0].empty:
        raise ValueError('No training observations')
    scaler = StandardScaler().fit(groups[0][FEATURES])
    xs = [windows(group, scaler)[0] for group in groups]
    if any(len(x) < 2 for x in xs):
        raise ValueError('Each split needs at least two complete 14-day windows')
    model = build_model()
    options = tf.data.Options()
    options.threading.private_threadpool_size = 1
    datasets = [tf.data.Dataset.from_tensor_slices((x, x)).batch(32).with_options(options) for x in xs[:2]]
    history = model.fit(datasets[0], validation_data=datasets[1], epochs=args.epochs, shuffle=False,
                        callbacks=[tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)], verbose=2)
    # Match the source model: last-day pollutant errors and validation 99th percentiles.
    errors = [np.abs(x[:, -1, :2] - model.predict(x, batch_size=32, verbose=0)[:, -1, :2]) for x in xs]
    if any(not np.isfinite(e).all() for e in errors):
        raise ValueError('Nonfinite reconstruction errors')
    thresholds = np.maximum(np.quantile(errors[1], .99, axis=0), 1e-8)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    bundle = args.models / run_id
    bundle.mkdir(parents=True, exist_ok=False)
    model.save(bundle / 'model.keras')
    joblib.dump(scaler, bundle / 'scaler.joblib')
    metadata = {'run_id': run_id, 'model_type': 'lstm', 'lookback': LOOKBACK, 'features': FEATURES,
                'threshold': 1., 'pollutant_thresholds': thresholds.tolist(),
                'threshold_method': '99th percentile of validation last-day absolute standardized pollutant errors',
                'seed': args.seed, 'epochs': args.epochs, 'validation_start': args.validation_start, 'test_start': args.test_start,
                'dataset_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(), 'git_commit': os.environ.get('GIT_COMMIT', 'unknown'),
                'history': history.history, 'metrics': {name: {'rows': len(e), 'mse': float(np.square(e).mean()),
                'anomaly_rate': float(((e / thresholds).max(axis=1) > 1).mean())}
                for name, e in zip(('train', 'validation', 'test'), errors)}}
    (bundle / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    print(f'LSTM candidate saved at {bundle}. Promote explicitly after review.')


def reconstruct(frame, scaler, model, metadata):
    import numpy as np
    x, ends = windows(frame, scaler, metadata['lookback'])
    if not len(x):
        raise ValueError('No complete 14-day windows to score; missing days are never filled')
    prediction = model.predict(x, batch_size=32, verbose=0)[:, -1, :]
    if not np.isfinite(prediction).all():
        raise ValueError('Nonfinite model reconstruction')
    return frame.iloc[ends].copy(), x[:, -1, :], prediction
