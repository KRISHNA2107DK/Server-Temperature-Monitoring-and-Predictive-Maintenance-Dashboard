# Server Temperature Monitoring & Predictive Maintenance Dashboard

**Live dashboard:** https://server-temp-monitor.streamlit.app/
**Source code:** https://github.com/KRISHNA2107DK/Server-Temperature-Monitoring-and-Predictive-Maintenance-Dashboard
**Final report:** [`submission/Final_Report.pdf`](submission/Final_Report.pdf)

Author: Dharmapuri Srikrishna Ashrit · Reg. No. 235890216 · Manipal Institute of Technology, Bengaluru

An interactive dashboard over the real lab heat-monitor logs (`Tempreture Data.zip`, 14 servers). It applies the
**85 °C critical threshold** to every component, identifies overheating components, shows temperature trends,
detects abnormal patterns and ranks components by maintenance risk.

## Setup (Python 3.11)
```bash
pip install -r requirements.txt
```

## Run (reproduces every output from the zip)
```bash
python src/pipeline.py          # ~4 min: data/processed/ + results/tables/
python src/export_charts.py     # results/charts/ (HTML + PNG)
python -m pytest -q             # unit tests
streamlit run src/dashboard.py  # http://localhost:8501
```
PNG export uses `kaleido`, which needs Google Chrome or Microsoft Edge installed.

## Project layout
| Path | Purpose |
|---|---|
| `src/pipeline.py` | Reads the CSVs directly from the zip, cleans them, makes 1-minute summaries (mean + max), finds >85 °C breach events, detects anomalies, fits trends, assigns risk levels |
| `src/charts.py` | All Plotly chart designs (shared by the dashboard and the export script) |
| `src/dashboard.py` | Streamlit dashboard: top navigation (Overview · Temperature trends · Abnormal patterns · Predictive maintenance · Cooling & workload · Component guide), shared filter bar, CSV downloads |
| `src/export_charts.py` | Saves every chart as interactive HTML and static PNG |
| `tests/test_pipeline.py` | Unit tests on a small hand-written fixture CSV (test data, not real lab data) |
| `.streamlit/config.toml` | Light theme; charts are white cards on a grey background for contrast |
| `data/processed/` | Pre-processed data used by the dashboard (committed so the hosted app does not need to re-run the pipeline) |
| `results/tables/` | `server_summary.csv`, `component_risk_summary.csv`, `critical_breach_events.csv`, `anomalies.csv` |
| `results/charts/`, `results/charts/png/` | 34 interactive HTML charts and 34 PNG images |
| `results/*.txt` | Logs of the pipeline run, chart export and test run |
| `submission/` | Final report (PDF + HTML) and dashboard screenshots |
| `SPEC.md`, `PLAN.md`, `CLAUDE.md` | Requirements and acceptance criteria, implementation plan, working instructions |

## Method (plain language)
- **Overheating:** any reading strictly above 85 °C. Consecutive hot readings (gaps ≤ 5 min) form one breach event.
- **Abnormal pattern:** a 1-minute average more than 4 standard deviations away from that component's previous hour.
- **Prediction:** straight-line trend over the last 3 days (only if they cover ≥ 1 day) → °C/day and projected days until 85 °C.
- **Risk level:** CRITICAL / HIGH / WARNING / NORMAL from breaches, trend and anomalies (rules in SPEC.md and the report).

## Verification status (2026-10-21)
Python 3.11.9, pandas 3.0.2, plotly 7.1.0, streamlit 1.66.0, pyarrow 26.0.0, kaleido 1.5.0, pytest 9.1.1.
- Pipeline on the real data: 1,376,036 samples, 14 servers, 14,234,677 component readings, 17 sensor types;
  3/14 servers above 85 °C; 237 breach events; 18,590 anomalous minutes;
  risk levels CRITICAL 10 / HIGH 2 / WARNING 112 / NORMAL 55 (`results/pipeline_log.txt`).
- Unit tests: see `results/test_log.txt` (all passed).
- Chart export: 34 HTML + 34 PNG.
- Dashboard: all 6 pages opened locally with no errors; about 320 MB memory after visiting every page.

## Known limitations
- The prediction is a linear trend, not a trained failure model (the data has no failure records).
- 172.27.28.111 AUXTIN1 reads a constant 127 °C, which is probably a sensor fault; it is still flagged, not hidden.
- Some SDR sensors read exactly 0 °C (boards off); these are kept but left out of box plots.
- Server 172.27.186.50 has rows dated March 2023 (probably a wrong clock); kept as logged.
