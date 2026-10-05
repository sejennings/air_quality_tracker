"""Render the real Streamlit app against fake artifact storage, without credentials."""
import json
import os
from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest


class DashboardTest(unittest.TestCase):
    def test_score_and_training_views_render(self):
        frame = pd.DataFrame({'date': pd.to_datetime(['2026-10-01']), 'pm25': [8.], 'ozone_8hr_max': [30.], 'reconstruction_error': [.4], 'pm25_reconstruction_error': [.2], 'ozone_reconstruction_error': [.2], 'anomaly': [False], 'model_version': ['test-run']})
        buffer = BytesIO()
        frame.to_parquet(buffer, index=False)
        metadata = {'run_id': 'test-run', 'threshold': 1., 'seed': 42, 'git_commit': 'abc123', 'history': {'loss': [1., .5], 'val_loss': [1.2, .6]}, 'metrics': {'train': {'rows': 100, 'mse': .4, 'anomaly_rate': .05}, 'test': {'rows': 30, 'mse': .5, 'anomaly_rate': .1}}}
        payloads = {'active.json': json.dumps({'run_id': 'test-run'}).encode(), 'test-run/metadata.json': json.dumps(metadata).encode(), 'scores/live/2026-09-28.parquet': buffer.getvalue(), 'reports/2026-09-28.json': json.dumps({'week_start': '2026-09-28', 'week_end': '2026-10-04', 'status': 'complete', 'scored_days': 7, 'missing_dates': []}).encode()}
        class Blob:
            def __init__(self, name):
                self.name = name
                self.time_created = datetime.now(timezone.utc)
                self.size = len(payloads[name])
                self.generation = 1
            def download_as_text(self, **kwargs):
                return payloads[self.name].decode()
            def download_as_bytes(self, **kwargs):
                return payloads[self.name]
        class Bucket:
            def blob(self, name):
                return Blob(name)
            def list_blobs(self, prefix):
                return [Blob(name) for name in payloads if name.startswith(prefix)]
        class Client:
            def bucket(self, name):
                return Bucket()
        with patch.dict(os.environ, {'MODELS_BUCKET': 'test-models', 'OPERATIONAL_BUCKET': 'test-operational'}), patch('google.cloud.storage.Client', Client):
            app = AppTest.from_file('/app/app.py').run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.metric[0].value, '1')
            self.assertEqual(app.metric[1].value, '0')
            self.assertTrue(any('Dense autoencoder' in heading.value for heading in app.subheader))


if __name__ == '__main__':
    unittest.main()
