"""JL Global Macro institutional portfolio command centre.

The Streamlit application is a presentation layer over the platform's point-in-time
research, portfolio, risk, execution, audit and reporting services. Business logic
remains in ``src/jlmacro`` so dashboard figures and exported datasets are reproducible.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from jlmacro.attribution.pnl import compute_pnl_attribution
from jlmacro.backtest.engine import run_backtest
from jlmacro.backtest.monte_carlo import bootstrap_terminal_nav
from jlmacro.config import get_settings, load_yaml_config
from jlmacro.database.session import session_scope
from jlmacro.execution.paper_broker import PaperBroker
from jlmacro.execution.service import close_trade_via_broker, open_trade_via_broker
from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.ml.evaluation import compare_models
from jlmacro.models.ml.features import build_feature_dataset
from jlmacro.models.ml.models import MODEL_FACTORIES
from jlmacro.models.portfolio import Portfolio, Trade
from jlmacro.models.signals import compute_investment_score
from jlmacro.nav.engine import drawdown_series, high_water_mark_series, nav_history
from jlmacro.nav.fees import compute_performance_fee, fees_config
from jlmacro.portfolio.construction import (
    equal_risk_contribution_weights,
    inverse_volatility_weights,
    risk_contributions,
    scale_to_target_volatility,
)
from jlmacro.portfolio.covariance import (
    annualised_volatility,
    ledoit_wolf_covariance,
    returns_matrix,
)
from jlmacro.portfolio.exposures import (
    component_contribution_to_risk,
    compute_exposures,
)
from jlmacro.portfolio.sizing import compute_position_size
from jlmacro.reporting.investor import (
    build_data_room_export,
    data_quality_snapshot,
    market_pulse,
    portfolio_operating_summary,
    recent_audit_activity,
)
from jlmacro.reporting.queries import (
    list_instruments,
    macro_data_history,
    market_data_history,
    regime_history,
    regime_matrix,
    system_status,
)
from jlmacro.risk.drawdown import (
    apply_drawdown_governor,
    drawdown_governor_config,
    is_defensive_mode,
    risk_budget_fraction_for_drawdown,
)
from jlmacro.risk.stress import apply_historical_scenario, apply_hypothetical_scenario
from jlmacro.risk.var import compute_all_var_methods
from jlmacro.trades.lifecycle import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    create_trade_idea,
    transition,
)
from jlmacro.trades.memo import generate_investment_memo
from jlmacro.trades.review import close_trade, generate_post_trade_review
from ui import (
    configure_plotly_theme,
    inject_institutional_theme,
    investor_report_html,
    style_figure,
)

st.set_page_config(
    page_title="JL Global Macro | Portfolio Command Centre",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_institutional_theme()
configure_plotly_theme()

settings = get_settings()
platform_config = load_yaml_config("settings")
fund_config = platform_config["fund"]
today = dt.datetime.now(tz=dt.UTC).date()

st.sidebar.markdown("### Command centre")
dashboard_as_of = st.sidebar.date_input("Reporting date", value=today, max_value=today)
st.sidebar.caption(
    f"Base currency · {fund_config['base_currency']}  \n"
    f"Mandate · {fund_config['jurisdiction']}"
)
if settings.jlmacro_live_trading_enabled:
    st.sidebar.error("Live trading is enabled")
else:
    st.sidebar.success("Paper execution · controls active")
st.sidebar.divider()
st.sidebar.caption(
    "Data lineage: point-in-time market and macro observations with an append-only audit trail."
)

st.markdown(
    f"""
    <div class="jl-hero">
      <div class="jl-eyebrow">Institutional research & portfolio intelligence</div>
      <div class="jl-title">{fund_config['name']} — Portfolio Command Centre</div>
      <div class="jl-subtitle">A unified view of performance, risk, macro regimes,
      investment decisions and operating controls.</div>
      <div class="jl-badge">RESEARCH ENVIRONMENT · PAPER EXECUTION</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with session_scope() as session:
    status = system_status(session)
    instruments_df = list_instruments(session)
    quality = data_quality_snapshot(session)
    market_pulse_df = market_pulse(session, as_of=dashboard_as_of)
    audit_df = recent_audit_activity(session)
    overview_portfolios = list(session.scalars(select(Portfolio).order_by(Portfolio.name)))

countries = load_yaml_config("macro_indicators").get("countries", [])
with session_scope() as session:
    overview_regimes_df = regime_matrix(session, countries, as_of=dashboard_as_of)

status_cols = st.columns(5)
status_cols[0].metric("Environment", settings.jlmacro_env.title())
status_cols[1].metric(
    "Coverage",
    f"{quality.price_coverage_pct:.0%}",
    f"{quality.instruments_with_prices}/{quality.active_instruments} assets",
)
status_cols[2].metric("Market observations", f"{status['market_data_points']:,}")
status_cols[3].metric("Macro observations", f"{status['macro_data_points']:,}")
status_cols[4].metric(
    "Execution", "LIVE" if settings.jlmacro_live_trading_enabled else "PAPER ONLY"
)

if instruments_df.empty:
    st.warning(
        "No instruments found. Seed the database first: "
        "`python scripts/generate_synthetic_data.py`"
    )
    st.stop()

(
    tab_overview,
    tab_prices,
    tab_macro,
    tab_regime,
    tab_signals,
    tab_portfolio,
    tab_risk,
    tab_backtest,
    tab_journal,
    tab_performance,
    tab_ml,
    tab_universe,
) = st.tabs(
    [
        "Overview",
        "Markets",
        "Macro",
        "Regimes",
        "Signals",
        "Portfolio Lab",
        "Risk Lab",
        "Backtests",
        "Trade Book",
        "Performance",
        "ML Lab",
        "Data Room",
    ]
)

report_metrics: dict[str, str] = {
    "Price coverage": f"{quality.price_coverage_pct:.0%}",
    "Active instruments": f"{quality.active_instruments:,}",
    "Market observations": f"{quality.market_rows:,}",
    "Audit events": f"{quality.audit_events:,}",
}

