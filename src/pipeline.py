"""Load the raw heat-monitor CSVs straight from the zip, clean them, and compute
threshold breaches, anomalies and a per-component risk ranking.

Run:  python src/pipeline.py
Writes processed data to data/processed/ and all result tables + charts to results/.
"""
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
ZIP_PATH = PROJECT_DIR / "Tempreture Data.zip"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
RESULTS_DIR = PROJECT_DIR / "results"

CRITICAL_TEMP_C = 85.0          # from the problem statement
WARNING_TEMP_C = 80.0           # assumption: early-warning band 5 °C below critical
RESAMPLE_INTERVAL = "1min"      # raw samples are ~10 s apart; 1 min keeps the dashboard fast
ANOMALY_WINDOW = 60             # rolling window in 1-min samples (= 1 hour)
ANOMALY_Z = 4.0                 # |value - rolling mean| > 4 rolling std devs => anomaly
TREND_DAYS = 3                  # trend is fitted on each component's last 3 days of data
MIN_TREND_SPAN_DAYS = 1.0       # ...and only if that data covers at least 1 day


def server_ip_from_path(member_name):
    """'30th_April/172_27_186_13_info/heat-monitor-logs/x.csv' -> '172.27.186.13'"""
    folder = member_name.split("/")[1]
    return folder.replace("_info", "").replace("_", ".")


def clean_column_name(raw_name):
    """'SDR0-FPGA(Â°C)' -> 'SDR0-FPGA', 'FAN-1(rpm)' -> 'FAN-1'"""
    return re.sub(r"\(.*\)$", "", raw_name).strip()


def load_raw_readings(zip_path=ZIP_PATH):
    """Read every non-empty CSV in the zip into one wide DataFrame (one row per sample)."""
    frames = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if not member.filename.endswith(".csv") or member.file_size < 500:
                continue  # header-only files (424 bytes) contain no readings
            raw_bytes = archive.read(member)
            frame = pd.read_csv(io.BytesIO(raw_bytes), encoding="latin-1", na_values=["-"])
            if frame.empty:
                continue
            frame.columns = [clean_column_name(c) for c in frame.columns]
            frame.insert(0, "server", server_ip_from_path(member.filename))
            frames.append(frame)
    readings = pd.concat(frames, ignore_index=True)
    readings["Timestamp"] = pd.to_datetime(readings["Timestamp"], errors="coerce")
    readings = readings.dropna(subset=["Timestamp"])
    readings = readings.drop_duplicates(subset=["server", "Timestamp"])
    return readings.sort_values(["server", "Timestamp"]).reset_index(drop=True)


def temperature_columns(readings):
    return [c for c in readings.columns
            if c not in ("server", "Timestamp", "STATUS") and not c.startswith("FAN")]


def fan_columns(readings):
    return [c for c in readings.columns if c.startswith("FAN")]


def minute_status(readings):
    """Server workload STATUS (active/idle) per minute: the last status logged in that minute."""
    return (readings.groupby(["server", pd.Grouper(key="Timestamp", freq=RESAMPLE_INTERVAL)])["STATUS"]
            .last().reset_index().rename(columns={"STATUS": "status"}))


def resample_fans(readings):
    """Fan speeds (rpm) per server, fan and minute. 0 rpm = fan stopped or not connected."""
    fans = readings.melt(id_vars=["server", "Timestamp"], value_vars=fan_columns(readings),
                         var_name="fan", value_name="rpm")
    fans["rpm"] = pd.to_numeric(fans["rpm"], errors="coerce")
    fans = fans.dropna(subset=["rpm"])
    return (fans.groupby(["server", "fan", pd.Grouper(key="Timestamp", freq=RESAMPLE_INTERVAL)])["rpm"]
            .mean().reset_index())


def to_long_format(readings):
    """Wide -> long: one row per (server, timestamp, component, temperature). Drops '-' (absent) sensors."""
    long_frame = readings.melt(
        id_vars=["server", "Timestamp", "STATUS"],
        value_vars=temperature_columns(readings),
        var_name="component", value_name="temp_c",
    )
    long_frame["temp_c"] = pd.to_numeric(long_frame["temp_c"], errors="coerce")
    long_frame = long_frame.dropna(subset=["temp_c"])
    # Physically implausible values (sensor glitches) are excluded, not clipped.
    long_frame = long_frame[(long_frame["temp_c"] > -20) & (long_frame["temp_c"] < 150)]
    return long_frame.reset_index(drop=True)


