# Install once:
# pip install tensorflow pandas numpy scikit-learn matplotlib pyarrow

import numpy as np
import pandas as pd
import tensorflow as tf
import matplotlib.pyplot as plt

from sklearn.preprocessing import StandardScaler
from tensorflow.keras import layers, Model

tf.keras.utils.set_random_seed(42)

WINDOW = 28  # Must be divisible by 4 for this architecture
POLLUTANTS = ["pm25", "ozone"]  # Adjust to your column names

# Use your existing dataframe, or load it:
# df = pd.read_parquet("data/triangle_pm25_ozone_daily_2021_2025.parquet")

# ---------------------------------------------------------
# 1. Prepare a daily time series
# ---------------------------------------------------------
data = df.copy()
data["date"] = pd.to_datetime(data["date"]).dt.normalize()

if data["date"].duplicated().any():
    raise ValueError("Expected one row per date. Aggregate duplicates first.")

data = (
    data.set_index("date")
    .sort_index()[POLLUTANTS]
    .apply(pd.to_numeric, errors="coerce")
    .asfreq("D")
    .replace([np.inf, -np.inf], np.nan)
)

# Missing days remain missing. Windows containing gaps are skipped.
# This avoids treating nonconsecutive observations as consecutive days.

# Example split dates for 2021–2025 data.
# Validation selects the training stopping point.
# Calibration sets the anomaly threshold independently.
train = data.loc[data.index < "2024-01-01"]
validation = data.loc[
    (data.index >= "2024-01-01") & (data.index < "2024-07-01")
]
calibration = data.loc[
    (data.index >= "2024-07-01") & (data.index < "2025-01-01")
]
test = data.loc[data.index >= "2025-01-01"]


# ---------------------------------------------------------
# 2. Create windows within each split
# ---------------------------------------------------------
def make_windows(series, scaler, window=WINDOW):
    values = series.to_numpy(dtype=np.float32)
    windows, end_dates = [], []

    for start in range(len(values) - window + 1):
        segment = values[start:start + window]

        if not np.isfinite(segment).all():
            continue

        scaled = scaler.transform(segment.reshape(-1, 1))
        windows.append(scaled)
        end_dates.append(series.index[start + window - 1])

    if not windows:
        raise ValueError(
            f"No complete {window}-day windows for {series.name}. "
            "Check missing values and split lengths."
        )

    return (
        np.stack(windows).astype(np.float32),
        pd.DatetimeIndex(end_dates),
    )


# ---------------------------------------------------------
# 3. Build the CNN autoencoder
# ---------------------------------------------------------
def build_autoencoder(window=WINDOW):
    if window % 4 != 0:
        raise ValueError("WINDOW must be divisible by 4.")

    inputs = layers.Input(shape=(window, 1))

    # Encoder: compress the time dimension
    x = layers.Conv1D(
        16, kernel_size=5, strides=2,
        padding="same", activation="relu"
    )(inputs)
    x = layers.Dropout(0.1)(x)
    x = layers.Conv1D(
        8, kernel_size=3, strides=2,
        padding="same", activation="relu"
    )(x)

    # Decoder: reconstruct the original sequence
    x = layers.UpSampling1D(size=2)(x)
    x = layers.Conv1D(
        8, kernel_size=3, padding="same", activation="relu"
    )(x)
    x = layers.UpSampling1D(size=2)(x)
    x = layers.Conv1D(
        16, kernel_size=5, padding="same", activation="relu"
    )(x)

    # Linear output because standardized values can be negative
    outputs = layers.Conv1D(
        1, kernel_size=3, padding="same"
    )(x)

    model = Model(inputs, outputs)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="mse",
    )
    return model


def reconstruction_error(model, windows):
    reconstructed = model.predict(windows, verbose=0)
    return np.mean(
        np.square(windows - reconstructed),
        axis=(1, 2),
    )


# ---------------------------------------------------------
# 4. Train and score each pollutant independently
# ---------------------------------------------------------
models = {}
scalers = {}
thresholds = {}
results = {}

for pollutant in POLLUTANTS:
    # Fit scaling ONLY on observed training values
    observed_train = train[pollutant].dropna()

    if observed_train.empty:
        raise ValueError(f"No training data for {pollutant}.")

    scaler = StandardScaler()
    scaler.fit(observed_train.to_numpy().reshape(-1, 1))

    x_train, _ = make_windows(train[pollutant], scaler)
    x_val, _ = make_windows(validation[pollutant], scaler)
    x_cal, _ = make_windows(calibration[pollutant], scaler)
    x_test, test_dates = make_windows(test[pollutant], scaler)

    model = build_autoencoder()

    # Autoencoder target = input
    history = model.fit(
        x_train,
        x_train,
        validation_data=(x_val, x_val),
        epochs=100,
        batch_size=32,
        shuffle=False,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss",
                patience=10,
                restore_best_weights=True,
            )
        ],
        verbose=1,
    )

    # Starting heuristic: 99th percentile of calibration errors
    cal_errors = reconstruction_error(model, x_cal)
    threshold = float(np.quantile(cal_errors, 0.99))

    test_errors = reconstruction_error(model, x_test)

    result = pd.DataFrame(
        {
            "value": test[pollutant].reindex(test_dates).to_numpy(),
            "window_mse": test_errors,
            "threshold": threshold,
            "anomaly_window": test_errors > threshold,
        },
        index=test_dates,
    )
    result.index.name = "window_end_date"

    models[pollutant] = model
    scalers[pollutant] = scaler
    thresholds[pollutant] = threshold
    results[pollutant] = result

    print(
        f"\n{pollutant}: "
        f"{result['anomaly_window'].sum()} / {len(result)} "
        "test windows flagged"
    )

    # Plot reconstruction error, aligned to each window's end date
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(result.index, result["window_mse"], label="Window error")
    ax.axhline(
        threshold, color="red", linestyle="--", label="Threshold"
    )

    flagged = result["anomaly_window"]
    ax.scatter(
        result.index[flagged],
        result.loc[flagged, "window_mse"],
        color="red",
        s=20,
        label="Flagged window",
    )

    ax.set_title(f"{pollutant.upper()}: CNN autoencoder")
    ax.set_ylabel("MSE in standardized units")
    ax.legend()
    plt.tight_layout()
    plt.show()

# Inspect flagged windows:
print(results["pm25"].query("anomaly_window").head())
