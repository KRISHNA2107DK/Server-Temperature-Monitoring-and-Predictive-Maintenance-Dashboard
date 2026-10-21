"""Unit tests for src/pipeline.py.  Run:  python -m pytest -q

The CSV used here is a SMALL HAND-WRITTEN TEST FIXTURE (not real lab data) in the same format as
the heat-monitor logs, built so the expected results are known exactly.
"""
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pipeline  # noqa: E402

HEADER = ("Timestamp,STATUS,SDR0-FPGA(°C),CPU-TEMP(°C),FAN-1(rpm)\n")


def fixture_rows():
    """20 minutes at 10 s intervals: SDR0-FPGA at 60 °C, with 87 °C between minute 5 and 6; CPU sensor absent."""
    rows = []
    start = pd.Timestamp("2025-04-01 00:00:00")
    for i in range(120):
        ts = start + pd.Timedelta(seconds=10 * i)
        fpga = 87 if 30 <= i < 36 else 60
        rows.append(f"{ts:%Y-%m-%d %H:%M:%S},{'active' if i < 60 else 'idle'},{fpga},-,{0 if i < 6 else 2000}\n")
    return "".join(rows)


@pytest.fixture
def fixture_zip(tmp_path):
    zip_path = tmp_path / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("30th_April/10_0_0_1_info/heat-monitor-logs/a.csv",
                         (HEADER + fixture_rows()).encode("latin-1"))
        archive.writestr("30th_April/10_0_0_1_info/heat-monitor-logs/empty.csv", HEADER.encode("latin-1"))
        archive.writestr("30th_April/10_0_0_1_info/system_ip_info.txt", "not a csv")
    return zip_path


def test_name_helpers():
    assert pipeline.server_ip_from_path("30th_April/172_27_186_13_info/heat-monitor-logs/x.csv") == "172.27.186.13"
    assert pipeline.clean_column_name("SDR0-FPGA(Â°C)") == "SDR0-FPGA"
    assert pipeline.clean_column_name("FAN-1(rpm)") == "FAN-1"


def test_load_skips_header_only_files_and_parses_dash_as_missing(fixture_zip):
    readings = pipeline.load_raw_readings(fixture_zip)
    assert len(readings) == 120
    assert set(readings["server"]) == {"10.0.0.1"}
    assert readings["CPU-TEMP"].isna().all()


def test_long_format_keeps_only_present_sensors(fixture_zip):
    long_frame = pipeline.to_long_format(pipeline.load_raw_readings(fixture_zip))
    assert set(long_frame["component"]) == {"SDR0-FPGA"}  # CPU '-' dropped, FAN excluded
    assert len(long_frame) == 120


def test_breach_events_group_consecutive_readings(fixture_zip):
    long_frame = pipeline.to_long_format(pipeline.load_raw_readings(fixture_zip))
    events = pipeline.build_breach_events(long_frame)
    assert len(events) == 1
    assert events.iloc[0]["readings"] == 6
    assert events.iloc[0]["peak_temp_c"] == 87
    assert events.iloc[0]["duration_min"] == pytest.approx(50 / 60, abs=0.01)


def test_threshold_is_strictly_above_85():
    frame = pd.DataFrame({"server": "s", "component": "c", "STATUS": "active",
                          "Timestamp": pd.date_range("2025-01-01", periods=3, freq="10s"),
                          "temp_c": [85.0, 85.0, 85.0]})
    assert pipeline.build_breach_events(frame).empty


def test_minute_max_preserves_spikes(fixture_zip):
    minutes = pipeline.resample_per_minute(pipeline.to_long_format(pipeline.load_raw_readings(fixture_zip)))
    minute_five = minutes[minutes["Timestamp"] == pd.Timestamp("2025-04-01 00:05:00")].iloc[0]
    assert minute_five["temp_max"] == 87


def test_fans_and_status(fixture_zip):
    readings = pipeline.load_raw_readings(fixture_zip)
    fans = pipeline.resample_fans(readings)
    assert fans.iloc[0]["rpm"] == 0
    status = pipeline.minute_status(readings)
    assert status.iloc[0]["status"] == "active" and status.iloc[-1]["status"] == "idle"


def test_trend_projects_days_to_critical():
    times = pd.date_range("2025-01-01", periods=3 * 24 * 60, freq="1min")
    warming = pd.DataFrame({"Timestamp": times, "temp_mean": 70 + 2.0 * (times - times[0]).total_seconds() / 86400})
    result = pipeline.fit_trend(warming)
    assert result["trend_c_per_day"] == pytest.approx(2.0, abs=0.01)
    assert result["days_to_critical"] == pytest.approx((85 - 76) / 2.0, abs=0.1)


@pytest.mark.parametrize("row, expected", [
    (dict(last_temp_c=90, pct_time_above_85=0.5, readings_above_85=5, days_to_critical=float("nan"),
          max_temp_c=95, anomaly_minutes=0), "CRITICAL"),
    (dict(last_temp_c=60, pct_time_above_85=0.1, readings_above_85=3, days_to_critical=float("nan"),
          max_temp_c=88, anomaly_minutes=0), "HIGH"),
    (dict(last_temp_c=60, pct_time_above_85=0, readings_above_85=0, days_to_critical=5,
          max_temp_c=70, anomaly_minutes=0), "HIGH"),
    (dict(last_temp_c=60, pct_time_above_85=0, readings_above_85=0, days_to_critical=float("nan"),
          max_temp_c=82, anomaly_minutes=0), "WARNING"),
    (dict(last_temp_c=60, pct_time_above_85=0, readings_above_85=0, days_to_critical=float("nan"),
          max_temp_c=70, anomaly_minutes=0), "NORMAL"),
])
def test_risk_rules(row, expected):
    assert pipeline.classify_risk(pd.Series(row)) == expected


def test_anomaly_flags_sudden_jump():
    times = pd.date_range("2025-01-01", periods=120, freq="1min")
    temps = [50.0 + (i % 2) * 0.2 for i in range(120)]
    temps[100] = 70.0
    frame = pd.DataFrame({"server": "s", "component": "c", "Timestamp": times,
                          "temp_mean": temps, "temp_max": temps})
    scored = pipeline.detect_anomalies(frame)
    assert scored["is_anomaly"].sum() == 1
    assert scored.loc[scored["is_anomaly"], "Timestamp"].iloc[0] == times[100]