with tab_overview:
    st.markdown(
        '<div class="jl-section">Executive portfolio overview</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Decision-ready performance, exposure, market and control information for investment "
        "committee and investor conversations."
    )

    overview_summary: dict[str, object] | None = None
    overview_nav = None
    overview_hwm = None
    overview_dd = None
    if overview_portfolios:
        portfolio_options = {portfolio.name: portfolio.id for portfolio in overview_portfolios}
        selected_overview_name = st.selectbox(
            "Portfolio",
            list(portfolio_options),
            key="overview_portfolio",
            help="Select the portfolio used for executive performance and exposure metrics.",
        )
        selected_overview_id = portfolio_options[selected_overview_name]
        inception = dt.date.fromisoformat(fund_config["inception_date"])
        effective_start = min(inception, dashboard_as_of)
        fee_policy = fees_config()
        with session_scope() as session:
            overview_summary = portfolio_operating_summary(session, selected_overview_id)
            overview_nav = nav_history(
                session,
                selected_overview_id,
                start=effective_start,
                end=dashboard_as_of,
                starting_capital=fee_policy["starting_capital"],
            )
        overview_hwm = high_water_mark_series(overview_nav)
        overview_dd = drawdown_series(overview_nav)
        nav_returns = overview_nav.pct_change().dropna()
        nav_value = float(overview_nav.iloc[-1])
        total_return = nav_value / float(overview_nav.iloc[0]) - 1.0
        annualised_vol = (
            float(nav_returns.std(ddof=1) * math.sqrt(252)) if len(nav_returns) > 1 else 0.0
        )
        max_drawdown = float(overview_dd.min())
        live_trades = int(overview_summary["live_trades"])
        gross_notional = float(overview_summary["gross_notional"])

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Net asset value", f"{fund_config['base_currency']} {nav_value:,.0f}")
        k2.metric("Total return", f"{total_return:+.2%}")
        k3.metric("Annualised volatility", f"{annualised_vol:.2%}")
        k4.metric("Maximum drawdown", f"{max_drawdown:.2%}")
        k5.metric("Live positions", f"{live_trades}", f"{gross_notional:,.0f} gross")
        report_metrics = {
            "Net asset value": f"{fund_config['base_currency']} {nav_value:,.0f}",
            "Total return": f"{total_return:+.2%}",
            "Annualised volatility": f"{annualised_vol:.2%}",
            "Maximum drawdown": f"{max_drawdown:.2%}",
        }
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Starting capital",
            f"{fund_config['base_currency']} {fees_config()['starting_capital']:,.0f}",
        )
        k2.metric("Portfolios", "0", "Create one in Trade Book")
        k3.metric("Price coverage", f"{quality.price_coverage_pct:.0%}")
        k4.metric("Regime snapshots", f"{quality.regime_snapshots:,}")
        st.info(
            "Create a portfolio in the Trade Book to activate live NAV, drawdown, exposure and "
            "attribution reporting. Market and macro research tools are already available."
        )

    chart_left, chart_right = st.columns([1.6, 1])
    with chart_left:
        if overview_nav is not None and overview_hwm is not None:
            nav_fig = go.Figure()
            nav_fig.add_trace(
                go.Scatter(
                    x=overview_nav.index,
                    y=overview_nav.values,
                    name="NAV",
                    mode="lines",
                    line={"width": 2.6, "color": "#3DD6C6"},
                    fill="tozeroy",
                    fillcolor="rgba(61,214,198,.08)",
                )
            )
            nav_fig.add_trace(
                go.Scatter(
                    x=overview_hwm.index,
                    y=overview_hwm.values,
                    name="High-water mark",
                    mode="lines",
                    line={"width": 1.2, "dash": "dot", "color": "#94A8C1"},
                )
            )
            style_figure(nav_fig, title="Portfolio value and capital preservation", height=390)
            nav_fig.update_yaxes(tickprefix=f"{fund_config['base_currency']} ", tickformat=",")
            st.plotly_chart(nav_fig, width="stretch")
        elif not market_pulse_df.empty:
            movers = market_pulse_df.dropna(subset=["return_20d"]).copy()
            movers = movers.sort_values("return_20d").tail(12)
            mover_fig = go.Figure(
                go.Bar(
                    x=movers["return_20d"],
                    y=movers["symbol"],
                    orientation="h",
                    marker_color=[
                        "#4ADE80" if value >= 0 else "#F87171"
                        for value in movers["return_20d"]
                    ],
                    text=[f"{value:+.1%}" for value in movers["return_20d"]],
                    textposition="outside",
                )
            )
            style_figure(mover_fig, title="20-session market leadership", height=390)
            mover_fig.update_xaxes(tickformat=".0%")
            st.plotly_chart(mover_fig, width="stretch")

    with chart_right:
        if not overview_regimes_df.empty:
            regime_view = overview_regimes_df[
                ["country", "regime", "confidence", "as_of"]
            ].copy()
            regime_view["regime"] = regime_view["regime"].str.replace("_", " ").str.title()
            st.markdown(
                '<div class="jl-section">Global regime monitor</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(
                regime_view.style.format({"confidence": "{:.0%}"}),
                width="stretch",
                hide_index=True,
                height=350,
            )
        else:
            st.info("Compute regime snapshots to activate the global regime monitor.")

    st.markdown('<div class="jl-section">Cross-asset market pulse</div>', unsafe_allow_html=True)
    if market_pulse_df.empty:
        st.info("No market observations are available yet.")
    else:
        pulse_view = market_pulse_df.sort_values(
            "return_20d", ascending=False, na_position="last"
        ).head(12)
        st.dataframe(
            pulse_view[
                [
                    "symbol",
                    "asset_class",
                    "last",
                    "change_1d",
                    "return_20d",
                    "realised_vol_20d",
                    "as_of",
                    "source",
                ]
            ].style.format(
                {
                    "last": "{:,.4f}",
                    "change_1d": "{:+.2%}",
                    "return_20d": "{:+.2%}",
                    "realised_vol_20d": "{:.1%}",
                },
                na_rep="—",
            ),
            width="stretch",
            hide_index=True,
        )

    control_cols = st.columns(4)
    control_cols[0].metric("Price coverage", f"{quality.price_coverage_pct:.0%}")
    control_cols[1].metric("Market sources", quality.market_sources)
    control_cols[2].metric("Macro sources", quality.macro_sources)
    control_cols[3].metric("Audit events", f"{quality.audit_events:,}")
    st.markdown(
        '<div class="jl-note"><strong>Control note:</strong> Outputs may include synthetic '
        "prices and documented proxy factors. Live trading remains disabled. Validate real-data "
        "licensing, reconciliation, custody and compliance workflows before presenting audited "
        "performance or allocating capital.</div>",
        unsafe_allow_html=True,
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
        "data - see the signal-model documentation. **Suggested risk units are advisory "
        "only**; the risk engine retains final authority over position size."
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

with tab_portfolio:
    st.subheader("Portfolio construction")
    st.caption(
        "Point-in-time covariance -> weighting (inverse-vol or equal-risk-contribution) "
        "→ scaled to the mandate's target volatility. This is an allocation laboratory, "
        "not an executed portfolio. Review the resulting risk, concentration and scenario "
        "analytics before approving positions in the Trade Book."
    )

    col1, col2, col3 = st.columns(3)
    portfolio_symbols = col1.multiselect(
        "Instruments",
        sorted(instruments_df["symbol"].unique()),
        default=[
            s for s in ["SPX", "US10Y", "XAU", "EURUSD"] if s in instruments_df["symbol"].values
        ],
        key="portfolio_symbols",
    )
    portfolio_as_of = col2.date_input(
        "As of", value=dt.datetime.now(tz=dt.UTC).date(), key="portfolio_as_of"
    )
    weighting_method = col3.selectbox(
        "Weighting method",
        ["equal_risk_contribution", "inverse_volatility"],
        key="portfolio_weighting_method",
    )
    target_vol = st.slider(
        "Target annualised volatility",
        min_value=0.02,
        max_value=0.20,
        value=load_yaml_config("risk_limits")["target_volatility"],
        step=0.005,
        format="%.3f",
        key="portfolio_target_vol",
    )

    if len(portfolio_symbols) < 2:
        st.info("Select at least two instruments to estimate a covariance matrix.")
    else:
        with session_scope() as session:
            returns = returns_matrix(session, portfolio_symbols, as_of=portfolio_as_of)
        missing = [s for s in portfolio_symbols if s not in returns.columns]
        if missing:
            st.warning(f"No point-in-time price history yet for: {missing}")
        elif returns.empty:
            st.warning("Not enough overlapping price history to estimate covariance.")
        else:
            cov = ledoit_wolf_covariance(returns)
            vol = annualised_volatility(returns)

            try:
                raw_weights = (
                    inverse_volatility_weights(vol)
                    if weighting_method == "inverse_volatility"
                    else equal_risk_contribution_weights(cov)
                )
            except RuntimeError as exc:
                st.error(f"Equal-risk-contribution solver failed to converge: {exc}")
                raw_weights = inverse_volatility_weights(vol)

            scaled = scale_to_target_volatility(raw_weights, cov, target_volatility=target_vol)
            contributions = risk_contributions(raw_weights, cov)

            normalised_abs_weights = scaled.weights.abs() / scaled.weights.abs().sum()
            effective_bets = 1.0 / float((normalised_abs_weights**2).sum())
            weighted_asset_vol = float((normalised_abs_weights * vol).sum())
            diversification_ratio = (
                weighted_asset_vol / scaled.portfolio_volatility
                if scaled.portfolio_volatility > 0
                else 0.0
            )

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Gross leverage", f"{scaled.gross_leverage:.2f}x")
            m2.metric("Portfolio volatility", f"{scaled.portfolio_volatility:.1%}")
            m3.metric("Instruments", len(portfolio_symbols))
            m4.metric("Effective bets", f"{effective_bets:.1f}")
            m5.metric("Diversification ratio", f"{diversification_ratio:.2f}x")

            weights_df = pd.DataFrame(
                {
                    "weight": scaled.weights,
                    "risk_contribution": contributions,
                    "annualised_vol": vol,
                }
            ).sort_values("weight", ascending=False)

            wcol1, wcol2 = st.columns(2)
            with wcol1:
                fig = go.Figure(go.Bar(x=weights_df.index, y=weights_df["weight"], name="Weight"))
                fig.update_layout(title="Scaled portfolio weights (fraction of NAV)", height=360)
                st.plotly_chart(fig, width="stretch")
            with wcol2:
                fig = go.Figure(
                    go.Bar(
                        x=weights_df.index,
                        y=weights_df["risk_contribution"],
                        name="Risk contribution",
                        marker_color="indianred",
                    )
                )
                fig.update_layout(
                    title="Risk contribution (fraction of portfolio variance)", height=360
                )
                st.plotly_chart(fig, width="stretch")

            st.dataframe(
                weights_df.style.format(
                    {"weight": "{:.2%}", "risk_contribution": "{:.2%}", "annualised_vol": "{:.1%}"}
                ),
                width="stretch",
            )

            st.caption(
                "Correlation matrix — identify hidden concentration before capital is allocated."
            )
            correlation = returns.corr()
            correlation_fig = go.Figure(
                go.Heatmap(
                    z=correlation.values,
                    x=correlation.columns,
                    y=correlation.index,
                    zmin=-1,
                    zmax=1,
                    colorscale=[
                        [0.0, "#F87171"],
                        [0.5, "#122A45"],
                        [1.0, "#3DD6C6"],
                    ],
                    colorbar={"title": "ρ"},
                    hovertemplate="%{x} / %{y}<br>Correlation %{z:.2f}<extra></extra>",
                )
            )
            style_figure(correlation_fig, title="Cross-asset correlation", height=430)
            st.plotly_chart(correlation_fig, width="stretch")

            st.divider()
            st.subheader("Exposure breakdown")
            with session_scope() as session:
                summary = compute_exposures(session, scaled.weights)
            ccr = component_contribution_to_risk(scaled.weights, cov)

            ecol1, ecol2 = st.columns(2)
            ecol1.metric("Gross exposure", f"{summary.gross:.2%}")
            ecol2.metric("Net exposure", f"{summary.net:.2%}")

            bcol1, bcol2, bcol3 = st.columns(3)
            for col, title, breakdown in (
                (bcol1, "By asset class", summary.by_asset_class),
                (bcol2, "By country", summary.by_country),
                (bcol3, "By currency", summary.by_currency),
            ):
                col.caption(title)
                if breakdown:
                    col.dataframe(
                        pd.Series(breakdown, name="weight").to_frame().style.format("{:.2%}"),
                        width="stretch",
                    )
                else:
                    col.write("n/a")

            st.caption(
                "Component contribution to risk (CCR) - sums exactly to total portfolio "
                "volatility; a better answer than raw weight to 'where does our risk come from'."
            )
            st.dataframe(ccr.to_frame("component_contribution_to_risk").style.format("{:.2%}"))

    st.divider()
    st.subheader("Risk-based position sizing")
    st.caption(
        "Risk budget = NAV × allowed risk percentage, calibrated by conviction band; "
        "position size = risk budget ÷ ATR-based stop distance."
    )

    scol1, scol2, scol3, scol4 = st.columns(4)
    sizing_symbol = scol1.selectbox(
        "Instrument", sorted(instruments_df["symbol"].unique()), key="sizing_symbol"
    )
    sizing_nav = scol2.number_input(
        "NAV", min_value=0.0, value=10_000_000.0, step=100_000.0, key="sizing_nav"
    )
    sizing_risk_units = scol3.selectbox("Risk units", [0.5, 1.0, 1.5], index=1, key="sizing_units")
    sizing_direction = scol4.selectbox(
        "Direction", [1, -1], format_func=lambda d: "Long" if d == 1 else "Short", key="sizing_dir"
    )

    with session_scope() as session:
        size_result = compute_position_size(
            session,
            sizing_symbol,
            nav=sizing_nav,
            risk_units=sizing_risk_units,
            direction=sizing_direction,
            as_of=portfolio_as_of,
        )

    if size_result.notional is None:
        st.info(
            "Notional not computable - either risk_units is 0.0 (no conviction) or "
            "there isn't enough point-in-time price history yet to estimate ATR."
        )
    else:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Risk budget", f"{size_result.risk_budget:,.0f}")
        r2.metric(
            "Stop distance",
            f"{size_result.stop_distance_pct:.2%}" if size_result.stop_distance_pct else "n/a",
        )
        r3.metric("Notional", f"{size_result.notional:,.0f}")
        r4.metric("Price", f"{size_result.price:,.4f}" if size_result.price else "n/a")

with tab_risk:
    st.subheader("Risk engine")
    st.caption(
        "VaR/Expected Shortfall, stress testing and the drawdown governor - the layer "
        "with authority over proposed risk. It uses the instruments and weights selected "
        "in Portfolio Lab; scenario results remain analytical until positions are approved "
        "through the controlled trade workflow."
    )

    if "scaled" not in globals() or len(portfolio_symbols) < 2:
        st.info(
            "Select at least two instruments (and a valid target volatility) in the "
            "Portfolio tab above first."
        )
    else:
        risk_nav = st.number_input(
            "NAV", min_value=0.0, value=10_000_000.0, step=100_000.0, key="risk_nav"
        )

        with session_scope() as session:
            var_results = compute_all_var_methods(
                session, portfolio_symbols, scaled.weights, nav=risk_nav, as_of=portfolio_as_of
            )

        var_df = pd.DataFrame(
            {
                method: {
                    "VaR %": r.var_pct,
                    "ES %": r.es_pct,
                    "VaR amount": r.var_amount,
                    "ES amount": r.es_amount,
                }
                for method, r in var_results.items()
            }
        ).T
        any_result = next(iter(var_results.values()))
        st.caption(
            f"{any_result.horizon_days}-day VaR/ES at {any_result.confidence:.0%} confidence"
        )

        risk_limits = load_yaml_config("risk_limits")
        soft_limit = float(risk_limits["soft_volatility_limit"])
        hard_limit = float(risk_limits["hard_volatility_limit"])
        limit_status = (
            "BREACH"
            if scaled.portfolio_volatility > hard_limit
            else "WATCH"
            if scaled.portfolio_volatility > soft_limit
            else "WITHIN LIMIT"
        )
        utilisation = scaled.portfolio_volatility / hard_limit if hard_limit else 0.0
        l1, l2, l3 = st.columns(3)
        l1.metric("Volatility limit status", limit_status)
        l2.metric("Hard-limit utilisation", f"{utilisation:.0%}")
        l3.metric("Hard volatility limit", f"{hard_limit:.1%}")

        vcol1, vcol2 = st.columns(2)
        with vcol1:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=var_df.index, y=var_df["VaR %"], name="VaR"))
            fig.add_trace(go.Bar(x=var_df.index, y=var_df["ES %"], name="Expected Shortfall"))
            fig.update_layout(title="VaR / ES by method (fraction of NAV)", height=360)
            st.plotly_chart(fig, width="stretch")
        with vcol2:
            st.dataframe(
                var_df.style.format(
                    {
                        "VaR %": "{:.2%}",
                        "ES %": "{:.2%}",
                        "VaR amount": "{:,.0f}",
                        "ES amount": "{:,.0f}",
                    }
                ),
                width="stretch",
            )

        st.divider()
        st.subheader("Stress testing")
        scenario_config = load_yaml_config("scenarios")
        hypothetical_ids = [s["id"] for s in scenario_config["hypothetical_scenarios"]]
        historical_ids = [s["id"] for s in scenario_config["historical_scenarios"]]

        scol1, scol2 = st.columns(2)
        with scol1:
            st.caption("Hypothetical shock")
            hyp_id = st.selectbox("Scenario", hypothetical_ids, key="risk_hyp_scenario")
            with session_scope() as session:
                hyp_result = apply_hypothetical_scenario(
                    session, scaled.weights, hyp_id, nav=risk_nav
                )
            st.metric("P&L", f"{hyp_result.pnl_amount:,.0f}", f"{hyp_result.pnl_pct:+.2%}")
            if hyp_result.unmapped_shock_keys:
                st.caption(
                    "Not reflected above (no direct mapping onto this instrument "
                    f"universe yet): {', '.join(hyp_result.unmapped_shock_keys)}"
                )

        with scol2:
            st.caption("Historical replay")
            hist_id = st.selectbox("Scenario", historical_ids, key="risk_hist_scenario")
            with session_scope() as session:
                hist_result = apply_historical_scenario(
                    session, scaled.weights, hist_id, nav=risk_nav
                )
            st.metric("P&L", f"{hist_result.pnl_amount:,.0f}", f"{hist_result.pnl_pct:+.2%}")
            if hist_result.missing_symbols:
                st.caption(
                    "No point-in-time price history in this window for: "
                    f"{', '.join(hist_result.missing_symbols)} - this platform only has "
                    "synthetic price history so far, not real historical prices."
                )

        st.divider()
        st.subheader("Drawdown governor")
        st.caption(
            "config/risk_limits.yaml's drawdown_governor schedule: the fraction of the "
            "normal risk budget retained at a given drawdown from the fund's high-water "
            "mark. Use the scenario control below to inspect the policy response before a "
            "drawdown threshold is breached."
        )
        governor_config = drawdown_governor_config()
        current_drawdown = st.slider(
            "Current drawdown vs high-water mark",
            min_value=-0.25,
            max_value=0.0,
            value=-0.05,
            step=0.005,
            format="%.3f",
            key="risk_current_drawdown",
        )
        fraction = risk_budget_fraction_for_drawdown(current_drawdown, config=governor_config)
        defensive = is_defensive_mode(current_drawdown, config=governor_config)

        dcol1, dcol2, dcol3 = st.columns(3)
        dcol1.metric("Risk budget retained", f"{fraction:.0%}")
        dcol2.metric("Defensive mode", "YES" if defensive else "no")
        if "size_result" in globals() and size_result.risk_budget:
            governed_budget = apply_drawdown_governor(
                size_result.risk_budget, current_drawdown, config=governor_config
            )
            dcol3.metric("Governed risk budget (from Sizing above)", f"{governed_budget:,.0f}")

