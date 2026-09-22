EDA
 ↓
Seasonality adjustment / feature engineering
 ↓
Dense AE
    Weather variables
           ↓
       32 neurons
           ↓
        8 neurons       ← compressed representation
           ↓
       32 neurons
           ↓
    Reconstructed weather variables
 ↓
LSTM AE
    Day 1 ┐
    Day 2 │
    Day 3 │
     ...  ├─ 14-day weather sequence → LSTM → reconstruct 14 days
    Day 14┘
 ↓
LSTM/GRU forecasting anomaly detector
    Past 14 days
         ↓
     LSTM / GRU
         ↓
    Tomorrow's weather
 ↓
1D CNN AE
    30-day weather sequence
            ↓
    Conv1D
            ↓
    Conv1D
            ↓
    latent representation
            ↓
    Conv1DTranspose
            ↓
    reconstructed sequence
 ↓
 Variational AE
     weather → latent representation → weather
                          x anomaly
                 • •
              • • • •
            • • • • • •
              • • •
                 •
                             x anomaly
 ↓
Examine specific dates flagged by each model

