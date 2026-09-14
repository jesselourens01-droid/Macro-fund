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

from jlmacro.backtest.engine import run_backtest
from jlmacro.backtest.monte_carlo import bootstrap_terminal_nav
from jlmacro.config import get_settings, load_yaml_config
from jlmacro.database.session import session_scope
from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Portfolio, Trade
from jlmacro.models.signals import compute_investment_score
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

(
    tab_prices,
    tab_macro,
    tab_regime,
    tab_signals,
    tab_portfolio,
    tab_risk,
    tab_backtest,
    tab_journal,
    tab_universe,
) = st.tabs(
    [
        "Prices",
        "Macro Indicators",
        "Macro Regime",
        "Signals",
        "Portfolio",
        "Risk",
        "Backtest",
        "Trade Journal",
        "Asset Universe",
    ]
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

with tab_portfolio:
    st.subheader("Portfolio construction")
    st.caption(
        "Point-in-time covariance -> weighting (inverse-vol or equal-risk-contribution) "
        "-> scaled to the fund's target volatility (config/risk_limits.yaml). This is a "
        "proposal, not an executed position - there is no persisted Position/Trade table "
        "yet (Phase 8), and none of config/risk_limits.yaml's concentration/drawdown "
        "limits are enforced here (Phase 6's risk engine)."
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

            m1, m2, m3 = st.columns(3)
            m1.metric("Gross leverage", f"{scaled.gross_leverage:.2f}x")
            m2.metric("Portfolio volatility", f"{scaled.portfolio_volatility:.1%}")
            m3.metric("Instruments", len(portfolio_symbols))

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
        "risk_budget = NAV x allowed_risk_percentage (config/risk_limits.yaml "
        "position_risk, keyed by risk_units from the Phase 4 composite score's action "
        "band); position size = risk_budget / ATR-based stop distance."
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
        "with actual authority over risk. Uses the same instruments/weights selected "
        "in the Portfolio tab above; nothing here is persisted or auto-enforced yet "
        "(there is no Position/Trade table until Phase 8)."
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
            "mark. There is no persisted NAV history yet (Phase 9), so this reads a "
            "hypothetical current drawdown you set below."
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
        "Replays the signal engine (Phase 4) and portfolio construction (Phase 5) "
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

            mcol1, mcol2, mcol3 = st.columns(3)
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

with tab_universe:
    st.subheader("Configured asset universe")
    st.caption(
        "Loaded from config/assets.yaml - edit that file to change the universe, no code changes needed."
    )
    st.dataframe(instruments_df, width="stretch")