with tab_backtest:
    st.subheader("Backtest")
    st.caption(
        "Replays the signal engine and portfolio construction process "
        "over history, one rebalance period at a time - each period's weights are "
        "decided using only data knowable before that period starts. Slow: one "
        "investment-score computation per symbol per rebalance date, so keep the "
        "date range and symbol count modest here."
    )

    bcol1, bcol2, bcol3 = st.columns(3)
    backtest_symbols = bcol1.multiselect(
        "Instruments",
        sorted(instruments_df["symbol"].unique()),
        default=[
            s
            for s in ["SPX", "NDX", "US10Y", "XAU", "EURUSD", "AUDUSD"]
            if s in instruments_df["symbol"].values
        ],
        key="backtest_symbols",
    )
    backtest_start = bcol2.date_input("Start", value=dt.date(2025, 1, 1), key="backtest_start")
    backtest_end = bcol3.date_input(
        "End", value=dt.datetime.now(tz=dt.UTC).date(), key="backtest_end"
    )
    backtest_rebalance_days = st.slider(
        "Rebalance frequency (days)", min_value=7, max_value=90, value=21, key="backtest_rebalance"
    )

    if len(backtest_symbols) < 2:
        st.info("Select at least two instruments.")
    elif backtest_start >= backtest_end:
        st.warning("Start date must be before end date.")
    elif st.button("Run backtest", key="backtest_run_button"):
        with (
            st.spinner(
                "Running backtest - this replays the signal engine at every rebalance date..."
            ),
            session_scope() as session,
        ):
            backtest_result = run_backtest(
                session,
                backtest_symbols,
                start=backtest_start,
                end=backtest_end,
                rebalance_frequency_days=backtest_rebalance_days,
            )

        nav_curve = backtest_result.nav_curve()
        rcol1, rcol2, rcol3, rcol4 = st.columns(4)
        rcol1.metric("Total return", f"{backtest_result.total_return:+.2%}")
        rcol2.metric("Annualised vol", f"{backtest_result.annualised_volatility:.2%}")
        rcol3.metric("Sharpe ratio", f"{backtest_result.sharpe_ratio:.2f}")
        rcol4.metric("Max drawdown", f"{backtest_result.max_drawdown:.2%}")

        fig = go.Figure(go.Scatter(x=nav_curve.index, y=nav_curve.values, mode="lines+markers"))
        fig.update_layout(title="NAV curve", xaxis_title="Date", yaxis_title="NAV", height=380)
        st.plotly_chart(fig, width="stretch")

        periods_df = pd.DataFrame(
            [
                {
                    "period_start": p.period_start,
                    "period_end": p.period_end,
                    "return": p.period_return,
                    "positions": len(p.weights),
                }
                for p in backtest_result.periods
            ]
        )
        st.dataframe(
            periods_df.style.format({"return": "{:+.2%}"}), width="stretch", hide_index=True
        )

        period_returns = backtest_result.period_returns()
        if not period_returns.empty:
            st.divider()
            st.subheader("Monte Carlo (bootstrap of this backtest's period returns)")
            mc_result = bootstrap_terminal_nav(
                period_returns, nav0=backtest_result.nav0, num_simulations=5_000, seed=42
            )
            mcol1, mcol2 = st.columns(2)
            with mcol1:
                st.caption("Terminal NAV percentiles")
                st.dataframe(
                    pd.Series(mc_result.terminal_nav_percentiles, name="NAV")
                    .to_frame()
                    .style.format("{:,.0f}")
                )
            with mcol2:
                st.caption("Max drawdown percentiles")
                st.dataframe(
                    pd.Series(mc_result.max_drawdown_percentiles, name="Drawdown")
                    .to_frame()
                    .style.format("{:.2%}")
                )
            st.metric("Probability of loss", f"{mc_result.probability_of_loss:.1%}")
            st.metric(
                "Probability of breaching defensive-mode drawdown",
                f"{mc_result.probability_of_defensive_mode_breach:.1%}",
            )

