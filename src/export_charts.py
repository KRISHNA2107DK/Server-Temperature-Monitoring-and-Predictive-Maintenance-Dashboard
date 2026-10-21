"""Save every dashboard chart to results/charts/ as interactive HTML and as a static PNG.
Run after pipeline.py:  python src/export_charts.py
PNG export uses kaleido, which drives a local Chrome/Edge browser (Edge is used on this machine).
"""
from pathlib import Path

import pandas as pd

from charts import (trend_chart, heatmap_chart, max_temp_bar_chart, distribution_box_chart, status_box_chart,
                    anomaly_scatter_chart, risk_level_chart, fan_temperature_chart)

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
CHARTS_DIR = PROJECT_DIR / "results" / "charts"
PNG_WIDTH = 1500


def save(figure, name):
    figure.write_html(CHARTS_DIR / f"{name}.html", include_plotlyjs="cdn")
    figure.write_image(CHARTS_DIR / "png" / f"{name}.png", width=PNG_WIDTH, scale=1)
    print("  saved", name)


def ten_minute_average(frame, group_column, columns):
    """Coarser resolution keeps per-server files small; 1-minute data stays in the dashboard."""
    return (frame.groupby([group_column, pd.Grouper(key="Timestamp", freq="10min")])
            .agg({c: ("max" if c == "temp_max" else "mean") for c in columns}).dropna().reset_index())


def main():
    (CHARTS_DIR / "png").mkdir(parents=True, exist_ok=True)
    minutes = pd.read_parquet(PROCESSED_DIR / "minute_temperatures.parquet")
    fans = pd.read_parquet(PROCESSED_DIR / "minute_fans.parquet")
    components = pd.read_csv(PROJECT_DIR / "results" / "tables" / "component_risk_summary.csv")

    save(max_temp_bar_chart(minutes), "01_hottest_components")
    save(heatmap_chart(minutes), "02_peak_heatmap")
    save(distribution_box_chart(minutes), "03_distribution_by_component")
    save(status_box_chart(minutes), "04_active_vs_idle")
    save(anomaly_scatter_chart(minutes[minutes["is_anomaly"]]), "05_anomalies")
    save(risk_level_chart(components), "06_risk_levels")
    for server, server_minutes in minutes.groupby("server"):
        safe_name = server.replace(".", "_")
        coarse = ten_minute_average(server_minutes, "component", ["temp_mean", "temp_max"])
        save(trend_chart(coarse, server, "10-minute"), f"trend_{safe_name}")
        coarse_fans = ten_minute_average(fans[fans["server"] == server], "fan", ["rpm"])
        save(fan_temperature_chart(coarse_fans, coarse, server, "10-minute"), f"cooling_{safe_name}")
    print("Charts written to", CHARTS_DIR)


if __name__ == "__main__":
    main()
