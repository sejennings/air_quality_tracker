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
