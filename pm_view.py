import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="4sight: PM View")


# ===========================================================================
#  SETUP  (imports, palette, shared data, chart helpers)
#  Kept at the bottom of the file on purpose. marimo runs cells by
#  dependency, not by position, so the story above reads top-to-bottom.
# ===========================================================================
@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import altair as alt
    from analysis import (
        load_raw, audit, clean, characterize_signal, signal_effectiveness,
        backtest_curves, market_model, DETREND_WINDOW,
    )

    # one consistent palette so every chart feels like the same deck
    C = {
        "price": "#334155",    # slate, the ETF price
        "signal": "#0ea5e9",   # sky, the vendor signal
        "good": "#10b981",     # emerald, the detrended / real-edge story
        "muted": "#94a3b8",    # grey, the naive / raw version
        "fix": "#ef4444",      # red, corrected data points
        "bench": "#f59e0b",    # amber, buy & hold benchmark
    }

    def themed(c):
        """Shared Altair styling for a clean, deck-ready look."""
        return (
            c.configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#eef2f7", labelColor="#475569",
                            titleColor="#334155", domainColor="#cbd5e1")
            .configure_legend(labelColor="#475569", titleColor="#334155")
            .configure_title(color="#1e293b", fontSize=15, anchor="start")
        )

    return (C, DETREND_WINDOW, themed, alt, audit, backtest_curves,
            characterize_signal, clean, load_raw, market_model, mo, np, pd,
            signal_effectiveness)


@app.cell
def _(audit, backtest_curves, characterize_signal, clean, load_raw, signal_effectiveness):
    # one clean pass through the engine; everything below reads these
    raw = load_raw()
    issues = audit(raw)
    clean_df, corrections = clean(raw)
    ch = characterize_signal(clean_df)
    eff = signal_effectiveness(clean_df)
    curves = backtest_curves(clean_df)
    return ch, clean_df, corrections, curves, eff, issues, raw


# ===========================================================================
#  THE STORY
# ===========================================================================
@app.cell
def _(mo):
    mo.md(
        r"""
        # 4sight Signal: The PM View

        A vendor says their AI ("4sight") forecasts the price of a broad-market ETF.
        Before we wire them any money, two questions, answered with pictures, not jargon:

        **1. Is the data they sent us even trustworthy?**
        **2. Does the signal actually predict the price, or just look like it does?**

        *Everything here is interactive. Drag the sliders, flip the toggles. If a chart
        makes you squint, that's on the chart.*
        """
    )
    return