def resample_per_minute(long_frame):
    """Per server+component 1-minute mean and max. Max is kept so short spikes over 85 °C are not hidden."""
    grouped = (long_frame.set_index("Timestamp")
               .groupby(["server", "component"])["temp_c"]
               .resample(RESAMPLE_INTERVAL)
               .agg(["mean", "max"])
               .dropna()
               .reset_index()
               .rename(columns={"mean": "temp_mean", "max": "temp_max"}))
    return grouped


def detect_anomalies(minute_frame):
    """Flag minutes where the mean temperature deviates strongly from that component's previous hour."""
    scored = minute_frame.sort_values(["server", "component", "Timestamp"]).reset_index(drop=True)
    by_component = scored.groupby(["server", "component"])["temp_mean"]
    previous = by_component.shift(1)
    rolling = previous.groupby([scored["server"], scored["component"]]).rolling(ANOMALY_WINDOW, min_periods=15)
    rolling_mean = rolling.mean().reset_index(level=[0, 1], drop=True)
    rolling_std = rolling.std().reset_index(level=[0, 1], drop=True).clip(lower=0.5)  # avoid ~0 std on flat sensors
    scored["z_score"] = (scored["temp_mean"] - rolling_mean) / rolling_std
    scored["is_anomaly"] = scored["z_score"].abs() > ANOMALY_Z
    return scored


def fit_trend(group):
    """Least-squares slope (°C/day) on the component's last TREND_DAYS of data, and days until 85 °C."""
    end = group["Timestamp"].max()
    recent = group[group["Timestamp"] >= end - pd.Timedelta(days=TREND_DAYS)]
    covered_days = (recent["Timestamp"].max() - recent["Timestamp"].min()) / pd.Timedelta(days=1)
    if len(recent) < 30 or covered_days < MIN_TREND_SPAN_DAYS:
        # Too little history to project days ahead (e.g. 1 hour of warm-up would give a huge fake slope).
        already_critical = len(recent) > 0 and recent["temp_mean"].tail(30).mean() >= CRITICAL_TEMP_C
        return pd.Series({"trend_c_per_day": float("nan"),
                          "days_to_critical": 0.0 if already_critical else float("nan")})
    days = (recent["Timestamp"] - recent["Timestamp"].min()).dt.total_seconds() / 86400
    temps = recent["temp_mean"]
    slope = ((days - days.mean()) * (temps - temps.mean())).sum() / ((days - days.mean()) ** 2).sum()
    current = temps.tail(30).mean()
    if current >= CRITICAL_TEMP_C:
        days_left = 0.0
    elif slope > 0.01:
        days_left = (CRITICAL_TEMP_C - current) / slope
    else:
        days_left = float("nan")  # flat or cooling: no projected breach
    return pd.Series({"trend_c_per_day": slope, "days_to_critical": days_left})


def build_component_summary(long_frame, scored_minutes):
    stats = long_frame.groupby(["server", "component"]).agg(
        readings=("temp_c", "size"),
        first_seen=("Timestamp", "min"),
        last_seen=("Timestamp", "max"),
        mean_temp_c=("temp_c", "mean"),
        max_temp_c=("temp_c", "max"),
        readings_above_85=("temp_c", lambda s: int((s > CRITICAL_TEMP_C).sum())),
        readings_80_to_85=("temp_c", lambda s: int(((s >= WARNING_TEMP_C) & (s <= CRITICAL_TEMP_C)).sum())),
    )
    stats["pct_time_above_85"] = 100 * stats["readings_above_85"] / stats["readings"]
    stats["anomaly_minutes"] = scored_minutes.groupby(["server", "component"])["is_anomaly"].sum()
    trends = scored_minutes.groupby(["server", "component"]).apply(fit_trend)
    stats = stats.join(trends)
    stats["last_temp_c"] = scored_minutes.groupby(["server", "component"])["temp_mean"].last()
    stats["risk_level"] = stats.apply(classify_risk, axis=1)
    order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "NORMAL": 3}
    stats = stats.reset_index()
    stats["_order"] = stats["risk_level"].map(order)
    stats = stats.sort_values(["_order", "max_temp_c"], ascending=[True, False]).drop(columns="_order")
    return stats.round(3)


