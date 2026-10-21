# SPEC — Server Temperature Monitoring & Predictive Maintenance Dashboard

## 1. Problem in plain language
Lab servers log temperatures for each hardware component (SDR FPGA/RFIC boards, CPU, motherboard sensors) every ~10 s.
Any component above **85 °C** is a risk of hardware failure and downtime. Lab engineers / admins need one
interactive dashboard that shows which components overheat, how temperatures trend, where readings behave
abnormally, and which components are likely to fail soon, so they can act before downtime.

**Users:** lab engineers, system administrators, maintenance staff.

## 2. Input data (actual, inspected)
- `Tempreture Data.zip` → `30th_April/<ip>_info/heat-monitor-logs/heat-monitor_<date>.csv` (14 servers, ~66 k CSV files; ~65.8 k are header-only and contain no readings).
- One schema in every CSV: `Timestamp, STATUS, SDR0..7-FPGA(°C), SDR0..7-RFIC(°C), CPU-TEMP, CPUTIN, AUXTIN0..3, SYSTIN (°C), FAN-1..7 (rpm)`.
- `-` = sensor not present → treated as missing. Encoding is latin-1 (degree sign).
- `system_ip_info.txt` / `error_log.txt` are hardware descriptions — not used (out of scope).

## 3. Workflow (example)
1. `python src/pipeline.py` → reads zip, writes `data/processed/minute_temperatures.parquet` + `results/tables/*.csv`.
2. `python src/export_charts.py` → writes `results/charts/*.html`.
3. `streamlit run src/dashboard.py` → browser at http://localhost:8501.
4. User picks servers/components/dates → sees KPIs, charts, anomaly list, risk table.

Example: input row `2025-04-27 00:00:13, active, SDR0-FPGA=56, …` → output: in trend chart for server
`172.27.186.134`, component `SDR0-FPGA` at 56 °C, status NORMAL. A reading of 87 °C appears as a red ✕ above
the dashed 85 °C line, is counted in "Minutes above 85 °C", appears in `critical_breach_events.csv`, and the
component is HIGH/CRITICAL in the risk table.

## 4. Mandatory requirements (from problem statement)
| ID | Requirement | Source phrase |
|----|-------------|---------------|
| M1 | Ingest temperature data of multiple servers and their components | "readings collected from multiple servers… each component" |
| M2 | Apply 85 °C critical threshold to every component | "critical temperature threshold… 85 °C" |
| M3 | Interactive dashboard | "interactive dashboard" |
| M4 | Multiple graphical formats (≥ 3 chart types) | "multiple graphical formats" |
| M5 | Identify overheating components | "identify overheating components" |
| M6 | Monitor temperature trends over time | "monitor temperature trends" |
| M7 | Detect abnormal patterns | "detect abnormal patterns" |
| M8 | Support proactive maintenance (flag components likely to fail) | "proactively address potential hardware failures" / "Predictive Maintenance" |

## 5. Acceptance criteria
- **M1:** pipeline log prints number of servers (> 1) and readings; `server_summary.csv` has one row per server with data.
- **M2:** every chart showing temperature draws a dashed 85 °C line; counts use `temp > 85`.
- **M3:** the filter bar (servers, components, server status, date range) changes all KPIs and charts; a navigation bar at the top switches pages.
- **M4:** dashboard shows line, bar, heatmap, box and scatter charts, plus a stacked temperature/fan chart.
- **M5:** Overview tab lists the number of server-component pairs > 85 °C; bar chart colours them red; `critical_breach_events.csv` lists each event (start, end, duration, peak).
- **M6:** Trends tab shows a time-series line per component for a chosen server, > 85 °C points marked.
- **M7:** Anomalies tab shows minutes where |z| > 4 vs. the previous hour's rolling mean/std; `anomalies.csv` saved.
- **M8:** Predictive tab shows risk level per component with 3-day linear trend (°C/day) and projected days-to-85 °C; `component_risk_summary.csv` saved.

## 6. Defaults / assumptions (labelled)
- A1: Warning band 80–85 °C (not in brief; visual aid only).
- A2: Readings resampled to 1-minute mean **and max** (max preserves short spikes) for speed.
- A3: Values outside −20…150 °C are sensor glitches and excluded.
- A4: Anomaly = rolling z-score > 4 over previous 60 minutes (std floor 0.5 °C).
- A5: Risk rules — CRITICAL: last reading > 85 or ≥ 1 % of readings > 85; HIGH: any reading > 85 or trend reaches 85 within 7 days; WARNING: peak ≥ 80 or any anomaly; else NORMAL.
- A6: Fan RPM columns are not temperatures and are excluded from the analysis.
- A7: "Predictive" = transparent linear-trend projection, not an ML model (no labelled failure data exists).

## 7. Out of scope
Live streaming ingestion, alerts by email/SMS, user accounts, ML failure models, cloud deployment, hardware-info parsing.

## 8. Optional enhancements — all 5 implemented after user approval (see README)
1. Fan-RPM vs. temperature view (fan failure as an overheating cause).
2. Filter by `STATUS` (active/idle) to compare load vs. idle temperatures.
3. CSV download buttons in the dashboard.
4. Static PNG export of charts (needs `kaleido`).
5. Unit tests for pipeline functions with a small fixture CSV.

## 9. Risks
- Data volume (~200 MB CSV) → mitigated by 1-minute resampling + parquet cache.
- Very uneven data per server (one server has a single file) → trend may be NaN where < 30 minutes in last 3 days.
- Threshold semantics: "exceeding" interpreted as strictly `> 85`.
