"""Render the real Streamlit app against fake artifact storage, without credentials."""
import json
import os
from datetime import datetime, timezone
from io import BytesIO
import unittest
import sys
sys.path.insert(0, '/app')
from evaluation import evaluate
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest


class DashboardTest(unittest.TestCase):
    def test_score_and_training_views_render(self):
        frame = pd.DataFrame({'date': pd.to_datetime(['2026-10-01']), 'pm25': [8.], 'ozone_8hr_max': [30.], 'reconstruction_error': [.4], 'pm25_reconstruction_error': [.2], 'ozone_reconstruction_error': [.2], 'anomaly': [False], 'model_version': ['test-run']})
        buffer = BytesIO()
        frame['pm25_reconstructed'] = 6.
        frame['ozone_reconstructed'] = 27.
        frame['anomaly_threshold'] = 1.
        frame.to_parquet(buffer, index=False)
        metadata = {'run_id': 'test-run', 'threshold': 1., 'seed': 42, 'git_commit': 'abc123', 'history': {'loss': [1., .5], 'val_loss': [1.2, .6]}, 'metrics': {'train': {'rows': 100, 'mse': .4, 'anomaly_rate': .05}, 'test': {'rows': 30, 'mse': .5, 'anomaly_rate': .1}}}
        payloads = {'active.json': json.dumps({'run_id': 'test-run'}).encode(), 'test-run/metadata.json': json.dumps(metadata).encode(), 'scores/live/2026-09-28.parquet': buffer.getvalue(), 'reports/2026-09-28.json': json.dumps({'week_start': '2026-09-28', 'week_end': '2026-10-04', 'status': 'complete', 'scored_days': 7, 'missing_dates': []}).encode()}
        historical = pd.concat([frame, frame], ignore_index=True)
        historical['date'] = pd.to_datetime(['2025-01-01', '2025-01-02'])
        historical['anomaly'] = [True, False]
        historical['reconstruction_error'] = [1.2, .4]
        historical_buffer = BytesIO()
        historical.to_parquet(historical_buffer, index=False)
        payloads['scores/historical/2025-test.parquet'] = historical_buffer.getvalue()
        lstm_meta = {**metadata, 'run_id': 'lstm-run', 'model_type': 'lstm', 'lookback': 14, 'pollutant_thresholds': [1., 1.]}
        payloads['lstm/active.json'] = json.dumps({'run_id': 'lstm-run'}).encode()
        payloads['lstm/lstm-run/metadata.json'] = json.dumps(lstm_meta).encode()
        lstm_frame = historical.copy()
        lstm_frame['model_version'] = 'lstm-run'
        lstm_frame['model_type'] = 'lstm'
        lstm_frame['pm25_reconstructed'] = 5.
        lstm_buffer = BytesIO()
        lstm_frame.to_parquet(lstm_buffer, index=False)
        payloads['scores/lstm/historical/2025-test.parquet'] = lstm_buffer.getvalue()
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
            decisions = [table.value for table in app.dataframe if 'Model decision' in table.value.columns][-1]
            self.assertEqual(decisions['Model decision'].tolist(), ['Flagged'])
            self.assertEqual(decisions['Observed rule'].tolist(), ['Below concentration limits'])
            errors = next(table.value for table in app.dataframe if 'MAE' in table.value.columns)
            self.assertEqual(errors['MAE'].tolist(), [2., 3.])
            self.assertEqual(errors['RMSE'].tolist(), [2., 3.])
            self.assertTrue(any(metric.label == 'Accuracy' and metric.value == '100.0%' for metric in app.metric))
            app.checkbox[0].uncheck().run()
            self.assertEqual(len(app.exception), 0)
            decisions = [table.value for table in app.dataframe if 'Model decision' in table.value.columns][-1]
            self.assertEqual(decisions['Model decision'].tolist(), ['Flagged', 'Not flagged'])
            comparison = next(table.value for table in app.dataframe if 'Common days' in table.value.columns)
            self.assertEqual(comparison['Common days'].tolist(), [2, 2])
            app.sidebar.selectbox[0].select('LSTM autoencoder').run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(heading.value == 'LSTM autoencoder' for heading in app.subheader))
            errors = next(table.value for table in app.dataframe if 'MAE' in table.value.columns)
            self.assertEqual(errors['MAE'].tolist(), [3., 3.])
            self.assertTrue(any(metric.label == 'Days scored' and metric.value == '2' for metric in app.metric))

    def test_independent_rule_and_confusion_counts(self):
        frame = pd.DataFrame({'pm25': [35.5, 1., 36., 1.], 'ozone_8hr_max': [10., 71., 10., 10.], 'pm25_reconstructed': [36., 1., 1., 36.], 'ozone_reconstructed': [10., 10., 10., 10.], 'anomaly': [True, False, False, True]})
        result, counts = evaluate(frame, 35.5, 71., reconstructed=True)
        self.assertEqual(result['Observed exceedance'].tolist(), [True, True, True, False])
        self.assertEqual(result.Outcome.tolist(), ['Correctly flagged', 'Missed day', 'Missed day', 'False alarm'])
        self.assertEqual(counts['Accuracy'], .25)
        self.assertEqual(counts['Precision'], .5)
        self.assertAlmostEqual(counts['Recall'], 1/3)
        changed = frame.copy()
        changed['anomaly'] = ~changed.anomaly
        second, _ = evaluate(changed, 35.5, 71.)
        self.assertTrue(result['Observed exceedance'].equals(second['Observed exceedance']))
        _, no_events = evaluate(frame.iloc[[3]], 100., 100., reconstructed=True)
        self.assertIsNone(no_events['Recall'])
        self.assertIsNone(no_events['Precision'])


if __name__ == '__main__':
    unittest.main()
