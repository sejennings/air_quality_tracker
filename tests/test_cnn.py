import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from air_quality_tracker.cnn import windows
from air_quality_tracker.cli import main


class CNNTests(unittest.TestCase):
    def test_independent_pollutants_and_calendar_gaps(self):
        frame = pd.DataFrame({'date': pd.date_range('2025-01-01', periods=60).delete(30), 'pm25': 8., 'ozone_8hr_max': 30.})
        frame.loc[0, 'ozone_8hr_max'] = np.nan
        scaler = StandardScaler().fit([[1.], [2.]])
        pm, pm_ends = windows(frame, 'pm25', scaler)
        ozone, ozone_ends = windows(frame, 'ozone_8hr_max', scaler)
        self.assertEqual(pm.shape, (5, 28, 1))
        self.assertEqual(ozone.shape, (4, 28, 1))
        self.assertNotIn(27, ozone_ends)
        self.assertIn(27, pm_ends)

    def test_training_calibration_promotion_and_scoring(self):
        import joblib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.DatetimeIndex([])
            for start in ('2023-11-01', '2024-01-01', '2024-07-01', '2025-01-01'):
                dates = dates.append(pd.date_range(start, periods=32))
            frame = pd.DataFrame({'date': dates, 'pm25': np.arange(128) + 1., 'ozone_8hr_max': 30 + np.sin(np.arange(128))})
            frame.loc[0, 'ozone_8hr_max'] = np.nan
            source = root / 'daily.parquet'
            frame.to_parquet(source, index=False)
            models = root / 'models'
            models.mkdir()
            (models / 'active.json').write_text('{"run_id":"dense-original"}')
            prefix = ['air-quality', '--models', str(models), '--operational', str(root / 'op'), '--model', 'cnn']
            with patch('sys.argv', prefix + ['train', '--input', str(source), '--epochs', '2']):
                main()
            bundle = next((models / 'cnn').iterdir())
            meta = json.loads((bundle / 'metadata.json').read_text())
            self.assertEqual([m['rows'] for m in meta['metrics'].values()], [4, 5, 5, 5])
            scalers = joblib.load(bundle / 'scaler.joblib')
            self.assertAlmostEqual(scalers['pm25'].mean_[0], 16.5)
            self.assertFalse((models / 'cnn' / 'active.json').exists())
            with patch('sys.argv', prefix + ['promote', bundle.name]):
                main()
            with patch('sys.argv', prefix + ['score', '--input', str(source)]):
                main()
            result = pd.read_parquet(next((root / 'op' / 'scores').iterdir()))
            self.assertEqual(len(result), 19)
            self.assertTrue(result.anomaly.eq(result.pm25_anomaly | result.ozone_anomaly).all())
            self.assertTrue(result.anomaly.eq(result.reconstruction_error > 1).all())
            calibration = result[(result.date >= '2024-07-01') & (result.date < '2025-01-01')]
            for p in ('pm25', 'ozone'):
                self.assertAlmostEqual(meta['pollutant_thresholds'][p], float(np.quantile(calibration[f'{p}_reconstruction_error'], .99)), places=5)
            self.assertEqual(json.loads((models / 'active.json').read_text())['run_id'], 'dense-original')
            with patch('sys.argv', prefix + ['score', '--input', str(source), '--score-start', '2025-01-01']):
                main()
            results = [pd.read_parquet(p) for p in (root / 'op' / 'scores').iterdir()]
            self.assertEqual(sorted(map(len, results)), [5, 19])
