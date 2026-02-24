#!/usr/bin/env python3
"""
dashboard/app.py
────────────────
Plotly Dash live dashboard. Reads from clean_sensor_data every 3 seconds.
Displays: temperature, humidity, vibration, rolling averages, anomaly flags.

Usage:
    python3 dashboard/app.py
    # Open browser: http://localhost:8050
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, callback
import yaml

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

DB_PATH = Path(__file__).parent.parent / config["database"]["path"]

# ─────────────────────────────────────────
# DATA FETCH
# ─────────────────────────────────────────
def fetch_clean_data(minutes=30):
    """Pull last N minutes of clean data."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn   = sqlite3.connect(DB_PATH)
    cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
    df = pd.read_sql_query("""
        SELECT
            processed_at, device_id,
            temp_f, humidity, vibration,
            temp_avg_60s, humidity_avg_60s, vibration_avg_60s,
            temp_anomaly, humidity_anomaly, vibration_anomaly,
            accel_x, accel_y, accel_z,
            gyro_x, gyro_y, gyro_z
        FROM clean_sensor_data
        WHERE processed_at >= ?
          AND is_valid = 1
        ORDER BY processed_at ASC
    """, conn, params=(cutoff,))
    conn.close()
    if not df.empty:
        df["processed_at"] = pd.to_datetime(df["processed_at"])
    return df


def fetch_stats():
    """Summary stats for the stat cards."""
    if not DB_PATH.exists():
        return {"raw_count": 0, "clean_count": 0, "anomaly_count": 0, "latest": None}
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM raw_sensor_data")
    raw_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clean_sensor_data WHERE is_valid=1")
    clean_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM clean_sensor_data
        WHERE (temp_anomaly=1 OR vibration_anomaly=1 OR humidity_anomaly=1)
        AND processed_at >= datetime('now', '-1 hour')
    """)
    anomaly_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT temp_f, humidity, vibration
        FROM clean_sensor_data
        WHERE is_valid=1
        ORDER BY processed_at DESC LIMIT 1
    """)
    latest = cursor.fetchone()
    conn.close()

    return {
        "raw_count":     raw_count,
        "clean_count":   clean_count,
        "anomaly_count": anomaly_count,
        "latest":        latest,
    }

# ─────────────────────────────────────────
# COLOR PALETTE
# ─────────────────────────────────────────
COLORS = {
    "bg":         "#0a0e1a",
    "surface":    "#111827",
    "surface2":   "#1c2333",
    "border":     "#2d3748",
    "accent1":    "#00d4ff",   # cyan  — temperature
    "accent2":    "#7c3aed",   # violet — humidity
    "accent3":    "#f59e0b",   # amber — vibration
    "anomaly":    "#ef4444",   # red   — anomaly markers
    "avg_line":   "#374151",
    "text":       "#f9fafb",
    "text_dim":   "#6b7280",
    "success":    "#10b981",
}

FONT = "JetBrains Mono, monospace"

# ─────────────────────────────────────────
# CHART BUILDERS
# ─────────────────────────────────────────
def make_chart(df, field, avg_field, anomaly_field, color, label, unit):
    fig = go.Figure()

    if df.empty:
        fig.update_layout(
            paper_bgcolor=COLORS["surface"],
            plot_bgcolor=COLORS["surface"],
            font=dict(color=COLORS["text_dim"], family=FONT),
            annotations=[dict(text="No data yet — waiting for Pico W...",
                              x=0.5, y=0.5, showarrow=False,
                              font=dict(size=13, color=COLORS["text_dim"]))]
        )
        return fig

    # ── main line ──
    fig.add_trace(go.Scatter(
        x=df["processed_at"],
        y=df[field],
        mode="lines",
        name=label,
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=f"rgba({_hex_to_rgb(color)},0.06)",
    ))

    # ── rolling average ──
    if avg_field in df.columns:
        fig.add_trace(go.Scatter(
            x=df["processed_at"],
            y=df[avg_field],
            mode="lines",
            name="60s avg",
            line=dict(color=COLORS["text_dim"], width=1, dash="dot"),
            opacity=0.7,
        ))

    # ── anomaly markers ──
    anomalies = df[df[anomaly_field] == 1]
    if not anomalies.empty:
        fig.add_trace(go.Scatter(
            x=anomalies["processed_at"],
            y=anomalies[field],
            mode="markers",
            name="anomaly",
            marker=dict(color=COLORS["anomaly"], size=10, symbol="x"),
        ))

    fig.update_layout(
        paper_bgcolor=COLORS["surface"],
        plot_bgcolor=COLORS["surface"],
        font=dict(color=COLORS["text"], family=FONT, size=11),
        margin=dict(l=50, r=20, t=30, b=40),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10, color=COLORS["text_dim"]),
            orientation="h", y=-0.2
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor=COLORS["border"],
            gridwidth=0.5,
            tickfont=dict(size=10),
            color=COLORS["text_dim"],
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=COLORS["border"],
            gridwidth=0.5,
            ticksuffix=f" {unit}",
            tickfont=dict(size=10),
            color=COLORS["text_dim"],
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=COLORS["surface2"],
            font=dict(family=FONT, size=11),
        ),
    )
    return fig


