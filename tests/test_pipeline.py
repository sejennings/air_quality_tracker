import os
from pathlib import Path
import tempfile
import unittest

from air_quality_tracker.retention import cleanup


class RetentionTests(unittest.TestCase):
    def test_expire_only_operational_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000
            for name in ('scores', 'collected', 'logs', 'models', 'historical'):
                folder = root / name
                folder.mkdir()
                for age in (29, 30, 31):
                    file = folder / str(age)
                    file.write_text('data')
                    os.utime(file, (now - age * 86400, now - age * 86400))
            self.assertEqual(cleanup(root, now=now), 6)
            self.assertTrue((root / 'scores' / '29').exists())
            self.assertTrue((root / 'models' / '31').exists())
            self.assertTrue((root / 'historical' / '31').exists())

    def test_reject_longer_retention(self):
        with self.assertRaises(ValueError):
            cleanup(Path('unused'), days=31)


class PipelineTests(unittest.TestCase):
    def test_training_promotion_and_scoring(self):
        import pandas as pd
        from air_quality_tracker.cli import main
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'daily.parquet'
            dates = pd.date_range('2023-12-27', periods=12).append(pd.date_range('2025-01-01', periods=4))
            pd.DataFrame({'date': dates, 'pm25': range(1, 17), 'ozone_8hr_max': [0.03] * 16}).to_parquet(source)
            prefix = ['air-quality', '--models', str(root / 'models'), '--operational', str(root / 'operational')]
            with patch('sys.argv', prefix + ['train', '--input', str(source), '--epochs', '1']):
                main()
            bundle = next((root / 'models').iterdir())
            import json, joblib
            meta = json.loads((bundle / 'metadata.json').read_text())
            self.assertEqual({k: v['rows'] for k, v in meta['metrics'].items()}, {'train': 5, 'validation': 7, 'test': 4})
            self.assertAlmostEqual(joblib.load(bundle / 'scaler.joblib').mean_[0], 3.0)
            self.assertEqual(len(meta['history']['loss']), 1)
            self.assertFalse((root / 'models' / 'active.json').exists())
            with patch('sys.argv', prefix + ['promote', bundle.name]):
                main()
            with patch('sys.argv', prefix + ['score', '--input', str(source)]):
                main()
            result = pd.read_parquet(next((root / 'operational' / 'scores').iterdir()))
            self.assertEqual(len(result), 16)
            self.assertTrue(result.model_version.eq(bundle.name).all())




class InputValidationTests(unittest.TestCase):
    def load(self, frame):
        from air_quality_tracker.cli import inputs
        from unittest.mock import patch
        with patch('pandas.read_parquet', return_value=frame):
            return inputs(Path('fixture.parquet'))

    def test_missing_column_rejected(self):
        import pandas as pd
        with self.assertRaisesRegex(ValueError, 'Missing columns'):
            self.load(pd.DataFrame({'date': ['2025-01-01'], 'pm25': [1.0]}))

    def test_duplicate_date_rejected(self):
        import pandas as pd
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.load(pd.DataFrame({'date': ['2025-01-01'] * 2, 'pm25': [1., 2.], 'ozone_8hr_max': [0.03] * 2}))

    def test_infinity_rejected(self):
        import pandas as pd
        with self.assertRaisesRegex(ValueError, 'Infinite'):
            self.load(pd.DataFrame({'date': ['2025-01-01'], 'pm25': [float('inf')], 'ozone_8hr_max': [0.03]}))

    def test_sort_and_drop_incomplete_observations(self):
        import pandas as pd
        result = self.load(pd.DataFrame({'date': ['2025-01-03', '2025-01-01', '2025-01-02'], 'pm25': [3., 1., None], 'ozone_8hr_max': [0.03] * 3}))
        self.assertEqual(result.pm25.tolist(), [1., 3.])
        self.assertTrue(result.date.is_monotonic_increasing)
        self.assertTrue(((result.doy_sin ** 2 + result.doy_cos ** 2) - 1).abs().lt(1e-10).all())


class PromotionTests(unittest.TestCase):
    def test_incomplete_bundle_does_not_replace_active_model(self):
        import json
        from air_quality_tracker.cli import main
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / 'active.json'
            active.write_text(json.dumps({'run_id': 'original'}))
            (root / 'incomplete').mkdir()
            with patch('sys.argv', ['air-quality', '--models', str(root), 'promote', 'incomplete']):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    main()
            self.assertEqual(json.loads(active.read_text())['run_id'], 'original')


