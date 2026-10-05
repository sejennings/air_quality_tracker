"""Public daily AirNow observations, matched to the historical regional inputs."""
from datetime import datetime, timedelta
from urllib.request import urlopen
from zoneinfo import ZoneInfo

COUNTIES = {"37183", "37063", "37135"}


def previous_week(now=None):
    today = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York")).date()
    end = today - timedelta(days=today.weekday())
    return end - timedelta(days=7), end  # exclusive end, safe across DST


def parse_daily(text, expected_date):
    import pandas as pd
    records = {}
    for line in text.splitlines():
        fields = line.split("|")
        if len(fields) < 13 or fields[1][:5] not in COUNTIES:
            continue
        parameter = fields[3].upper()
        if parameter not in ("PM2.5-24HR", "OZONE-8HR"):
            continue
        if datetime.strptime(fields[0], "%m/%d/%y").date() != expected_date:
            raise ValueError("AirNow file contains unexpected observation date")
        value = float(fields[5])
        if value < 0:
            continue
        if parameter == "OZONE-8HR":
            if fields[4].upper() == "PPM":
                value *= 1000
            elif fields[4].upper() != "PPB":
                raise ValueError("Unsupported ozone unit")
            feature = "ozone_8hr_max"
        else:
            if fields[4].upper() != "UG/M3":
                raise ValueError("Unsupported PM2.5 unit")
            feature = "pm25"
        key = (feature, fields[1])
        if key in records and records[key] != value:
            raise ValueError("Conflicting daily monitor observations")
        records[key] = value
    result = {"date": pd.Timestamp(expected_date), "input_source": "AirNow preliminary daily observations"}
    for feature in ("pm25", "ozone_8hr_max"):
        values = [v for (f, _), v in records.items() if f == feature]
        result[feature] = sum(values) / len(values) if values else float("nan")
        result[feature + "_sites"] = len(values)
    return result


def collect_week(start, end):
    import pandas as pd
    from urllib.error import HTTPError
    rows = []
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        url = f"https://files.airnowtech.org/airnow/{day:%Y}/{day:%Y%m%d}/daily_data_v2.dat"
        try:
            with urlopen(url, timeout=60) as reply:
                text = reply.read().decode("utf-8-sig")
        except HTTPError as error:
            if error.code == 404:
                rows.append({"date": pd.Timestamp(day), "pm25": float("nan"), "ozone_8hr_max": float("nan"), "pm25_sites": 0, "ozone_8hr_max_sites": 0, "input_source": "AirNow file unavailable"})
                continue
            raise
        rows.append(parse_daily(text, day))
    return pd.DataFrame(rows)