def make_accel_chart(df):
    fig = go.Figure()
    if df.empty:
        return fig

    for axis, color in [("accel_x", "#00d4ff"), ("accel_y", "#7c3aed"), ("accel_z", "#f59e0b")]:
        fig.add_trace(go.Scatter(
            x=df["processed_at"],
            y=df[axis],
            mode="lines",
            name=axis.upper(),
            line=dict(color=color, width=1.5),
        ))

    fig.update_layout(
        paper_bgcolor=COLORS["surface"],
        plot_bgcolor=COLORS["surface"],
        font=dict(color=COLORS["text"], family=FONT, size=11),
        margin=dict(l=50, r=20, t=30, b=40),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
            orientation="h", y=-0.25
        ),
        xaxis=dict(showgrid=True, gridcolor=COLORS["border"], color=COLORS["text_dim"]),
        yaxis=dict(showgrid=True, gridcolor=COLORS["border"],
                   ticksuffix=" g", color=COLORS["text_dim"]),
        hovermode="x unified",
    )
    return fig


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return ",".join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))

# ─────────────────────────────────────────
# STAT CARD COMPONENT
# ─────────────────────────────────────────
def stat_card(label, value, unit, color):
    return html.Div([
        html.P(label, style={
            "margin": "0 0 4px 0",
            "fontSize": "10px",
            "letterSpacing": "2px",
            "textTransform": "uppercase",
            "color": COLORS["text_dim"],
            "fontFamily": FONT,
        }),
        html.Div([
            html.Span(value, style={
                "fontSize": "28px",
                "fontWeight": "700",
                "color": color,
                "fontFamily": FONT,
            }),
            html.Span(f" {unit}", style={
                "fontSize": "13px",
                "color": COLORS["text_dim"],
                "fontFamily": FONT,
            }),
        ]),
    ], style={
        "background": COLORS["surface"],
        "border": f"1px solid {COLORS['border']}",
        "borderTop": f"2px solid {color}",
        "borderRadius": "8px",
        "padding": "16px 20px",
        "flex": "1",
        "minWidth": "140px",
    })

# ─────────────────────────────────────────
# APP LAYOUT
# ─────────────────────────────────────────
app = Dash(__name__, title="Pico W Pipeline Dashboard")

