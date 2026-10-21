"""Plotly chart builders shared by the dashboard and the static export script.

Every figure goes through style_figure(): white plot area, dark text, grid lines and a boxed,
titled legend, so charts stay readable on the light-grey dashboard background and in PNG exports.
Each component always gets the same colour in every chart (COMPONENT_COLORS).
"""
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CRITICAL_TEMP_C = 85.0
WARNING_TEMP_C = 80.0

RISK_COLORS = {"CRITICAL": "#C62828", "HIGH": "#EF6C00", "WARNING": "#F9A825", "NORMAL": "#2E7D32"}
STATUS_COLORS = {"Critical (>85 °C)": "#C62828", "Warning (80–85 °C)": "#F9A825", "Normal (<80 °C)": "#2E7D32"}

# What each sensor column measures. The SDR/CPU names follow the log headers; the
# CPUTIN/SYSTIN/AUXTIN meanings are the standard Nuvoton Super-I/O sensor labels
# (assumption: exact board placement of AUXTIN0-3 is motherboard specific).
COMPONENT_GUIDE = {
    **{f"SDR{n}-FPGA": f"FPGA chip on software-defined-radio board {n}" for n in range(8)},
    **{f"SDR{n}-RFIC": f"RF integrated circuit (radio front-end) on SDR board {n}" for n in range(8)},
    "CPU-TEMP": "CPU package temperature (processor die)",
    "CPUTIN": "CPU socket temperature measured by the motherboard sensor chip",
    "SYSTIN": "System / motherboard ambient temperature",
    "AUXTIN0": "Auxiliary motherboard sensor 0 (e.g. VRM / chipset area)",
    "AUXTIN1": "Auxiliary motherboard sensor 1",
    "AUXTIN2": "Auxiliary motherboard sensor 2",
    "AUXTIN3": "Auxiliary motherboard sensor 3",
}
COMPONENT_ORDER = list(COMPONENT_GUIDE)
_PALETTE = px.colors.qualitative.Dark24
COMPONENT_COLORS = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(COMPONENT_ORDER)}


def present_components(frame):
    """Components present in `frame`, in the fixed guide order (unique() once: the frame can hold millions of rows)."""
    present = set(frame["component"].unique())
    return [c for c in COMPONENT_ORDER if c in present]


def component_label(name):
    return f"{name} – {COMPONENT_GUIDE.get(name, 'sensor')}"


def style_figure(figure, height=480, legend_title=None):
    figure.update_layout(
        template="plotly_white", height=height,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Segoe UI, Arial, sans-serif", size=14, color="#111827"),
        title=dict(font=dict(size=18, color="#111827"), x=0.01),
        margin=dict(l=60, r=20, t=70, b=60),
        hoverlabel=dict(font_size=13),
        legend=dict(title=dict(text=f"<b>{legend_title}</b>" if legend_title else None),
                    bgcolor="#F3F4F6", bordercolor="#374151", borderwidth=1,
                    font=dict(size=13, color="#111827"), itemsizing="constant"),
    )
    figure.update_xaxes(showgrid=True, gridcolor="#E5E7EB", linecolor="#374151", showline=True,
                        tickfont=dict(color="#111827"), title_font=dict(color="#111827"))
    figure.update_yaxes(showgrid=True, gridcolor="#E5E7EB", linecolor="#374151", showline=True,
                        tickfont=dict(color="#111827"), title_font=dict(color="#111827"))
    return figure


def add_threshold_lines(figure):
    figure.add_hline(y=CRITICAL_TEMP_C, line_dash="dash", line_color="#C62828", line_width=2,
                     annotation_text="Critical 85 °C", annotation_font_color="#C62828")
    figure.add_hline(y=WARNING_TEMP_C, line_dash="dot", line_color="#EF6C00", line_width=1.5,
                     annotation_text="Warning 80 °C", annotation_font_color="#EF6C00",
                     annotation_position="bottom right")
    return figure


def trend_chart(server_minutes, server_name):
    """Line chart of 1-minute mean temperature per component for one server, >85 °C points marked."""
    figure = px.line(server_minutes, x="Timestamp", y="temp_mean", color="component",
                     color_discrete_map=COMPONENT_COLORS,
                     category_orders={"component": COMPONENT_ORDER},
                     title=f"Temperature trend — server {server_name}",
                     labels={"temp_mean": "Temperature (°C)", "Timestamp": "Time", "component": "Component"})
    figure.update_traces(line_width=1.6)
    hot = server_minutes[server_minutes["temp_max"] > CRITICAL_TEMP_C]
    if not hot.empty:
        figure.add_trace(go.Scatter(x=hot["Timestamp"], y=hot["temp_max"], mode="markers",
                                    marker=dict(color="#C62828", size=7, symbol="x"), name="Reading > 85 °C"))
    figure.update_layout(hovermode="x unified")
    figure.update_xaxes(rangeslider_visible=True)
    return style_figure(add_threshold_lines(figure), height=560, legend_title="Component")


def heatmap_chart(minutes):
    """Server x component grid coloured by peak temperature; every component is labelled."""
    peak = minutes.pivot_table(index="server", columns="component", values="temp_max", aggfunc="max")
    peak = peak[[c for c in COMPONENT_ORDER if c in peak.columns]]
    figure = px.imshow(peak, color_continuous_scale="RdYlGn_r", zmin=20, zmax=100, text_auto=".0f",
                       aspect="auto", title="Peak temperature (°C) by server and component",
                       labels={"color": "Peak °C", "x": "Component", "y": "Server"})
    figure.update_xaxes(tickangle=-45, tickmode="array", tickvals=list(peak.columns), showgrid=False)
    figure.update_yaxes(tickmode="array", tickvals=list(peak.index), showgrid=False)
    figure.update_traces(textfont=dict(size=12))
    figure.update_coloraxes(colorbar=dict(title="Peak °C", tickvals=[20, 40, 60, 80, 85, 100]))
    return style_figure(figure, height=40 * len(peak.index) + 220)


