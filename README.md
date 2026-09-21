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