app.layout = html.Div([

    # ── Google Font import ──
    html.Link(rel="preconnect", href="https://fonts.googleapis.com"),
    html.Link(rel="stylesheet",
              href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap"),

    # ── Header ──
    html.Div([
        html.Div([
            html.Span("●", style={"color": COLORS["success"], "marginRight": "8px", "fontSize": "12px"}),
            html.Span("LIVE", style={"color": COLORS["success"], "fontSize": "11px",
                                      "letterSpacing": "3px", "fontFamily": FONT}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.H1("PICO W SENSOR PIPELINE", style={
            "margin": "4px 0 0 0",
            "fontSize": "22px",
            "fontWeight": "700",
            "color": COLORS["text"],
            "fontFamily": FONT,
            "letterSpacing": "3px",
        }),
        html.P("Real-time IoT data pipeline · DHT11 + MPU6050 → MQTT → SQLite → Dashboard",
               style={"margin": "4px 0 0 0", "fontSize": "11px",
                      "color": COLORS["text_dim"], "fontFamily": FONT}),
    ], style={
        "borderBottom": f"1px solid {COLORS['border']}",
        "padding": "20px 32px",
        "background": COLORS["surface"],
    }),

    # ── Stat cards ──
    html.Div(id="stat-cards", style={
        "display": "flex",
        "gap": "12px",
        "padding": "20px 32px 0",
        "flexWrap": "wrap",
    }),

    # ── Charts ──
    html.Div([

        html.Div([
            html.P("TEMPERATURE", style={"margin": "0 0 8px", "fontSize": "10px",
                                          "letterSpacing": "2px", "color": COLORS["text_dim"],
                                          "fontFamily": FONT}),
            dcc.Graph(id="temp-chart", config={"displayModeBar": False}),
        ], style={"background": COLORS["surface"], "border": f"1px solid {COLORS['border']}",
                  "borderRadius": "8px", "padding": "16px"}),

        html.Div([
            html.P("HUMIDITY", style={"margin": "0 0 8px", "fontSize": "10px",
                                       "letterSpacing": "2px", "color": COLORS["text_dim"],
                                       "fontFamily": FONT}),
            dcc.Graph(id="humidity-chart", config={"displayModeBar": False}),
        ], style={"background": COLORS["surface"], "border": f"1px solid {COLORS['border']}",
                  "borderRadius": "8px", "padding": "16px"}),

        html.Div([
            html.P("VIBRATION MAGNITUDE (g)", style={"margin": "0 0 8px", "fontSize": "10px",
                                                      "letterSpacing": "2px", "color": COLORS["text_dim"],
                                                      "fontFamily": FONT}),
            dcc.Graph(id="vibration-chart", config={"displayModeBar": False}),
        ], style={"background": COLORS["surface"], "border": f"1px solid {COLORS['border']}",
                  "borderRadius": "8px", "padding": "16px"}),

        html.Div([
            html.P("ACCELEROMETER XYZ (g)", style={"margin": "0 0 8px", "fontSize": "10px",
                                                     "letterSpacing": "2px", "color": COLORS["text_dim"],
                                                     "fontFamily": FONT}),
            dcc.Graph(id="accel-chart", config={"displayModeBar": False}),
        ], style={"background": COLORS["surface"], "border": f"1px solid {COLORS['border']}",
                  "borderRadius": "8px", "padding": "16px"}),

    ], style={
        "display": "grid",
        "gridTemplateColumns": "1fr 1fr",
        "gap": "12px",
        "padding": "20px 32px 32px",
    }),

    # ── Live refresh interval ──
    dcc.Interval(id="interval", interval=3000, n_intervals=0),

], style={
    "background": COLORS["bg"],
    "minHeight": "100vh",
    "fontFamily": FONT,
})

# ─────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────
@callback(
    Output("stat-cards",      "children"),
    Output("temp-chart",      "figure"),
    Output("humidity-chart",  "figure"),
    Output("vibration-chart", "figure"),
    Output("accel-chart",     "figure"),
    Input("interval", "n_intervals"),
)
def update_dashboard(n):
    df    = fetch_clean_data(minutes=30)
    stats = fetch_stats()

    latest = stats["latest"]
    t_val  = f"{latest[0]:.1f}" if latest and latest[0] is not None else "—"
    h_val  = f"{latest[1]:.1f}" if latest and latest[1] is not None else "—"
    v_val  = f"{latest[2]:.3f}" if latest and latest[2] is not None else "—"

    cards = html.Div([
        stat_card("Temperature",   t_val,                          "°F",      COLORS["accent1"]),
        stat_card("Humidity",      h_val,                          "%",       COLORS["accent2"]),
        stat_card("Vibration",     v_val,                          "g",       COLORS["accent3"]),
        stat_card("Raw Records",   f"{stats['raw_count']:,}",      "total",   COLORS["text_dim"]),
        stat_card("Clean Records", f"{stats['clean_count']:,}",    "valid",   COLORS["success"]),
        stat_card("Anomalies 1hr", str(stats["anomaly_count"]),    "flagged", COLORS["anomaly"]),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap"})

    temp_fig      = make_chart(df, "temp_f",    "temp_avg_60s",
                               "temp_anomaly",      COLORS["accent1"], "Temp (°F)",   "°F")
    humidity_fig  = make_chart(df, "humidity",  "humidity_avg_60s",
                               "humidity_anomaly",  COLORS["accent2"], "Humidity (%)","%")
    vibration_fig = make_chart(df, "vibration", "vibration_avg_60s",
                               "vibration_anomaly", COLORS["accent3"], "Vibration",   "g")
    accel_fig     = make_accel_chart(df)

    return cards, temp_fig, humidity_fig, vibration_fig, accel_fig


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