with tab_journal:
    st.subheader("Trade journal")
    st.caption(
        "Create trade ideas, move them through the lifecycle (idea -> watchlist/"
        "approved -> open -> reduce -> closed, or invalidated at any non-terminal "
        "point), and read the investment memo / post-trade review generated from "
        "each trade's own recorded data. Every transition is audited."
    )

    with session_scope() as session:
        portfolios = list(session.scalars(select(Portfolio).order_by(Portfolio.name)))

    jcol1, jcol2 = st.columns(2)
    with jcol1:
        st.caption("Create a portfolio")
        new_portfolio_name = st.text_input("Portfolio name", key="journal_new_portfolio_name")
        if st.button("Create portfolio", key="journal_create_portfolio") and new_portfolio_name:
            with session_scope() as session:
                if session.scalar(select(Portfolio).where(Portfolio.name == new_portfolio_name)):
                    st.warning("A portfolio with that name already exists.")
                else:
                    session.add(Portfolio(name=new_portfolio_name))
            st.rerun()

    if not portfolios:
        st.info("Create a portfolio above to start logging trade ideas.")
    else:
        with jcol2:
            selected_portfolio = st.selectbox(
                "Portfolio", portfolios, format_func=lambda p: p.name, key="journal_portfolio"
            )

        st.divider()
        st.caption("New trade idea")
        ncol1, ncol2, ncol3 = st.columns(3)
        idea_symbol = ncol1.selectbox(
            "Instrument", sorted(instruments_df["symbol"].unique()), key="journal_idea_symbol"
        )
        idea_direction = ncol2.selectbox(
            "Direction", ["long", "short"], key="journal_idea_direction"
        )
        idea_composite = ncol3.number_input(
            "Composite score (optional)",
            min_value=0.0,
            max_value=100.0,
            value=70.0,
            key="journal_idea_composite",
        )
        idea_thesis = st.text_area("Thesis", key="journal_idea_thesis")
        idea_actor = st.text_input(
            "Your name (required to approve later)", key="journal_idea_actor"
        )

        if st.button("Log trade idea", key="journal_log_idea") and idea_thesis:
            with session_scope() as session:
                instrument = session.scalar(
                    select(Instrument).where(Instrument.symbol == idea_symbol)
                )
                create_trade_idea(
                    session,
                    portfolio_id=selected_portfolio.id,
                    instrument_id=instrument.id,
                    direction=(
                        TradeDirection.LONG if idea_direction == "long" else TradeDirection.SHORT
                    ),
                    thesis=idea_thesis,
                    composite_score=idea_composite,
                    actor=idea_actor or "system",
                )
            st.rerun()

        st.divider()
        st.caption("Trades in this portfolio")
        with session_scope() as session:
            trades = list(
                session.scalars(
                    select(Trade)
                    .where(Trade.portfolio_id == selected_portfolio.id)
                    .order_by(Trade.created_at.desc())
                )
            )
            trade_symbols = {
                t.instrument_id: session.get(Instrument, t.instrument_id).symbol for t in trades
            }

        if not trades:
            st.info("No trades logged yet for this portfolio.")
        else:
            trades_df = pd.DataFrame(
                [
                    {
                        "trade_id": t.trade_id,
                        "symbol": trade_symbols[t.instrument_id],
                        "direction": t.direction.value,
                        "status": t.status.value,
                        "composite_score": t.composite_score,
                        "created_at": t.created_at,
                    }
                    for t in trades
                ]
            )
            st.dataframe(trades_df, width="stretch", hide_index=True)

            st.divider()
            st.caption("Manage one trade")
            selected_trade_id = st.selectbox(
                "Trade", trades_df["trade_id"].tolist(), key="journal_selected_trade"
            )
            with session_scope() as session:
                selected_trade = session.scalar(
                    select(Trade).where(Trade.trade_id == selected_trade_id)
                )
                allowed_next = sorted(s.value for s in ALLOWED_TRANSITIONS[selected_trade.status])

            mcol1, mcol2, mcol3, mcol4 = st.columns(4)
            with mcol1:
                if allowed_next:
                    next_status = st.selectbox("Move to", allowed_next, key="journal_next_status")
                    transition_actor = st.text_input("Actor", key="journal_transition_actor")
                    if st.button("Apply transition", key="journal_apply_transition"):
                        with session_scope() as session:
                            trade_to_move = session.scalar(
                                select(Trade).where(Trade.trade_id == selected_trade_id)
                            )
                            try:
                                transition(
                                    session,
                                    trade_to_move,
                                    TradeStatus(next_status),
                                    actor=transition_actor or "system",
                                )
                                st.success(f"Moved to {next_status}.")
                            except InvalidTransitionError as exc:
                                st.error(str(exc))
                else:
                    st.caption("Terminal status - no further transitions.")

            with mcol2:
                if selected_trade.status in (TradeStatus.OPEN, TradeStatus.REDUCE):
                    exit_price = st.number_input(
                        "Exit price", min_value=0.0, key="journal_exit_price"
                    )
                    close_actor = st.text_input("Closed by", key="journal_close_actor")
                    if st.button("Close trade", key="journal_close_trade") and exit_price > 0:
                        with session_scope() as session:
                            trade_to_close = session.scalar(
                                select(Trade).where(Trade.trade_id == selected_trade_id)
                            )
                            close_trade(
                                session,
                                trade_to_close,
                                exit_price=exit_price,
                                actor=close_actor or "system",
                            )
                        st.success("Trade closed.")

            with mcol3:
                st.caption("Execute (paper broker)")
                if selected_trade.status == TradeStatus.APPROVED:
                    order_qty = st.number_input(
                        "Quantity", min_value=0.0, value=100.0, key="journal_open_order_qty"
                    )
                    order_actor = st.text_input("Actor", key="journal_open_order_actor")
                    if st.button("Submit opening order", key="journal_submit_open_order"):
                        with session_scope() as session:
                            trade_to_open = session.scalar(
                                select(Trade).where(Trade.trade_id == selected_trade_id)
                            )
                            broker = PaperBroker(session)
                            result = open_trade_via_broker(
                                session,
                                broker,
                                trade_to_open,
                                quantity=order_qty,
                                as_of=dt.datetime.now(tz=dt.UTC).date(),
                                actor=order_actor or "system",
                            )
                        if result.status.value == "filled":
                            st.success(f"Filled at {result.filled_price:,.4f}.")
                        else:
                            st.warning(f"Order {result.status.value}: {result.rejected_reason}")
                elif selected_trade.status in (TradeStatus.OPEN, TradeStatus.REDUCE):
                    order_qty = st.number_input(
                        "Quantity", min_value=0.0, value=100.0, key="journal_close_order_qty"
                    )
                    order_actor = st.text_input("Actor", key="journal_close_order_actor")
                    if st.button("Submit closing order", key="journal_submit_close_order"):
                        with session_scope() as session:
                            trade_to_close_via_broker = session.scalar(
                                select(Trade).where(Trade.trade_id == selected_trade_id)
                            )
                            broker = PaperBroker(session)
                            result = close_trade_via_broker(
                                session,
                                broker,
                                trade_to_close_via_broker,
                                quantity=order_qty,
                                as_of=dt.datetime.now(tz=dt.UTC).date(),
                                actor=order_actor or "system",
                            )
                        if result.status.value == "filled":
                            st.success(f"Filled at {result.filled_price:,.4f}.")
                        else:
                            st.warning(f"Order {result.status.value}: {result.rejected_reason}")
                else:
                    st.caption("No order to submit for this status.")

            with mcol4:
                st.caption("View")
                if st.button("Show investment memo", key="journal_show_memo"):
                    with session_scope() as session:
                        trade_for_memo = session.scalar(
                            select(Trade).where(Trade.trade_id == selected_trade_id)
                        )
                        memo = generate_investment_memo(session, trade_for_memo)
                    st.markdown(memo.to_markdown())

                if selected_trade.status == TradeStatus.CLOSED and st.button(
                    "Show post-trade review", key="journal_show_review"
                ):
                    with session_scope() as session:
                        trade_for_review = session.scalar(
                            select(Trade).where(Trade.trade_id == selected_trade_id)
                        )
                        review = generate_post_trade_review(session, trade_for_review)
                    st.write(review)

