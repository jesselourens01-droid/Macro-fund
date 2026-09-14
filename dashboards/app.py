"""JL Global Macro Investment Platform - Phase 1 research dashboard.

This is intentionally minimal: an instrument browser with a price chart and a macro
indicator viewer that visualises the point-in-time revision history, plus a system
status panel. The full 8-page CIO dashboard (NAV, risk, positions, attribution,
investment journal, ...) described in the platform spec is built from Phase 9 onward,
once there is a portfolio/risk/attribution layer to display.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from jlmacro.config import get_settings, load_yaml_config
from jlmacro.database.session import session_scope
from jlmacro.models.instrument import Instrument
from jlmacro.models.signals import compute_investment_score
from jlmacro.reporting.queries import (
    list_instruments,
    macro_data_history,
    market_data_history,
    regime_history,
    regime_matrix,
    system_status,
)

st.set_page_config(page_title="JL Global Macro Platform", layout="wide")

settings = get_settings()

st.title("JL Global Macro Investment Platform")
st.caption("Phase 1 - Research & data wiring dashboard. Live trading disabled by default.")

with session_scope() as session:
    status = system_status(session)
    instruments_df = list_instruments(session)

status_cols = st.columns(5)
status_cols[0].metric("Environment", settings.jlmacro_env)
status_cols[1].metric("Instruments", status["instruments"])
status_cols[2].metric("Market data rows", f"{status['market_data_points']:,}")
status_cols[3].metric("Macro data rows", f"{status['macro_data_points']:,}")
status_cols[4].metric(
    "Live trading", "ENABLED" if settings.jlmacro_live_trading_enabled else "disabled"
)

if instruments_df.empty:
    st.warning(
        "No instruments found. Seed the database first: "
        "`python scripts/generate_synthetic_data.py`"
    )
    st.stop()

tab_prices, tab_macro, tab_regime, tab_signals, tab_universe = st.tabs(
    ["Prices", "Macro Indicators", "Macro Regime", "Signals", "Asset Universe"]
)

with tab_prices:
    st.subheader("Instrument price history (synthetic)")
    asset_classes = sorted(instruments_df["asset_class"].unique())
    col1, col2 = st.columns([1, 3])
    with col1:
        selected_class = st.selectbox("Asset class", asset_classes)
        symbols = instruments_df.loc[
            instruments_df["asset_class"] == selected_class, "symbol"
        ].tolist()
        selected_symbol = st.selectbox("Instrument", symbols)

    with session_scope() as session:
        price_df = market_data_history(session, selected_symbol)

    if price_df.empty:
        st.info("No price history for this instrument yet.")
    else:
        with col2:
            fig = go.Figure(
                data=[
                    go.Candlestick(
                        x=price_df["timestamp"],
                        open=price_df["open"],
                        high=price_df["high"],
                        low=price_df["low"],
                        close=price_df["close"],
                        name=selected_symbol,
                    )
                ]
            )
            fig.update_layout(
                title=f"{selected_symbol} - daily synthetic price",
                xaxis_title="Date",
                yaxis_title="Level",
                height=480,
                xaxis_rangeslider_visible=False,
            )
            st.plotly_chart(fig, width="stretch")

        last_close = price_df["close"].iloc[-1]
        ret_20d = (
            price_df["close"].iloc[-1] / price_df["close"].iloc[-21] - 1
            if len(price_df) > 20
            else None
        )
        m1, m2 = st.columns(2)
        m1.metric("Last close", f"{last_close:,.4f}")
        m2.metric("20-session return", f"{ret_20d:+.2%}" if ret_20d is not None else "n/a")

with tab_macro:
    st.subheader("Macro indicator viewer (point-in-time)")
    st.caption(
        "Shows both the value known at first release and the latest revised value, "
        "to illustrate the platform's point-in-time data discipline."
    )
    col1, col2 = st.columns(2)
    country = col1.text_input("Country code", value="US").upper()
    indicator_code = col2.text_input("Indicator code", value="CPI_HEADLINE").upper()

    with session_scope() as session:
        macro_df = macro_data_history(session, country, indicator_code)

    if macro_df.empty:
        st.info("No macro data for this country/indicator combination yet.")
    else:
        latest_per_period = (
            macro_df.sort_values("revision_date").groupby("effective_date").last().reset_index()
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=latest_per_period["effective_date"],
                y=latest_per_period["original_value"],
                mode="lines+markers",
                name="First release",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=latest_per_period["effective_date"],
                y=latest_per_period["value"],
                mode="lines+markers",
                name="Latest known value",
            )
        )
        fig.update_layout(
            title=f"{country} / {indicator_code}",
            xaxis_title="Effective date",
            yaxis_title="Value",
            height=420,
        )
        st.plotly_chart(fig, width="stretch")
        st.dataframe(macro_df.sort_values("effective_date", ascending=False), width="stretch")

with tab_regime:
    st.subheader("Country regime matrix")
    st.caption(
        "Growth / Inflation / Monetary Policy / Financial Conditions buckets (-2..+2) "
        "and the classified regime for each country's latest snapshot. Run "
        "`python scripts/compute_regime_snapshots.py` to (re)compute these from "
        "current macro data."
    )

    countries = load_yaml_config("macro_indicators").get("countries", [])
    with session_scope() as session:
        matrix_df = regime_matrix(session, countries)

    if matrix_df.empty:
        st.info(
            "No regime snapshots yet. Run `python scripts/compute_regime_snapshots.py` "
            "after seeding macro data."
        )
    else:
        display_df = matrix_df.set_index("country")[
            [
                "regime",
                "confidence",
                "growth",
                "inflation",
                "monetary_policy",
                "financial_conditions",
            ]
        ]

        def _bucket_color(value: object) -> str:
            # Manual red(-2)->white(0)->green(+2) scale - avoids adding matplotlib
            # just for pandas Styler.background_gradient.
            if not isinstance(value, int | float) or pd.isna(value):
                return ""
            clamped = max(-2.0, min(2.0, float(value)))
            if clamped >= 0:
                t = clamped / 2.0
                r, g, b = (
                    int(255 * (1 - t) + 26 * t),
                    int(255 * (1 - t) + 152 * t),
                    int(255 * (1 - t) + 80 * t),
                )
            else:
                t = -clamped / 2.0
                r, g, b = (
                    int(255 * (1 - t) + 211 * t),
                    int(255 * (1 - t) + 47 * t),
                    int(255 * (1 - t) + 47 * t),
                )
            return f"background-color: rgb({r},{g},{b})"

        bucket_cols = ["growth", "inflation", "monetary_policy", "financial_conditions"]
        styled = display_df.style.map(_bucket_color, subset=bucket_cols).format(
            {"confidence": "{:.0%}"}
        )
        st.dataframe(styled, width="stretch")

        st.divider()
        st.subheader("Regime history for one country")
        selected_country = st.selectbox("Country", countries, key="regime_country")

        with session_scope() as session:
            history_df = regime_history(session, selected_country)

        if history_df.empty:
            st.info(f"No regime snapshots for {selected_country} yet.")
        else:
            fig = go.Figure()
            for column, label in [
                ("growth_score", "Growth"),
                ("inflation_score", "Inflation"),
                ("monetary_policy_score", "Monetary Policy"),
                ("financial_conditions_score", "Financial Conditions"),
            ]:
                fig.add_trace(
                    go.Scatter(
                        x=history_df["as_of"], y=history_df[column], mode="lines", name=label
                    )
                )
            fig.update_layout(
                title=f"{selected_country} category scores",
                xaxis_title="As of",
                yaxis_title="Composite z-score",
                height=380,
            )
            st.plotly_chart(fig, width="stretch")

            latest = history_df.iloc[-1]
            m1, m2 = st.columns(2)
            m1.metric("Current regime", latest["regime"].replace("_", " ").title())
            m2.metric("Confidence", f"{latest['confidence']:.0%}")

            st.dataframe(history_df.sort_values("as_of", ascending=False), width="stretch")

with tab_signals:
    st.subheader("Investment signals - ranked opportunities")
    st.caption(
        "Composite = weighted Macro / Valuation / Trend / Positioning / Catalyst "
        "(weights and action thresholds from config/risk_limits.yaml). Positioning "
        "and Catalyst use documented proxies (RSI-based crowding; projected-cadence "
        "and self-referential surprise) pending real CFTC/options/consensus-calendar "
        "data - see src/jlmacro/models/signals/ docstrings. **suggested_risk_units is "
        "advisory only** - the risk engine (Phase 5+) has final authority over "
        "position size."
    )

    @st.cache_data(ttl=300)
    def _compute_all_scores(as_of_iso: str, asset_class_value: str | None) -> list[dict]:
        as_of = dt.date.fromisoformat(as_of_iso)
        with session_scope() as scoring_session:
            stmt = select(Instrument).where(Instrument.is_active.is_(True))
            if asset_class_value:
                stmt = stmt.where(Instrument.asset_class == asset_class_value)
            symbols = [
                instrument.symbol
                for instrument in scoring_session.scalars(stmt.order_by(Instrument.symbol))
            ]

            rows = []
            for symbol in symbols:
                score = compute_investment_score(scoring_session, symbol, as_of=as_of)
                rows.append(
                    {
                        "symbol": score.instrument_symbol,
                        "action": score.action,
                        "composite": score.composite_score,
                        "macro": score.macro_score,
                        "valuation": score.valuation_score,
                        "trend": score.trend_score,
                        "positioning": score.positioning_score,
                        "catalyst": score.catalyst_score,
                        "trend_label": score.detail.get("trend_label"),
                        "positioning_label": score.detail.get("positioning_label"),
                    }
                )
            return rows

    col1, col2 = st.columns(2)
    signal_as_of = col1.date_input(
        "As of", value=dt.datetime.now(tz=dt.UTC).date(), key="signals_as_of"
    )
    asset_class_options = ["All", *sorted(instruments_df["asset_class"].unique())]
    signal_asset_class = col2.selectbox(
        "Asset class filter", asset_class_options, key="signals_asset_class"
    )

    rows = _compute_all_scores(
        signal_as_of.isoformat(), None if signal_asset_class == "All" else signal_asset_class
    )
    scores_df = pd.DataFrame(rows).sort_values("composite", ascending=False, na_position="last")

    _ACTION_COLORS = {
        "max_unit": "background-color: rgb(26,152,80); color: white",
        "full_unit": "background-color: rgb(140,198,101)",
        "half_unit": "background-color: rgb(217,239,139)",
        "watchlist": "background-color: rgb(255,235,180)",
        "no_position": "",
    }

    display_cols = [
        "symbol",
        "action",
        "composite",
        "macro",
        "valuation",
        "trend",
        "positioning",
        "catalyst",
    ]
    numeric_cols = ["composite", "macro", "valuation", "trend", "positioning", "catalyst"]
    styled_scores = (
        scores_df[display_cols]
        .style.map(lambda v: _ACTION_COLORS.get(v, ""), subset=["action"])
        .format({c: "{:.1f}" for c in numeric_cols}, na_rep="—")
    )
    st.dataframe(styled_scores, width="stretch", hide_index=True)

    if not scores_df.empty:
        st.divider()
        st.subheader("Signal detail for one instrument")
        detail_symbol = st.selectbox(
            "Instrument", scores_df["symbol"].tolist(), key="signals_detail_symbol"
        )
        detail_row = scores_df.loc[scores_df["symbol"] == detail_symbol].iloc[0]

        fig = go.Figure(
            go.Bar(
                x=["Macro", "Valuation", "Trend", "Positioning", "Catalyst"],
                y=[
                    detail_row[col]
                    for col in ["macro", "valuation", "trend", "positioning", "catalyst"]
                ],
            )
        )
        fig.update_layout(
            title=f"{detail_symbol} factor breakdown",
            yaxis_title="Score (0-100, 50 = neutral)",
            yaxis_range=[0, 100],
            height=350,
        )
        st.plotly_chart(fig, width="stretch")

        m1, m2, m3 = st.columns(3)
        m1.metric(
            "Composite score",
            f"{detail_row['composite']:.1f}" if pd.notna(detail_row["composite"]) else "n/a",
        )
        m2.metric("Action", str(detail_row["action"]).replace("_", " ").title())
        m3.metric("Trend label", str(detail_row["trend_label"]).replace("_", " ").title())

with tab_universe:
    st.subheader("Configured asset universe")
    st.caption(
        "Loaded from config/assets.yaml - edit that file to change the universe, no code changes needed."
    )
    st.dataframe(instruments_df, width="stretch")
