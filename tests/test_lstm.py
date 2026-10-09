import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from air_quality_tracker.cli import FEATURES, inputs, main
from air_quality_tracker.lstm import windows


class SequenceTests(unittest.TestCase):
    def test_gaps_do_not_become_adjacent_days(self):
        dates = pd.date_range('2025-01-01', periods=30).delete(15)
        frame = pd.DataFrame({'date': dates, 'pm25': 8., 'ozone_8hr_max': 30.})
        with patch('pandas.read_parquet', return_value=frame):
            frame = inputs(Path('unused'))
        scaler = StandardScaler().fit(frame[FEATURES])
        sequences, ends = windows(frame, scaler)
        self.assertEqual(sequences.shape, (3, 14, 4))
        self.assertEqual(frame.iloc[ends].date.dt.day.tolist(), [14, 15, 30])

    def test_lstm_training_scoring_and_independent_promotion(self):
        import joblib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.date_range('2023-11-01', periods=30).append(pd.date_range('2024-01-01', periods=30)).append(pd.date_range('2025-01-01', periods=30))
            frame = pd.DataFrame({'date': dates, 'pm25': np.arange(90) + 1., 'ozone_8hr_max': 30 + np.sin(np.arange(90))})
            source = root / 'input.parquet'
            frame.to_parquet(source, index=False)
            models = root / 'models'
            models.mkdir()
            (models / 'active.json').write_text('{"run_id":"dense-original"}')
            prefix = ['air-quality', '--models', str(models), '--operational', str(root / 'operational'), '--model', 'lstm']
            with patch('sys.argv', prefix + ['train', '--input', str(source), '--epochs', '2']):
                main()
            bundle = next((models / 'lstm').iterdir())
            meta = json.loads((bundle / 'metadata.json').read_text())
            self.assertEqual([m['rows'] for m in meta['metrics'].values()], [17, 17, 17])
            self.assertAlmostEqual(joblib.load(bundle / 'scaler.joblib').mean_[0], 15.5)
            self.assertFalse((models / 'lstm' / 'active.json').exists())
            with patch('sys.argv', prefix + ['promote', bundle.name]):
                main()
            with patch('sys.argv', prefix + ['score', '--input', str(source), '--score-start', '2025-01-01']):
                main()
            self.assertEqual(json.loads((models / 'active.json').read_text())['run_id'], 'dense-original')
            scored = pd.read_parquet(next((root / 'operational' / 'scores').iterdir()))
            self.assertEqual(len(scored), 17)
            self.assertEqual(scored.date.min(), pd.Timestamp('2025-01-14'))
            ratios = np.sqrt(scored[['pm25_reconstruction_error', 'ozone_reconstruction_error']].to_numpy()) / meta['pollutant_thresholds']
            self.assertTrue(np.allclose(scored.reconstruction_error, ratios.max(axis=1)))
            self.assertTrue(scored.anomaly.eq(scored.reconstruction_error > 1).all())
            self.assertTrue(scored.anomaly.eq(scored.pm25_anomaly | scored.ozone_anomaly).all())
            # Re-evaluate validation to prove thresholds are validation-only, not test quantiles.
            with patch('sys.argv', prefix + ['score', '--input', str(source)]):
                main()
            all_scored = pd.concat([pd.read_parquet(p) for p in (root / 'operational' / 'scores').iterdir()]).drop_duplicates('date')
            val = all_scored[all_scored.date.dt.year == 2024]
            expected = np.quantile(np.sqrt(val[['pm25_reconstruction_error', 'ozone_reconstruction_error']].to_numpy()), .99, axis=0)
            self.assertTrue(np.allclose(meta['pollutant_thresholds'], expected, atol=1e-6))