def classify_risk(row):
    """Plain rules, in priority order (see SPEC.md)."""
    if row["last_temp_c"] > CRITICAL_TEMP_C or row["pct_time_above_85"] >= 1.0:
        return "CRITICAL"
    if row["readings_above_85"] > 0 or (pd.notna(row["days_to_critical"]) and row["days_to_critical"] <= 7):
        return "HIGH"
    if row["max_temp_c"] >= WARNING_TEMP_C or row["anomaly_minutes"] > 0:
        return "WARNING"
    return "NORMAL"


def build_breach_events(long_frame):
    """Group consecutive >85 °C readings per component into events (gap > 5 min starts a new event)."""
    hot = long_frame[long_frame["temp_c"] > CRITICAL_TEMP_C].sort_values(["server", "component", "Timestamp"])
    if hot.empty:
        return pd.DataFrame(columns=["server", "component", "start", "end", "duration_min", "peak_temp_c", "readings"])
    new_event = (hot.groupby(["server", "component"])["Timestamp"].diff() > pd.Timedelta(minutes=5)).fillna(True)
    hot = hot.assign(event_id=new_event.cumsum())
    events = hot.groupby(["server", "component", "event_id"]).agg(
        start=("Timestamp", "min"), end=("Timestamp", "max"),
        peak_temp_c=("temp_c", "max"), readings=("temp_c", "size")).reset_index()
    events["duration_min"] = (events["end"] - events["start"]).dt.total_seconds() / 60
    return events.drop(columns="event_id").sort_values("peak_temp_c", ascending=False).round(2)


def build_server_summary(component_summary):
    return component_summary.groupby("server").agg(
        components=("component", "size"),
        max_temp_c=("max_temp_c", "max"),
        hottest_component=("max_temp_c", lambda s: component_summary.loc[s.idxmax(), "component"]),
        readings_above_85=("readings_above_85", "sum"),
        anomaly_minutes=("anomaly_minutes", "sum"),
        critical_components=("risk_level", lambda s: int((s == "CRITICAL").sum())),
        high_risk_components=("risk_level", lambda s: int((s == "HIGH").sum())),
        first_seen=("first_seen", "min"), last_seen=("last_seen", "max"),
    ).reset_index().sort_values("max_temp_c", ascending=False)


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "tables").mkdir(parents=True, exist_ok=True)

    print("Loading CSVs from", ZIP_PATH.name)
    readings = load_raw_readings()
    print(f"  {len(readings):,} raw samples from {readings['server'].nunique()} servers")
    long_frame = to_long_format(readings)
    print(f"  {len(long_frame):,} valid component readings, {long_frame['component'].nunique()} component types")

    minutes = resample_per_minute(long_frame)
    scored = detect_anomalies(minutes)
    scored = scored.merge(minute_status(readings), on=["server", "Timestamp"], how="left")
    scored["status"] = scored["status"].fillna("unknown")
    fans = resample_fans(readings)
    component_summary = build_component_summary(long_frame, scored)
    breach_events = build_breach_events(long_frame)
    server_summary = build_server_summary(component_summary)

    scored.to_parquet(PROCESSED_DIR / "minute_temperatures.parquet", index=False)
    fans.to_parquet(PROCESSED_DIR / "minute_fans.parquet", index=False)
    tables = RESULTS_DIR / "tables"
    component_summary.to_csv(tables / "component_risk_summary.csv", index=False)
    server_summary.to_csv(tables / "server_summary.csv", index=False)
    breach_events.to_csv(tables / "critical_breach_events.csv", index=False)
    scored[scored["is_anomaly"]].round(3).to_csv(tables / "anomalies.csv", index=False)

    print(f"  servers with any reading > {CRITICAL_TEMP_C:.0f} C: "
          f"{(server_summary['readings_above_85'] > 0).sum()} / {len(server_summary)}")
    print(f"  breach events: {len(breach_events)}, anomaly minutes: {int(scored['is_anomaly'].sum())}")
    print("  risk levels:", component_summary["risk_level"].value_counts().to_dict())
    print("Done. Outputs in", RESULTS_DIR)


if __name__ == "__main__":
    sys.exit(main())
