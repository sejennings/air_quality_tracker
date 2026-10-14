"""Train the project's CNN: install with pip install -e . first.
Run: python "notebooks/1D CNN Autoencoder.py" --epochs 100
The architecture and scoring live in air_quality_tracker.cnn.
This script creates a local candidate; it never promotes or deploys.
"""
import argparse
from pathlib import Path
from types import SimpleNamespace


def main():
    from air_quality_tracker.cnn import train
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=root / 'data/triangle_pm25_ozone_daily_2021_2025.parquet')
    parser.add_argument('--models', type=Path, default=root / 'runtime/cnn-candidates/cnn')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    train(SimpleNamespace(**vars(args), validation_start='2024-01-01', calibration_start='2024-07-01', test_start='2025-01-01'))


if __name__ == '__main__':
    main()
