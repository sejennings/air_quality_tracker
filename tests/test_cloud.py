from datetime import date, datetime, timezone
import unittest
from air_quality_tracker.live import previous_week, parse_daily


class WeekTests(unittest.TestCase):
    def test_monday_completed_week(self):
        self.assertEqual(previous_week(datetime(2026, 10, 5, 12, tzinfo=timezone.utc)), (date(2026, 9, 28), date(2026, 10, 5)))

    def test_utc_monday_still_sunday_in_new_york(self):
        self.assertEqual(previous_week(datetime(2026, 10, 5, 2, tzinfo=timezone.utc)), (date(2026, 9, 21), date(2026, 9, 28)))

    def test_dst_week_has_seven_calendar_days(self):
        start, end = previous_week(datetime(2026, 3, 9, 12, tzinfo=timezone.utc))
        self.assertEqual((end - start).days, 7)


class AirNowTests(unittest.TestCase):
    def line(self, site, parameter, unit, value):
        return f'10/04/26|{site}|Station|{parameter}|{unit}|{value}|8|Agency|0|0|36|-79|840{site}'

    def test_region_averaging_and_ozone_units(self):
        lines = [self.line('370630015', 'OZONE-8HR', 'PPM', .04), self.line('371830001', 'OZONE-8HR', 'PPB', 20), self.line('370630015', 'PM2.5-24hr', 'UG/M3', 4), self.line('371830001', 'PM2.5-24hr', 'UG/M3', 6), self.line('060410001', 'PM2.5-24hr', 'UG/M3', 500)]
        result = parse_daily('\n'.join(lines), date(2026, 10, 4))
        self.assertEqual(result['ozone_8hr_max'], 30)
        self.assertEqual(result['pm25'], 5)
        self.assertEqual(result['pm25_sites'], 2)

    def test_missing_pollutant_remains_missing(self):
        import math
        result = parse_daily(self.line('370630015', 'PM2.5-24hr', 'UG/M3', 4), date(2026, 10, 4))
        self.assertTrue(math.isnan(result['ozone_8hr_max']))

    def test_bad_units_rejected(self):
        with self.assertRaises(ValueError):
            parse_daily(self.line('370630015', 'OZONE-8HR', 'AQI', 50), date(2026, 10, 4))

    def test_wrong_date_rejected(self):
        with self.assertRaises(ValueError):
            parse_daily(self.line('370630015', 'OZONE-8HR', 'PPB', 50), date(2026, 10, 3))


class CloudRetentionTests(unittest.TestCase):
    def test_age_and_generation_based_delete(self):
        from datetime import timedelta
        from air_quality_tracker.cloud import expire
        from unittest.mock import Mock
        now = datetime.now(timezone.utc)
        recent, expired = Mock(), Mock()
        recent.time_created = now - timedelta(days=29)
        expired.time_created = now - timedelta(days=30)
        expired.generation = 123
        bucket = Mock()
        bucket.list_blobs.return_value = [recent, expired]
        self.assertEqual(expire(bucket, now), 1)
        recent.delete.assert_not_called()
        expired.delete.assert_called_once_with(if_generation_match=123)


class TwoModelWeeklyTests(unittest.TestCase):
    def test_sequence_context_and_separate_outputs(self):
        from datetime import timedelta
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import pandas as pd
        from air_quality_tracker.cloud import weekly
        start, end = date(2026, 9, 28), date(2026, 10, 5)
        def collect(first, last):
            return pd.DataFrame({'date': pd.date_range(first, last - timedelta(days=1)), 'pm25': 8., 'ozone_8hr_max': 30.})
        def score(args):
            frame = pd.read_parquet(args.input)
            if getattr(args, 'score_start', None):
                self.assertEqual(len(frame), 20)
                frame = frame[frame.date >= pd.Timestamp(args.score_start)]
            output = args.operational / 'scores'
            output.mkdir(parents=True)
            frame.to_parquet(output / 'result.parquet')
        models, operational = Mock(), Mock()
        models.blob.return_value.exists.return_value = True
        with TemporaryDirectory() as tmp, patch('air_quality_tracker.cloud.previous_week', return_value=(start, end)), patch('air_quality_tracker.cloud.collect_week', side_effect=collect) as collected, patch('air_quality_tracker.cloud.download_model', return_value='model-run') as downloaded, patch('air_quality_tracker.cli.score', side_effect=score), patch('air_quality_tracker.cloud.write_json') as report:
            weekly(SimpleNamespace(), models, operational, Path(tmp))
            self.assertEqual(collected.call_args_list[1].args, (start - timedelta(days=13), start))
            self.assertEqual(downloaded.call_args_list[1].args[2], 'lstm')
            names = [call.args[0] for call in operational.blob.call_args_list]
            self.assertIn('scores/live/2026-09-28.parquet', names)
            self.assertIn('scores/lstm/live/2026-09-28.parquet', names)
            self.assertEqual(report.call_args.args[1]['lstm_scored_days'], 7)

    def test_missing_lstm_windows_does_not_discard_dense_scores(self):
        from datetime import timedelta
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import pandas as pd
        from air_quality_tracker.cloud import weekly
        start, end = date(2026, 9, 28), date(2026, 10, 5)
        def collect(first, last):
            return pd.DataFrame({'date': pd.date_range(first, last - timedelta(days=1)), 'pm25': 8., 'ozone_8hr_max': 30.})
        def score(args):
            if getattr(args, 'score_start', None):
                raise ValueError('No complete 14-day windows to score; missing days are never filled')
            output = args.operational / 'scores'
            output.mkdir(parents=True)
            collect(start, end).to_parquet(output / 'result.parquet')
        models, operational = Mock(), Mock()
        models.blob.return_value.exists.return_value = True
        with TemporaryDirectory() as tmp, patch('air_quality_tracker.cloud.previous_week', return_value=(start, end)), patch('air_quality_tracker.cloud.collect_week', side_effect=collect), patch('air_quality_tracker.cloud.download_model', return_value='model-run'), patch('air_quality_tracker.cli.score', side_effect=score), patch('air_quality_tracker.cloud.write_json') as report:
            weekly(SimpleNamespace(), models, operational, Path(tmp))
            self.assertEqual(report.call_args.args[1]['scored_days'], 7)
            self.assertEqual(report.call_args.args[1]['lstm_scored_days'], 0)
