import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler

tf.keras.utils.set_random_seed(42)

# ---------- 1. Prepare data ----------
df = pd.read_parquet(
    "data/triangle_pm25_ozone_daily_2021_2025.parquet"
)
# Assumes df contains: date, pm25, ozone
# Change these names to match your actual columns.
TARGETS = ["pm25", "ozone"]
LOOKBACK = 14

data = df.copy()
data["date"] = pd.to_datetime(data["date"])
data = data.set_index("date").sort_index()

if data.index.has_duplicates:
    raise ValueError("Aggregate your data to one row per day first.")

# Preserve daily spacing; missing dates become NaN.
data = data.asfreq("D")

# Seasonal features
day_of_year = data.index.dayofyear
data["season_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
data["season_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)

FEATURES = TARGETS + ["season_sin", "season_cos"]

train_end = int(len(data) * 0.70)
val_end = int(len(data) * 0.85)

# Fit scaling ONLY on training observations.
x_scaler = StandardScaler()
y_scaler = StandardScaler()

x_scaler.fit(data.iloc[:train_end][FEATURES].dropna())
y_scaler.fit(data.iloc[:train_end][TARGETS].dropna())

features = x_scaler.transform(data[FEATURES]).astype("float32")
targets = y_scaler.transform(data[TARGETS]).astype("float32")

# ---------- 2. Create 14-day input windows ----------
LOOKBACK = 14

X, window_end_positions = [], []

for end in range(LOOKBACK, len(data) + 1):
    window = features[end - LOOKBACK:end]

    if not np.isfinite(window).all():
        continue

    X.append(window)
    window_end_positions.append(end - 1)

X = np.asarray(X, dtype="float32")
window_end_positions = np.asarray(window_end_positions)
window_start_positions = window_end_positions - LOOKBACK + 1

# Keep each window entirely within its split.
train_mask = window_end_positions < train_end
val_mask = (
    (window_start_positions >= train_end)
    & (window_end_positions < val_end)
)
test_mask = window_start_positions >= val_end

X_train = X[train_mask]
X_val = X[val_mask]
X_test = X[test_mask]

if any(len(part) == 0 for part in [X_train, X_val, X_test]):
    raise ValueError("Not enough complete windows in each split.")

# ---------- 3. Build LSTM autoencoder ----------
n_features = len(FEATURES)

model = tf.keras.Sequential([
    tf.keras.layers.Input(shape=(LOOKBACK, n_features)),

    # Encoder: compress the sequence into 16 values.
    tf.keras.layers.LSTM(32, return_sequences=True),
    tf.keras.layers.LSTM(16),

    # Decoder: reconstruct all 14 days.
    tf.keras.layers.RepeatVector(LOOKBACK),
    tf.keras.layers.LSTM(16, return_sequences=True),
    tf.keras.layers.LSTM(32, return_sequences=True),
    tf.keras.layers.TimeDistributed(
        tf.keras.layers.Dense(n_features)
    )
])

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss="mse"
)

model.summary()

# ---------- 4. Train: input and target are identical ----------
history = model.fit(
    X_train,
    X_train,
    validation_data=(X_val, X_val),
    epochs=100,
    batch_size=32,
    shuffle=False,
    callbacks=[
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True
        )
    ],
    verbose=1
)

# ---------- 5. Calculate pollutant-specific anomaly scores ----------
val_reconstructed = model.predict(X_val, verbose=0)
test_reconstructed = model.predict(X_test, verbose=0)

# Score the LAST day of each window.
# This assigns one score to each date, using its preceding context.
pollutant_indices = [FEATURES.index(col) for col in TARGETS]

val_errors = np.abs(
    X_val[:, -1, pollutant_indices]
    - val_reconstructed[:, -1, pollutant_indices]
)

test_errors = np.abs(
    X_test[:, -1, pollutant_indices]
    - test_reconstructed[:, -1, pollutant_indices]
)

# Starting heuristic: separate 99th-percentile validation thresholds.
thresholds = np.quantile(val_errors, 0.99, axis=0)

results = pd.DataFrame({
    "date": data.index[window_end_positions[test_mask]]
})

for j, pollutant in enumerate(TARGETS):
    results[f"{pollutant}_score"] = test_errors[:, j]
    results[f"{pollutant}_threshold"] = thresholds[j]
    results[f"{pollutant}_anomaly"] = (
        test_errors[:, j] > thresholds[j]
    )

print(results.head())
print(results[[f"{p}_anomaly" for p in TARGETS]].sum())
