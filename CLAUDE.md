# CLAUDE.md — standing instructions

Project: Server temperature monitoring & predictive maintenance dashboard (see SPEC.md, PLAN.md).
Run: `python src/pipeline.py` → `python src/export_charts.py` → `streamlit run src/dashboard.py`.

- Follow SPEC.md; flag conflicts before changing agreed scope, then proceed with a stated decision.
- Prefer readable, straightforward code and descriptive names.
- Keep modules focused (pipeline = data, charts = figures, dashboard = UI); avoid unnecessary abstractions.
- Explain important design decisions in plain language (comments / SPEC assumptions).
- Use real implementations for required functionality; the dataset is the real zip, never synthetic.
- Clearly label sample data, mocks, simulations, and external dependencies.
- Never fabricate execution results, test results, or model metrics.
- Run relevant checks after meaningful changes (re-run pipeline, start dashboard).
- Report what was verified and what remains unverified.
- Never weaken a requirement or test just to make the project pass.
- Keep secrets out of source code and version control (none are needed).
- Ask before paid resources, public deployment, or destructive operations.
- Keep setup instructions (README.md) and progress documentation accurate.
- 85 °C critical threshold is fixed by the brief; constants live in `src/pipeline.py` and `src/charts.py`.
