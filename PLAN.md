# PLAN

## Tech stack decision
| Option | Mandatory reqs | Explainability | Setup | Cost |
|---|---|---|---|---|
| **Python + pandas + Plotly + Streamlit (chosen)** | All | High — pure Python, ~400 lines | `pip install -r requirements.txt` | Free, local, no keys |
| Plotly Dash | All | Medium — callbacks add boilerplate | Same | Free |
| Power BI / Grafana | All | Low code but not reproducible from repo; Grafana needs a DB | Separate installs/accounts | Power BI Desktop free (Windows), Grafana needs server |

- **pandas** — read/clean/resample CSVs. **pyarrow** — fast parquet cache of processed data.
- **Plotly** — interactive charts (zoom/hover) reused in dashboard and HTML export.
- **Streamlit** — dashboard UI with filters; no frontend code. No database, no external services, no API keys.
- Hardware: any laptop; pipeline needs ~2–4 GB RAM.

## Milestones
| # | Milestone | Verification |
|---|---|---|
| 1 | Inspect data schema | Header identical across all files (verified) |
| 2 | `src/pipeline.py`: load → long format → 1-min resample → anomalies → risk → tables | Runs end-to-end; log saved to `results/pipeline_log.txt`; CSVs present |
| 3 | `src/charts.py` + `src/export_charts.py` | HTML files in `results/charts/` open in browser |
| 4 | `src/dashboard.py` (Streamlit) | App starts, HTTP 200 on localhost:8501, tabs render without exceptions |
| 5 | README + results packaging | Fresh-run commands reproduce outputs |
| 6 | Optional items from SPEC §8 (done) | Fan/status in pipeline, PNG export written, pytest 14 passed, all pages opened in browser |
| 7 | UI restructure (done) | Top navigation, filter bar, white chart cards with boxed legends, component guide |

## Status
See README.md "Verification status".