with tab_performance:
    st.subheader("Performance: NAV, drawdown, attribution")
    st.caption(
        "Computed on demand from this portfolio's controlled trade records - never a "
        "separately-maintained ledger. Realised P&L uses each trade's recorded exit "
        "price; unrealised P&L marks open trades to the latest point-in-time close."
    )

    with session_scope() as session:
        perf_portfolios = list(session.scalars(select(Portfolio).order_by(Portfolio.name)))

    if not perf_portfolios:
        st.info("No portfolios yet - create one in the Trade Journal tab.")
    else:
        pcol1, pcol2, pcol3 = st.columns(3)
        perf_portfolio = pcol1.selectbox(
            "Portfolio", perf_portfolios, format_func=lambda p: p.name, key="perf_portfolio"
        )
        perf_start = pcol2.date_input(
            "Start",
            value=dt.date.fromisoformat(load_yaml_config("settings")["fund"]["inception_date"]),
            key="perf_start",
        )
        perf_as_of = pcol3.date_input(
            "As of", value=dt.datetime.now(tz=dt.UTC).date(), key="perf_as_of"
        )

        fees = fees_config()
        with session_scope() as session:
            series = nav_history(
                session,
                perf_portfolio.id,
                start=perf_start,
                end=perf_as_of,
                starting_capital=fees["starting_capital"],
            )
        hwm_series = high_water_mark_series(series)
        dd_series = drawdown_series(series)
        nav_gross = float(series.iloc[-1])
        hwm = float(hwm_series.iloc[-1])
        fee_result = compute_performance_fee(
            nav_gross, hwm, performance_fee_pct=fees["performance_fee_pct"]
        )

        mcol1, mcol2, mcol3, mcol4 = st.columns(4)
        mcol1.metric("NAV (gross)", f"{nav_gross:,.0f}")
        mcol2.metric("High-water mark", f"{hwm:,.0f}")
        mcol3.metric("Drawdown", f"{float(dd_series.iloc[-1]):.2%}")
        mcol4.metric("Performance fee accrued", f"{fee_result.performance_fee_accrued:,.0f}")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name="NAV"))
        fig.add_trace(
            go.Scatter(
                x=hwm_series.index, y=hwm_series.values, mode="lines", name="High-water mark"
            )
        )
        fig.update_layout(title="NAV vs high-water mark", height=380)
        st.plotly_chart(fig, width="stretch")

        fig = go.Figure(
            go.Scatter(x=dd_series.index, y=dd_series.values, mode="lines", fill="tozeroy")
        )
        fig.update_layout(title="Drawdown from high-water mark", height=280, yaxis_tickformat=".0%")
        st.plotly_chart(fig, width="stretch")

        st.divider()
        st.subheader("P&L attribution")
        attribution_group_by = st.selectbox(
            "Group by", ["symbol", "asset_class", "direction"], key="perf_attribution_group_by"
        )
        with session_scope() as session:
            attribution = compute_pnl_attribution(
                session, perf_portfolio.id, as_of=perf_as_of, group_by=attribution_group_by
            )

        if not attribution:
            st.info("No trades have contributed P&L yet for this portfolio/date.")
        else:
            attribution_df = pd.Series(attribution, name="pnl").sort_values(ascending=False)
            fig = go.Figure(go.Bar(x=attribution_df.index, y=attribution_df.values))
            fig.update_layout(title=f"P&L attribution by {attribution_group_by}", height=360)
            st.plotly_chart(fig, width="stretch")
            st.dataframe(attribution_df.to_frame().style.format("{:,.0f}"), width="stretch")