def max_temp_bar_chart(minutes, top_n=40):
    """Peak temperature of the hottest server-component pairs, coloured by threshold status."""
    peak = minutes.groupby(["server", "component"])["temp_max"].max().reset_index()
    peak["label"] = peak["server"] + " · " + peak["component"]
    peak["status"] = peak["temp_max"].apply(
        lambda t: "Critical (>85 °C)" if t > CRITICAL_TEMP_C
        else ("Warning (80–85 °C)" if t >= WARNING_TEMP_C else "Normal (<80 °C)"))
    peak = peak.sort_values("temp_max", ascending=False).head(top_n)
    figure = px.bar(peak, x="label", y="temp_max", color="status", text="temp_max",
                    color_discrete_map=STATUS_COLORS, category_orders={"status": list(STATUS_COLORS)},
                    hover_data={"component": True, "server": True, "label": False},
                    title=f"Top {len(peak)} hottest server · component pairs (peak °C)",
                    labels={"temp_max": "Peak temperature (°C)", "label": "Server · component", "status": "Status"})
    figure.update_traces(texttemplate="%{text:.0f}", textposition="outside", textfont_size=11)
    figure.update_xaxes(tickangle=-50, categoryorder="total descending")
    return style_figure(add_threshold_lines(figure), height=560, legend_title="Status")


def distribution_box_chart(minutes):
    """Box plot of temperature distribution for each component type."""
    present = present_components(minutes)
    figure = px.box(minutes, x="component", y="temp_mean", color="component", points=False,
                    color_discrete_map=COMPONENT_COLORS, category_orders={"component": present},
                    title="Temperature distribution by component (all selected servers)",
                    labels={"temp_mean": "Temperature (°C)", "component": "Component"})
    figure.update_xaxes(tickangle=-45)
    return style_figure(add_threshold_lines(figure), height=520, legend_title="Component")


def status_box_chart(minutes):
    """Active vs idle temperature per component: shows how much workload heats each part."""
    data = minutes[minutes["status"].isin(["active", "idle"])]
    present = present_components(data)
    figure = px.box(data, x="component", y="temp_mean", color="status", points=False,
                    color_discrete_map={"active": "#C62828", "idle": "#1565C0"},
                    category_orders={"component": present, "status": ["active", "idle"]},
                    title="Temperature under load (active) vs idle, per component",
                    labels={"temp_mean": "Temperature (°C)", "component": "Component", "status": "Server status"})
    figure.update_xaxes(tickangle=-45)
    return style_figure(add_threshold_lines(figure), height=520, legend_title="Server status")


def anomaly_scatter_chart(anomalies):
    figure = px.scatter(anomalies, x="Timestamp", y="temp_mean", color="component", symbol="server",
                        color_discrete_map=COMPONENT_COLORS, category_orders={"component": COMPONENT_ORDER},
                        hover_data={"z_score": ":.1f", "server": True},
                        title="Anomalous minutes (sudden deviation from the previous hour)",
                        labels={"temp_mean": "Temperature (°C)", "Timestamp": "Time", "component": "Component"})
    figure.update_traces(marker=dict(size=8, line=dict(width=0.5, color="#111827")))
    return style_figure(add_threshold_lines(figure), height=520, legend_title="Component, server")


def risk_level_chart(component_summary):
    counts = component_summary["risk_level"].value_counts().reindex(list(RISK_COLORS), fill_value=0).reset_index()
    counts.columns = ["risk_level", "components"]
    figure = px.bar(counts, x="risk_level", y="components", color="risk_level", text="components",
                    color_discrete_map=RISK_COLORS, title="Components by maintenance risk level",
                    labels={"risk_level": "Risk level", "components": "Server-components"})
    figure.update_traces(textposition="outside")
    return style_figure(figure, height=420, legend_title="Risk level")


def fan_temperature_chart(server_fans, server_minutes, server_name):
    """Two stacked panels sharing the time axis: key temperatures on top, fan speeds below.
    A fan dropping to 0 rpm while temperatures climb points to a cooling failure."""
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                           subplot_titles=("Temperatures (°C)", "Fan speeds (rpm)"))
    for component in ["CPU-TEMP", "SYSTIN", "CPUTIN", "AUXTIN0", "AUXTIN1", "AUXTIN2", "AUXTIN3"]:
        part = server_minutes[server_minutes["component"] == component]
        if not part.empty:
            figure.add_trace(go.Scatter(x=part["Timestamp"], y=part["temp_mean"], name=component,
                                        line=dict(color=COMPONENT_COLORS[component], width=1.5),
                                        legendgroup="temps", legendgrouptitle_text="Temperature"), row=1, col=1)
    fan_palette = px.colors.qualitative.Bold
    for i, (fan, part) in enumerate(server_fans.groupby("fan")):
        figure.add_trace(go.Scatter(x=part["Timestamp"], y=part["rpm"], name=fan,
                                    line=dict(color=fan_palette[i % len(fan_palette)], width=1.5),
                                    legendgroup="fans", legendgrouptitle_text="Fan"), row=2, col=1)
    figure.add_hline(y=CRITICAL_TEMP_C, line_dash="dash", line_color="#C62828", row=1, col=1,
                     annotation_text="Critical 85 °C", annotation_font_color="#C62828")
    figure.update_layout(title=f"Cooling check — server {server_name}", hovermode="x unified")
    figure.update_yaxes(title_text="°C", row=1, col=1)
    figure.update_yaxes(title_text="rpm", row=2, col=1)
    return style_figure(figure, height=700, legend_title=None)
