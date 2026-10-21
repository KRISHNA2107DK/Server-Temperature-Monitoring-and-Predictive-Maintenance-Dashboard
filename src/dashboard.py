"""Interactive dashboard.  Run:  streamlit run src/dashboard.py
Requires `python src/pipeline.py` to have been run first.

Layout: title -> filter bar -> top navigation bar (one page per question the user asks) -> page content.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from charts import (CRITICAL_TEMP_C, WARNING_TEMP_C, COMPONENT_GUIDE, COMPONENT_ORDER, COMPONENT_COLORS,
                    RISK_COLORS, present_components, trend_chart, heatmap_chart, max_temp_bar_chart, distribution_box_chart,
                    status_box_chart, anomaly_scatter_chart, risk_level_chart, fan_temperature_chart)

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
TABLES_DIR = PROJECT_DIR / "results" / "tables"

st.set_page_config(page_title="Server Temperature Monitor", page_icon="🌡️", layout="wide",
                   initial_sidebar_state="collapsed")


@st.cache_data
def load_data():
    minutes = pd.read_parquet(PROCESSED_DIR / "minute_temperatures.parquet")
    fans = pd.read_parquet(PROCESSED_DIR / "minute_fans.parquet")
    components = pd.read_csv(TABLES_DIR / "component_risk_summary.csv", parse_dates=["first_seen", "last_seen"])
    servers = pd.read_csv(TABLES_DIR / "server_summary.csv")
    breaches = pd.read_csv(TABLES_DIR / "critical_breach_events.csv", parse_dates=["start", "end"])
    return minutes, fans, components, servers, breaches


def show_chart(figure):
    """Charts sit in a bordered card; theme=None keeps our high-contrast white chart styling."""
    with st.container(border=True):
        st.plotly_chart(figure, theme=None, width="stretch")


def download_button(frame, file_name, label):
    st.download_button(f"⬇ Download {label} (CSV)", frame.to_csv(index=False).encode("utf-8"),
                       file_name=file_name, mime="text/csv", key=f"dl_{file_name}")


if not (PROCESSED_DIR / "minute_fans.parquet").exists():
    st.error("Processed data not found. Run `python src/pipeline.py` first.")
    st.stop()

minutes, fans, components, servers, breaches = load_data()

# ---------------- Header + filter bar (applies to every page) ----------------
st.title("🌡️ Server Temperature Monitoring & Predictive Maintenance")
st.caption(f"Critical threshold **{CRITICAL_TEMP_C:.0f} °C** · warning band {WARNING_TEMP_C:.0f}–{CRITICAL_TEMP_C:.0f} °C "
           f"(assumption) · data = 1-minute mean/max of raw ~10 s readings from `Tempreture Data.zip`")

all_servers = sorted(minutes["server"].unique())
all_components = present_components(minutes)
min_day, max_day = minutes["Timestamp"].min().date(), minutes["Timestamp"].max().date()

with st.expander("🔎 Filters — servers, components, server status, dates", expanded=False):
    f1, f2 = st.columns(2)
    chosen_servers = f1.multiselect("Servers", all_servers, default=all_servers)
    chosen_components = f2.multiselect("Components", all_components, default=all_components)
    f3, f4 = st.columns(2)
    chosen_status = f3.multiselect("Server status", ["active", "idle", "unknown"],
                                   default=["active", "idle", "unknown"],
                                   help="'active' = server under workload, 'idle' = no workload (from the STATUS column)")
    date_range = f4.date_input("Date range", (min_day, max_day), min_value=min_day, max_value=max_day)

start_day, end_day = (date_range if isinstance(date_range, (tuple, list)) and len(date_range) == 2
                      else (min_day, max_day))
in_window = minutes["Timestamp"].between(pd.Timestamp(start_day), pd.Timestamp(end_day) + pd.Timedelta(days=1))
view = minutes[minutes["server"].isin(chosen_servers) & minutes["component"].isin(chosen_components)
               & minutes["status"].isin(chosen_status) & in_window]
comp_view = components[components["server"].isin(chosen_servers) & components["component"].isin(chosen_components)]

if view.empty:
    st.warning("No data for the selected filters.")
    st.stop()


# ---------------- Pages ----------------
def overview_page():
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Servers", view["server"].nunique(), border=True)
    k2.metric("Server-components monitored", view.groupby(["server", "component"]).ngroups, border=True)
    k3.metric("Peak temperature", f"{view['temp_max'].max():.1f} °C", border=True)
    k4.metric("Minutes above 85 °C", f"{int((view['temp_max'] > CRITICAL_TEMP_C).sum()):,}", border=True)
    k5.metric("Anomalous minutes", f"{int(view['is_anomaly'].sum()):,}", border=True)

    peaks = view.groupby(["server", "component"])["temp_max"].max()
    hot = peaks[peaks > CRITICAL_TEMP_C].sort_values(ascending=False)
    if hot.empty:
        st.success("No component exceeded 85 °C for the current filters.")
    else:
        names = ", ".join(f"**{s} · {c}** ({t:.0f} °C)" for (s, c), t in hot.items())
        st.error(f"🔥 {len(hot)} server-components exceeded 85 °C: {names}")

    show_chart(max_temp_bar_chart(view))
    show_chart(heatmap_chart(view))
    st.subheader("Server summary")
    server_table = servers[servers["server"].isin(chosen_servers)]
    st.dataframe(server_table, width="stretch", hide_index=True)
    download_button(server_table, "server_summary.csv", "server summary")


def trends_page():
    c1, c2 = st.columns([1, 3])
    trend_server = c1.selectbox("Server", sorted(view["server"].unique()))
    server_view = view[view["server"] == trend_server]
    available = present_components(server_view)
    trend_components = c2.multiselect("Components to plot", available, default=available)
    show_chart(trend_chart(server_view[server_view["component"].isin(trend_components)], trend_server))
    st.caption("Drag the slider under the chart to zoom into a time window · click a legend entry to hide it, "
               "double-click to show only that component.")
    show_chart(distribution_box_chart(view))


def anomalies_page():
    st.info("A minute is **anomalous** when its mean temperature is more than 4 standard deviations away from the "
            "same component's previous hour (rolling z-score). These are sudden jumps or drops, even below 85 °C.")
    anomalies = view[view["is_anomaly"]]
    show_chart(anomaly_scatter_chart(anomalies))
    left, right = st.columns(2)
    with left:
        st.subheader("Anomaly count per server-component")
        counts = (anomalies.groupby(["server", "component"]).size().reset_index(name="anomaly_minutes")
                  .sort_values("anomaly_minutes", ascending=False))
        st.dataframe(counts, width="stretch", hide_index=True, height=400)
        download_button(anomalies.round(3), "anomalies.csv", "anomalous minutes")
    with right:
        st.subheader("Critical breach events (> 85 °C)")
        events = breaches[breaches["server"].isin(chosen_servers) & breaches["component"].isin(chosen_components)]
        st.dataframe(events, width="stretch", hide_index=True, height=400)
        download_button(events, "critical_breach_events.csv", "breach events")


def risk_page():
    st.info("**CRITICAL** = last reading > 85 °C or ≥ 1 % of readings above 85 °C · "
            "**HIGH** = any reading above 85 °C, or the 3-day linear trend reaches 85 °C within 7 days · "
            "**WARNING** = peak ≥ 80 °C or any anomaly · **NORMAL** otherwise.")
    left, right = st.columns([1, 2])
    with left:
        show_chart(risk_level_chart(comp_view))
    with right:
        st.subheader("Act first on these")
        urgent = comp_view[comp_view["risk_level"].isin(["CRITICAL", "HIGH"])]
        for _, row in urgent.iterrows():
            eta = ("already above 85 °C" if row["days_to_critical"] == 0
                   else f"projected 85 °C in {row['days_to_critical']:.1f} days" if pd.notna(row["days_to_critical"])
                   else "no rising trend")
            st.markdown(f"- **{row['risk_level']}** · `{row['server']}` · **{row['component']}** "
                        f"({COMPONENT_GUIDE.get(row['component'], '')}) — peak {row['max_temp_c']:.0f} °C, {eta}")
    columns = ["risk_level", "server", "component", "last_temp_c", "max_temp_c", "mean_temp_c",
               "readings_above_85", "pct_time_above_85", "anomaly_minutes", "trend_c_per_day", "days_to_critical"]
    table = comp_view[columns]
    st.subheader("Full risk table")
    st.dataframe(table.style.map(lambda v: f"background-color: {RISK_COLORS.get(v, '')}; color: white; font-weight: bold"
                                 if v in RISK_COLORS else "", subset=["risk_level"]).format(precision=2),
                 width="stretch", hide_index=True, height=500)
    download_button(table, "component_risk_summary.csv", "risk table")


def cooling_page():
    st.info("Fan speeds next to temperatures. A fan at **0 rpm** while temperatures climb points to a cooling "
            "failure; the active-vs-idle chart shows how much workload heats each component.")
    fan_server = st.selectbox("Server", sorted(view["server"].unique()), key="fan_server")
    server_fans = fans[(fans["server"] == fan_server)
                       & fans["Timestamp"].between(pd.Timestamp(start_day), pd.Timestamp(end_day) + pd.Timedelta(days=1))]
    show_chart(fan_temperature_chart(server_fans, view[view["server"] == fan_server], fan_server))
    fan_table = (server_fans.groupby("fan")["rpm"]
                 .agg(mean_rpm="mean", min_rpm="min", max_rpm="max",
                      pct_minutes_stopped=lambda s: 100 * (s == 0).mean()).round(1).reset_index())
    st.subheader(f"Fan summary — {fan_server}")
    st.dataframe(fan_table, width="stretch", hide_index=True)
    show_chart(status_box_chart(view))


def guide_page():
    st.subheader("What each component sensor measures")
    present = set(all_components)
    guide = pd.DataFrame([{"component": name, "description": text,
                           "colour in charts": COMPONENT_COLORS[name], "in this dataset": name in present}
                          for name, text in COMPONENT_GUIDE.items()])
    st.dataframe(guide.style.map(lambda c: f"background-color: {c}; color: white", subset=["colour in charts"]),
                 width="stretch", hide_index=True, height=800)
    st.caption("SDR = software-defined radio board. CPUTIN/SYSTIN/AUXTIN are standard motherboard sensor-chip "
               "labels; the exact location of AUXTIN0–3 depends on the motherboard (assumption).")


navigation = st.navigation(
    [st.Page(overview_page, title="Overview", icon="📊", default=True),
     st.Page(trends_page, title="Temperature trends", icon="📈"),
     st.Page(anomalies_page, title="Abnormal patterns", icon="⚠️"),
     st.Page(risk_page, title="Predictive maintenance", icon="🛠️"),
     st.Page(cooling_page, title="Cooling & workload", icon="🌀"),
     st.Page(guide_page, title="Component guide", icon="📘")],
    position="top",
)
navigation.run()