with tab_ml:
    st.subheader("ML research layer")
    st.caption(
        "Features are the composite score's five point-in-time components (already "
        "point-in-time correct); the label is the sign of the forward return over a "
        "chosen horizon. Walk-forward validated (chronological splits, never "
        "shuffled) against a majority-class baseline. Expensive - one investment-"
        "score computation per symbol per date - keep the selections modest."
    )

    ml_col1, ml_col2, ml_col3 = st.columns(3)
    ml_symbols = ml_col1.multiselect(
        "Instruments",
        sorted(instruments_df["symbol"].unique()),
        default=[
            s
            for s in ["SPX", "NDX", "US10Y", "XAU", "EURUSD"]
            if s in instruments_df["symbol"].values
        ],
        key="ml_symbols",
    )
    ml_horizon = ml_col2.number_input(
        "Forward-return horizon (days)", min_value=5, max_value=90, value=21, key="ml_horizon"
    )
    ml_n_splits = ml_col3.number_input(
        "Walk-forward splits", min_value=2, max_value=10, value=4, key="ml_n_splits"
    )

    ml_start = st.date_input("Dates from", value=dt.date(2025, 1, 1), key="ml_start")
    ml_num_dates = st.slider(
        "Number of sample dates (spaced by the horizon)",
        min_value=6,
        max_value=60,
        value=20,
        key="ml_num_dates",
    )
    ml_model_names = st.multiselect(
        "Models",
        list(MODEL_FACTORIES.keys()),
        default=["logistic", "random_forest", "gradient_boosting"],
        key="ml_model_names",
    )

    if len(ml_symbols) < 1 or not ml_model_names:
        st.info("Select at least one instrument and one model.")
    elif st.button("Run walk-forward evaluation", key="ml_run_button"):
        with st.spinner("Building features and walk-forward validating..."):
            ml_dates = [
                ml_start + dt.timedelta(days=int(ml_horizon) * i) for i in range(int(ml_num_dates))
            ]
            with session_scope() as session:
                ml_dataset = build_feature_dataset(
                    session, ml_symbols, ml_dates, horizon_days=int(ml_horizon)
                )

        if ml_dataset.empty:
            st.warning(
                "No feature/label rows could be built - check that a RegimeSnapshot "
                "exists for the relevant countries and that price history extends "
                "past the forward-return horizon."
            )
        else:
            st.caption(f"{len(ml_dataset)} feature/label rows built.")
            try:
                ml_results = compare_models(ml_dataset, ml_model_names, n_splits=int(ml_n_splits))
            except ValueError as exc:
                st.error(str(exc))
            else:
                summary_df = pd.DataFrame(
                    [
                        {
                            "model": name,
                            "mean model accuracy": r.mean_model_accuracy,
                            "mean baseline accuracy": r.mean_baseline_accuracy,
                            "beats baseline": r.beats_baseline,
                            "mean AUC": r.mean_model_auc,
                        }
                        for name, r in ml_results.items()
                    ]
                ).set_index("model")
                st.dataframe(
                    summary_df.style.format(
                        {
                            "mean model accuracy": "{:.1%}",
                            "mean baseline accuracy": "{:.1%}",
                            "mean AUC": "{:.3f}",
                        },
                        na_rep="n/a",
                    ),
                    width="stretch",
                )

                fig = go.Figure()
                fig.add_trace(
                    go.Bar(x=summary_df.index, y=summary_df["mean model accuracy"], name="Model")
                )
                fig.add_trace(
                    go.Bar(
                        x=summary_df.index,
                        y=summary_df["mean baseline accuracy"],
                        name="Baseline (majority class)",
                    )
                )
                fig.update_layout(
                    title="Walk-forward mean accuracy vs. baseline",
                    yaxis_tickformat=".0%",
                    height=380,
                )
                st.plotly_chart(fig, width="stretch")