@app.cell
def _(ch, corrections, eff, mo):
    # executive summary up top, a PM reads top-down
    _raw5 = eff["ic"][5]["pearson"]
    _detr5 = eff["ic_detr"][5]["pearson"]
    mo.callout(
        mo.md(
            f"""
            ### The 20-second version

            - **The data was dirty.** We found and fixed **{corrections['row'].nunique()}
              days** with physically-impossible values (negative prices, 24% one-day jumps,
              highs printed below lows). All logged.
            - **About {ch['price_r2']:.0%} of the signal is just the ETF's own price** copied
              back. Test the raw signal and it looks like a **coin flip** (predictive score
              about {_raw5:+.2f}). A lazy read stops here and calls it junk.
            - **The other {1 - ch['price_r2']:.0%} is real.** Strip out the copied price and the
              signal forecasts the next 1 to 2 weeks with a score of **{_detr5:+.2f}**, and the
              price *alone* can't do that. So it's genuine, independent information.
            - **Verdict: believable, not plug-and-play.** Don't buy yet. Get a longer track
              record and test it against our own signals first.
            """
        ),
        kind="info",
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## 1 · The cleanup: what we caught

        Real markets obey rules: prices are positive, the day's High is the highest price,
        a broad ETF doesn't jump 24% overnight. We flagged every row that broke physics and
        fixed it. The red dots are the days we corrected.
        """
    )
    return


@app.cell
def _(corrections, mo):
    show_fixes = mo.ui.switch(value=True, label="Highlight corrected days")
    show_fixes
    return (show_fixes,)


@app.cell
def _(C, themed, alt, clean_df, corrections, mo, show_fixes):
    _price = clean_df[["Date", "Close"]]
    _line = (
        alt.Chart(_price)
        .mark_line(color=C["price"], strokeWidth=1.3)
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("Close:Q", title="ETF price ($)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("Date:T"), alt.Tooltip("Close:Q", format="$.2f")],
        )
    )

    # one marker per corrected day, tooltip lists what was fixed
    _fix_rows = (
        corrections.groupby("row")
        .agg(date=("date", "first"),
             columns=("column", lambda s: ", ".join(sorted(set(s)))),
             reason=("reason", "first"))
        .reset_index()
    )
    _fix_rows["Date"] = clean_df.loc[_fix_rows["row"], "Date"].values
    _fix_rows["Close"] = clean_df.loc[_fix_rows["row"], "Close"].values
    _dots = (
        alt.Chart(_fix_rows)
        .mark_point(color=C["fix"], size=85, filled=True, opacity=0.9)
        .encode(
            x="Date:T",
            y="Close:Q",
            tooltip=[alt.Tooltip("Date:T", title="Fixed day"),
                     alt.Tooltip("columns:N", title="Columns"),
                     alt.Tooltip("reason:N", title="What we did")],
        )
    )

    _chart = (_line + _dots) if show_fixes.value else _line
    _chart = themed(_chart.properties(height=320, title="ETF price (cleaned): red = days we corrected"))
    mo.vstack([
        mo.ui.altair_chart(_chart),
        mo.md(f"**{len(_fix_rows)} corrected days** out of {len(clean_df):,}. "
              "Hover a red dot to see exactly what was wrong and how we fixed it."),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## 2 · The "tell": the signal mostly copies the price

        Here's the vendor's signal laid over the ETF price. Watch them rise and fall
        together. Most of the "forecast" is really just yesterday's price wearing a hat.
        Flip the toggle to **remove** the copied price, and what's left is the part that
        might actually be worth something.
        """
    )
    return


@app.cell
def _(ch, mo):
    detrend_toggle = mo.ui.switch(
        value=False,
        label=f"Remove the copied price (about {ch['price_r2']:.0%} of the signal)",
    )
    detrend_toggle
    return (detrend_toggle,)


@app.cell
def _(C, DETREND_WINDOW, ch, themed, alt, clean_df, detrend_toggle, mo):
    _d = clean_df[["Date", "Adj Close", "Signal"]].copy()
    if detrend_toggle.value:
        _d["plot_signal"] = _d["Signal"] - _d["Signal"].rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()
        _sig_title = "Signal, copied price removed"
        _msg = ("Now the signal floats around zero and **stops tracking the price**. "
                "*This* leftover is what we actually test for forecasting power.")
    else:
        _d["plot_signal"] = _d["Signal"]
        _sig_title = "Vendor signal (raw)"
        _msg = ("The raw signal hugs the price line. That shared shape is the "
                f"~{ch['price_r2']:.0%} that's just a repackaged copy of the price.")

    _price = (
        alt.Chart(_d).mark_line(color=C["price"], strokeWidth=1.3)
        .encode(x=alt.X("Date:T", title=None),
                y=alt.Y("Adj Close:Q", title="ETF price ($)", scale=alt.Scale(zero=False),
                        axis=alt.Axis(titleColor=C["price"])))
    )
    _sig = (
        alt.Chart(_d).mark_line(color=C["signal"], strokeWidth=1.3, opacity=0.85)
        .encode(x="Date:T",
                y=alt.Y("plot_signal:Q", title=_sig_title,
                        scale=alt.Scale(zero=False), axis=alt.Axis(titleColor=C["signal"])))
    )
    _chart = themed(
        alt.layer(_price, _sig).resolve_scale(y="independent")
        .properties(height=320, title="Signal vs. ETF price")
    )
    mo.vstack([mo.ui.altair_chart(_chart), mo.md(_msg)])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## 3 · The scoreboard: raw vs. real

        The **Information Coefficient** is just *"how well does today's signal line up
        with the next few days' move?"* Zero means a useless coin flip. Around 0.05 is a
        usable quant signal, and 0.20 is strong. Grey is the raw signal. Green is after we
        remove the copied price.
        """
    )
    return


@app.cell
def _(C, themed, alt, eff, mo, pd):
    _rows = []
    for _h, _v in eff["ic"].items():
        _rows.append({"horizon": f"{_h}d", "hz": _h, "version": "Raw signal", "IC": _v["pearson"]})
    for _h, _v in eff["ic_detr"].items():
        _rows.append({"horizon": f"{_h}d", "hz": _h, "version": "Price copy removed", "IC": _v["pearson"]})
    _df = pd.DataFrame(_rows)

    _bars = (
        alt.Chart(_df).mark_bar()
        .encode(
            x=alt.X("version:N", title=None, axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y("IC:Q", title="Information Coefficient"),
            color=alt.Color("version:N",
                            scale=alt.Scale(domain=["Raw signal", "Price copy removed"],
                                            range=[C["muted"], C["good"]]),
                            legend=alt.Legend(title=None, orient="top")),
            column=alt.Column("horizon:N", title="Forecast horizon",
                              sort=["1d", "5d", "10d", "20d"]),
            tooltip=["version", "horizon", alt.Tooltip("IC:Q", format=".3f")],
        )
        .properties(width=95, height=240)
    )
    mo.vstack([
        mo.ui.altair_chart(themed(_bars)),
        mo.md("**Read it left to right:** raw signal hugs zero (coin flip). Remove the "
              "copied price and a real, positive edge appears, strongest at the 1 to 2 week mark."),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## 4 · Kick the tyres yourself

        "Remove the copied price" really just means: *how far is the signal above or below
        its own recent average?* Change the look-back and the forecast horizon and watch
        the score move. The point isn't one magic number. It's that the edge is **stable**
        across sensible settings, which is what makes us believe it's real, not a fluke.
        """
    )
    return


