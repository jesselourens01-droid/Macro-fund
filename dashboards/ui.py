"""Shared visual system and investor-report rendering for the Streamlit dashboard."""

from __future__ import annotations

import datetime as dt
import html
from collections.abc import Mapping

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

NAVY = "#071426"
PANEL = "#0D1F35"
PANEL_ALT = "#122A45"
BLUE = "#35A7FF"
TEAL = "#3DD6C6"
GREEN = "#4ADE80"
AMBER = "#F4B942"
RED = "#F87171"
TEXT = "#E8F0FA"
MUTED = "#94A8C1"
GRID = "rgba(148, 168, 193, 0.12)"


def inject_institutional_theme() -> None:
    """Apply a compact institutional visual system without a frontend dependency."""

    st.markdown(
        f"""
        <style>
        .stApp {{ background: {NAVY}; color: {TEXT}; }}
        [data-testid="stHeader"] {{ background: rgba(7, 20, 38, 0.92); }}
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #08182B 0%, #0A2036 100%);
            border-right: 1px solid rgba(148,168,193,.16);
        }}
        .block-container {{ max-width: 1580px; padding-top: 1.35rem; padding-bottom: 3rem; }}
        h1, h2, h3 {{ letter-spacing: -0.025em; }}
        h1 {{ font-size: 2rem !important; }}
        h2 {{ font-size: 1.35rem !important; }}
        h3 {{ font-size: 1.02rem !important; color: {TEXT}; }}
        p, label, [data-testid="stCaptionContainer"] {{ color: {MUTED}; }}
        [data-testid="stMetric"] {{
            background: linear-gradient(145deg, {PANEL} 0%, {PANEL_ALT} 100%);
            border: 1px solid rgba(148,168,193,.14);
            border-radius: 12px;
            padding: 1rem 1.05rem;
            box-shadow: 0 10px 30px rgba(0,0,0,.14);
        }}
        [data-testid="stMetricLabel"] {{ color: {MUTED}; }}
        [data-testid="stMetricValue"] {{ color: {TEXT}; letter-spacing: -.03em; }}
        [data-testid="stTabs"] button {{ color: {MUTED}; font-weight: 600; }}
        [data-testid="stTabs"] button[aria-selected="true"] {{ color: {TEAL}; }}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: {TEAL}; }}
        [data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {{
            border: 1px solid rgba(148,168,193,.12);
            border-radius: 12px;
            overflow: hidden;
        }}
        .stButton > button, .stDownloadButton > button {{
            border-radius: 9px;
            border: 1px solid rgba(61,214,198,.45);
            background: rgba(61,214,198,.10);
            color: {TEXT};
            font-weight: 650;
        }}
        .stButton > button:hover, .stDownloadButton > button:hover {{
            border-color: {TEAL}; color: white; background: rgba(61,214,198,.18);
        }}
        .jl-hero {{
            background: radial-gradient(circle at 92% 10%, rgba(53,167,255,.20), transparent 34%),
                        linear-gradient(135deg, #0D223B 0%, #0A1A2E 65%, #102943 100%);
            border: 1px solid rgba(61,214,198,.20);
            border-radius: 16px;
            padding: 1.35rem 1.55rem 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 18px 50px rgba(0,0,0,.20);
        }}
        .jl-eyebrow {{ color: {TEAL}; font-size: .72rem; font-weight: 750;
            letter-spacing: .16em; text-transform: uppercase; margin-bottom: .35rem; }}
        .jl-title {{ color: white; font-size: 1.8rem; line-height: 1.15;
            font-weight: 730; letter-spacing: -.035em; }}
        .jl-subtitle {{ color: {MUTED}; font-size: .92rem; margin-top: .45rem; }}
        .jl-badge {{ display: inline-block; border: 1px solid rgba(61,214,198,.35);
            background: rgba(61,214,198,.10); color: {TEAL}; border-radius: 999px;
            padding: .22rem .6rem; font-size: .68rem; font-weight: 700; margin-top: .75rem; }}
        .jl-section {{ color: {TEXT}; font-size: 1.02rem; font-weight: 700;
            letter-spacing: -.015em; margin: .5rem 0 .15rem; }}
        .jl-note {{ border-left: 3px solid {AMBER}; background: rgba(244,185,66,.07);
            padding: .7rem .85rem; border-radius: 0 8px 8px 0; color: {MUTED};
            font-size: .82rem; }}
        hr {{ border-color: rgba(148,168,193,.12) !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def configure_plotly_theme() -> None:
    """Register the house chart template before any figures are constructed."""

    pio.templates["jl_institutional"] = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=PANEL,
            plot_bgcolor=PANEL,
            font={"color": TEXT, "family": "Inter, Segoe UI, sans-serif", "size": 12},
            title_font={"size": 15, "color": TEXT},
            colorway=[BLUE, TEAL, AMBER, RED, "#A78BFA", "#60A5FA"],
            margin={"l": 44, "r": 22, "t": 55, "b": 42},
            hoverlabel={"bgcolor": PANEL_ALT, "font_color": TEXT, "bordercolor": BLUE},
            xaxis={"gridcolor": GRID, "zerolinecolor": GRID},
            yaxis={"gridcolor": GRID, "zerolinecolor": GRID},
        )
    )
    pio.templates.default = "jl_institutional"


def style_figure(
    fig: go.Figure, *, title: str | None = None, height: int | None = None
) -> go.Figure:
    """Give every Plotly visual a consistent, presentation-ready treatment."""

    fig.update_layout(
        title=title,
        height=height,
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font={"color": TEXT, "family": "Inter, Segoe UI, sans-serif", "size": 12},
        title_font={"size": 15, "color": TEXT},
        colorway=[BLUE, TEAL, AMBER, RED, "#A78BFA", "#60A5FA"],
        margin={"l": 44, "r": 22, "t": 55 if title else 24, "b": 42},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hoverlabel={"bgcolor": PANEL_ALT, "font_color": TEXT, "bordercolor": BLUE},
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, showline=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, showline=False)
    return fig


def investor_report_html(
    *,
    fund_name: str,
    as_of: dt.date,
    metrics: Mapping[str, str],
    market: pd.DataFrame,
    regimes: pd.DataFrame,
) -> str:
    """Render a portable, standalone investment snapshot for stakeholder sharing."""

    metric_cards = "".join(
        f'<div class="metric"><span>{html.escape(label)}</span>'
        f"<strong>{html.escape(value)}</strong></div>"
        for label, value in metrics.items()
    )
    market_table = market.head(12).to_html(index=False, border=0, classes="data")
    regime_table = regimes.to_html(index=False, border=0, classes="data")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(fund_name)} | Investor Snapshot</title>
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:#071426;color:#e8f0fa;
margin:0;padding:40px}}
.wrap{{max-width:1180px;margin:auto}} .eyebrow{{color:#3dd6c6;font-size:12px;
font-weight:700;letter-spacing:2px}}
h1{{font-size:34px;margin:8px 0}} .muted{{color:#94a8c1}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}}
.metric{{background:#0d1f35;border:1px solid #1c3857;border-radius:12px;padding:18px}}
.metric span{{display:block;color:#94a8c1;font-size:12px}}
.metric strong{{display:block;font-size:23px;margin-top:8px}}
section{{background:#0d1f35;border:1px solid #1c3857;border-radius:12px;
padding:22px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;color:#94a8c1;border-bottom:1px solid #284562;padding:9px}}
td{{padding:9px;border-bottom:1px solid #162d47}}
.notice{{border-left:3px solid #f4b942;padding:12px 16px;background:#172437;
color:#c4d1df}}
@media(max-width:800px){{.metrics{{grid-template-columns:repeat(2,1fr)}} body{{padding:20px}}}}
</style></head><body><div class="wrap"><div class="eyebrow">
INVESTOR REPORTING • RESEARCH ENVIRONMENT</div>
<h1>{html.escape(fund_name)}</h1><p class="muted">
Portfolio command-centre snapshot as of {as_of.isoformat()}</p>
<div class="metrics">{metric_cards}</div><section><h2>Market pulse</h2>{market_table}</section>
<section><h2>Macro regime monitor</h2>{regime_table}</section>
<p class="notice">Research output only. Synthetic or proxy data may be present.
This report is not investment advice and is not a substitute for administrator,
custodian or broker records.</p>
</div></body></html>"""