with tab_universe:
    st.subheader("Investor data room & operating controls")
    st.caption(
        "Curated exports, data lineage and audit evidence for investment committee, investor "
        "due-diligence and downstream analysis."
    )

    q1, q2, q3, q4, q5 = st.columns(5)
    q1.metric("Active instruments", quality.active_instruments)
    q2.metric("Price coverage", f"{quality.price_coverage_pct:.0%}")
    q3.metric("Regime snapshots", f"{quality.regime_snapshots:,}")
    q4.metric("Market sources", quality.market_sources)
    q5.metric("Macro sources", quality.macro_sources)

    latest_market_label = (
        quality.latest_market_date.isoformat() if quality.latest_market_date else "—"
    )
    latest_macro_label = (
        quality.latest_macro_date.isoformat() if quality.latest_macro_date else "—"
    )
    latest_ingestion_label = (
        quality.latest_ingestion_at.isoformat(timespec="seconds")
        if quality.latest_ingestion_at
        else "—"
    )
    lineage = pd.DataFrame(
        [
            {
                "dataset": "Market prices",
                "rows": quality.market_rows,
                "latest_effective_date": latest_market_label,
                "coverage": f"{quality.price_coverage_pct:.0%}",
                "control": "Point-in-time timestamps and source identifiers",
            },
            {
                "dataset": "Macroeconomic observations",
                "rows": quality.macro_rows,
                "latest_effective_date": latest_macro_label,
                "coverage": f"{quality.macro_sources} source(s)",
                "control": "Release and revision vintages preserved",
            },
            {
                "dataset": "Regime model output",
                "rows": quality.regime_snapshots,
                "latest_effective_date": (
                    str(overview_regimes_df["as_of"].max())
                    if not overview_regimes_df.empty
                    else "—"
                ),
                "coverage": f"{len(overview_regimes_df)}/{len(countries)} countries",
                "control": "Model version stored with every snapshot",
            },
            {
                "dataset": "Audit trail",
                "rows": quality.audit_events,
                "latest_effective_date": latest_ingestion_label,
                "coverage": "Append-only",
                "control": "Actor, entity and event identifiers",
            },
        ]
    )
    st.dataframe(lineage, width="stretch", hide_index=True)

    export_market = market_pulse_df.copy()
    export_regimes = overview_regimes_df.copy()
    generated_at = dt.datetime.now(tz=dt.UTC)
    data_room_zip = build_data_room_export(
        market=export_market,
        regimes=export_regimes,
        instruments=instruments_df,
        audit=audit_df,
        quality=quality,
        generated_at=generated_at,
    )

    report_market = export_market[
        ["symbol", "asset_class", "last", "change_1d", "return_20d", "as_of", "source"]
    ].copy() if not export_market.empty else export_market
    if not report_market.empty:
        report_market["change_1d"] = report_market["change_1d"].map(
            lambda value: f"{value:+.2%}" if pd.notna(value) else "—"
        )
        report_market["return_20d"] = report_market["return_20d"].map(
            lambda value: f"{value:+.2%}" if pd.notna(value) else "—"
        )
        report_market["last"] = report_market["last"].map(lambda value: f"{value:,.4f}")

    report_regimes = export_regimes[
        ["country", "regime", "confidence", "as_of"]
    ].copy() if not export_regimes.empty else export_regimes
    if not report_regimes.empty:
        report_regimes["regime"] = report_regimes["regime"].str.replace("_", " ").str.title()
        report_regimes["confidence"] = report_regimes["confidence"].map(
            lambda value: f"{value:.0%}"
        )

    report_html = investor_report_html(
        fund_name=fund_config["name"],
        as_of=dashboard_as_of,
        metrics=report_metrics,
        market=report_market,
        regimes=report_regimes,
    )

    st.markdown('<div class="jl-section">Export centre</div>', unsafe_allow_html=True)
    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "Download investor snapshot",
        data=report_html.encode("utf-8"),
        file_name=f"jlmacro-investor-snapshot-{dashboard_as_of.isoformat()}.html",
        mime="text/html",
        use_container_width=True,
    )
    e2.download_button(
        "Download diligence data room",
        data=data_room_zip,
        file_name=f"jlmacro-data-room-{dashboard_as_of.isoformat()}.zip",
        mime="application/zip",
        use_container_width=True,
    )
    e3.download_button(
        "Download market pulse CSV",
        data=export_market.to_csv(index=False).encode("utf-8"),
        file_name=f"market-pulse-{dashboard_as_of.isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Configured asset universe", expanded=True):
        st.caption(
            "Loaded from config/assets.yaml. Change the investment universe through configuration, "
            "without changing application code."
        )
        st.dataframe(instruments_df, width="stretch", hide_index=True)

    with st.expander("Market snapshot and source lineage"):
        st.dataframe(export_market, width="stretch", hide_index=True)

    with st.expander("Recent immutable audit trail"):
        if audit_df.empty:
            st.info("No audit events have been recorded yet.")
        else:
            st.dataframe(audit_df, width="stretch", hide_index=True)