@app.cell
def _(DETREND_WINDOW, mo):
    window = mo.ui.slider(20, 150, value=DETREND_WINDOW, step=10, label="Look-back window (days)", show_value=True)
    horizon = mo.ui.slider(1, 20, value=5, step=1, label="Forecast horizon (days)", show_value=True)
    mo.hstack([window, horizon], justify="start", gap=2)
    return horizon, window


@app.cell
def _(C, themed, alt, clean_df, horizon, mo, pd, window):
    _px = clean_df["Adj Close"]
    _detr = clean_df["Signal"] - clean_df["Signal"].rolling(window.value, min_periods=window.value).mean()
    _fwd = _px.shift(-horizon.value) / _px - 1.0
    _ic = pd.concat([_detr, _fwd], axis=1).dropna().corr().iloc[0, 1]
    _raw_ic = pd.concat([clean_df["Signal"], _fwd], axis=1).dropna().corr().iloc[0, 1]

    _g = pd.DataFrame({"version": ["Raw signal", "Price copy removed"],
                       "IC": [_raw_ic, _ic]})
    _gauge = (
        alt.Chart(_g).mark_bar(height=34)
        .encode(
            x=alt.X("IC:Q", title="Information Coefficient",
                    scale=alt.Scale(domain=[-0.15, 0.35])),
            y=alt.Y("version:N", title=None, sort=["Raw signal", "Price copy removed"]),
            color=alt.Color("version:N",
                            scale=alt.Scale(domain=["Raw signal", "Price copy removed"],
                                            range=[C["muted"], C["good"]]), legend=None),
            tooltip=[alt.Tooltip("IC:Q", format=".3f")],
        ).properties(height=120, title=f"IC at window={window.value}d, horizon={horizon.value}d")
    )
    _rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#cbd5e1").encode(x="x:Q")
    _verdict = ("strong" if _ic > 0.15 else "decent" if _ic > 0.05
                else "weak" if _ic > 0 else "negative")
    mo.vstack([
        mo.ui.altair_chart(themed(_gauge + _rule)),
        mo.md(f"**Detrended score = {_ic:+.3f}** ({_verdict}) vs. raw **{_raw_ic:+.3f}**. "
              "Notice the green bar stays meaningfully positive across most settings while "
              "grey stays pinned near zero."),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## 5 · What it would've made us, and the honest caveat

        A toy strategy: **hold the ETF when the signal, with the copied price removed, is
        positive, and sit in cash otherwise.** No leverage, no shorting. Against simply
        buying and holding.
        """
    )
    return


@app.cell
def _(C, themed, alt, clean_df, curves, eff, market_model, mo):
    # curves come straight from the engine (analysis.backtest_curves), so this
    # chart and the numbers everywhere else use the exact same position logic.
    _eq = curves.melt("Date", var_name="strategy", value_name="growth")

    _chart = (
        alt.Chart(_eq).mark_line(strokeWidth=1.8)
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("growth:Q", title="Growth of $1", scale=alt.Scale(zero=False)),
            color=alt.Color("strategy:N",
                            scale=alt.Scale(domain=["Price copy removed", "Raw signal", "Buy & hold"],
                                            range=[C["good"], C["muted"], C["bench"]]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["strategy", alt.Tooltip("Date:T"), alt.Tooltip("growth:Q", format="$.2f")],
        ).properties(height=320, title="Growth of $1: signal strategies vs. buy & hold")
    )
    _ds = eff["backtest"]["detrended_signal_strategy"]
    _cost = eff["backtest"]["cost_bps"]
    _mm = market_model(clean_df)
    mo.vstack([
        mo.ui.altair_chart(themed(_chart)),
        mo.callout(
            mo.md(
                f"**Yes, both signal strategies beat buy-and-hold here, but don't fall in love.** "
                f"First, costs: this rule flips in and out about **{round(_ds['turnover_per_yr'])} "
                f"times a year**, and at a conservative {_cost:.0f} bps a flip its Sharpe slips from "
                f"**{_ds['sharpe']:.2f} gross to {_ds['sharpe_net']:.2f} net**. Real, not fatal, but "
                f"real. Second, notice the *grey* raw line actually finishes a touch **above** the "
                f"green one. That's not the raw signal being smart. It just stays long almost every "
                f"day in a market that only went up, so it rides the bull (its forecast score is "
                f"about 0). The green line earns its return from real signal, so that's the one to "
                f"trust. Bigger picture: this sample is a single, mostly-up market (2015 to 2020), so "
                f"a pretty equity curve is *encouraging, not proof*, and the edge is stronger in the "
                f"back half than the front. The real test is running this next to our own book."
            ),
            kind="warn",
        ),
        mo.callout(
            mo.md(
                f"**And it isn't just sitting in cash.** The strategy holds less market than "
                f"buy-and-hold (market beta **{_mm['beta_mkt']:.2f}**, and it's invested about "
                f"{_mm['days_invested_pct']:.0%} of the time), so some of the smoother ride is just "
                f"lower exposure. But there's still **{_mm['alpha_annual'] * 100:.0f}% a year of "
                f"alpha** left over on top of that exposure, with a t-stat around "
                f"{_mm['alpha_t_nw']:.1f}. That's genuine timing, not just de-risking. In-sample on "
                f"one path, so suggestive rather than proof, but it's the right thing to check."
            ),
            kind="success",
        ),
    ])
    return


@app.cell
def _(ch, clean_df, corrections, eff, market_model, mo):
    _raw5 = eff["ic"][5]["pearson"]
    _detr5 = eff["ic_detr"][5]["pearson"]
    _mm = market_model(clean_df)
    mo.md(
        f"""
        ---
        ## Bottom line for the desk

        | Question | Answer |
        |---|---|
        | Is the data clean? | **No** → fixed {corrections['row'].nunique()} impossible days, all logged |
        | Is it a risk/vol gauge? | **No** → negatively correlated with volatility |
        | Is it just our own price? | **~{ch['price_r2']:.0%} of it, yes** → that's the dead weight |
        | Does the *rest* forecast? | **Yes** → score {_detr5:+.2f} at 1 to 2 weeks; raw is only {_raw5:+.2f} |
        | Could we replicate it free? | **No** → neither price nor past-return momentum forecast here |
        | Is the backtest just lower risk? | **No** → ~{_mm['alpha_annual'] * 100:.0f}% alpha at beta {_mm['beta_mkt']:.2f} (t≈{_mm['alpha_t_nw']:.1f}), real timing on top |
        | Buy it? | **Not yet** → longer history + test vs. our signals, then negotiate hard |

        *Numbers and cleaning logic all come from `analysis.py`; this view just makes the
        argument visible. Full correction log and the signal-identity tests live there.*
        """
    )
    return


if __name__ == "__main__":
    app.run()
