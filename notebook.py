import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="4sight Signal Review")


@app.cell
def _(mo):
    mo.md(
        r"""
        # 4sight Signal: Data Cleaning & Reality Check

        A vendor sent us a dataset to prove their "4sight" AI forecasts ETF prices.

        Our job, in plain terms:

        1. **Is the data any good?** Find the broken stuff, fix it, show our work.
        2. **Does the signal actually predict the price?** Or is it just a random number in a nice suit?

        > *Rule of the house: if a chart makes you think too hard, the chart is wrong, not you.*

        Use the dropdowns and sliders below. This whole thing is meant to be poked at.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(r"""## Step 1. Meet the raw data (the "before" picture)""")
    return


@app.cell
def _(load_raw, mo):
    raw = load_raw()
    mo.md(
        f"""
        Loaded **{len(raw):,} rows**, from **{raw['Date'].min().date()}**
        to **{raw['Date'].max().date()}**. It's daily price data for a broad-market
        ETF (think S&P 500) plus the vendor's mystery **Signal** column.

        Here's the raw file. Scroll, sort, and filter it like a spreadsheet:
        """
    )
    return (raw,)


@app.cell
def _(mo, raw):
    mo.ui.table(raw, page_size=8, selection=None)
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 2. The data quality audit (spot the garbage)

        We run automatic checks for things that are **physically impossible** in a
        real market. A price can't be negative. The day's High can't be below its Low.
        The price can't jump 24% in a day unless the world is ending (it wasn't).

        Pick a check type to see every row that failed it:
        """
    )
    return


@app.cell
def _(audit, raw):
    issues = audit(raw)
    return (issues,)


@app.cell
def _(issues, mo):
    check_picker = mo.ui.dropdown(
        options=["(all)"] + sorted(issues["check"].unique().tolist()),
        value="(all)",
        label="Filter by check:",
    )
    check_picker
    return (check_picker,)


@app.cell
def _(check_picker, issues, mo):
    _view = issues if check_picker.value == "(all)" else issues[issues["check"] == check_picker.value]
    mo.vstack([
        mo.md(f"**{len(_view)} issue(s)** shown, total found: **{len(issues)}**"),
        mo.ui.table(_view, page_size=10, selection=None),
    ])
    return


@app.cell
def _(issues, mo):
    _counts = issues["check"].value_counts().rename_axis("check").reset_index(name="count")
    mo.vstack([
        mo.md(
            r"""
            ### What we found, in human terms

            | Check | What it means | Believability |
            |---|---|---|
            | `non_positive_price` | A price of **-152**. They'd have to *pay you* to own it. | impossible |
            | `price_spike_outlier` | The price "jumped" **+24%** in one day. Fat-finger typo. | impossible |
            | `high_below_low` | The day's High printed **below** its Low. Ceiling under the floor. | impossible |
            | `low_above_open_close` / `high_below_open_close` | Price traded **outside its own range**. | impossible |
            | `adj_close_too_high` | Adjusted close way above the real close. | suspicious |

            Tally by check type:
            """
        ),
        mo.ui.table(_counts, selection=None),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 3. Fix it, and prove we fixed it

        Our fixes are boring on purpose (boring = trustworthy):

        - **Impossible / fat-finger prices** → replaced with a smooth interpolation from the neighbours.
        - **High/Low that break the rules** → rebuilt as the true max/min of that day's four prices.
        - **Broken Adjusted Close** → rebuilt from the real Close × the stable adjustment ratio.

        Every single change is logged below: old value → new value → why.
        """
    )
    return


@app.cell
def _(clean, raw):
    clean_df, corrections = clean(raw)
    return clean_df, corrections


@app.cell
def _(corrections, mo):
    mo.vstack([
        mo.md(f"### Correction log: **{len(corrections)} fixes applied**"),
        mo.ui.table(corrections, page_size=12, selection=None),
    ])
    return


@app.cell
def _(audit, clean_df, mo):
    _residual = audit(clean_df)
    _ok = len(_residual) == 0
    mo.callout(
        mo.md(
            f"**Re-audit after cleaning: {len(_residual)} remaining issues.** "
            + ("Spotless. The data is now internally consistent."
               if _ok else "Still some left, see table above.")
        ),
        kind="success" if _ok else "warn",
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 4. Wait… what *is* this signal? (reason before you measure)

        The vendor *says* it forecasts price. A strong analyst doesn't take that at
        face value, so we interrogate the thing first. If we'd just assumed "forecast"
        and run one test, we'd have drawn the wrong conclusion (as you'll see).

        So we put three hypotheses on trial:

        - **H1. Is it a risk or volatility gauge?** (VIX-like)
        - **H2. Is it just a repackaging of the ETF's own price?** In other words, are
          they selling us back something we already own?
        - **H3. Does whatever's *left* carry independent forecasting information?**
        """
    )
    return


@app.cell
def _(characterize_signal, clean_df):
    ch = characterize_signal(clean_df)
    return (ch,)


@app.cell
def _(ch, mo, pd):
    _vol = pd.DataFrame(
        [{"window (days)": _w, "corr(signal, realized vol)": round(_v, 3)}
         for _w, _v in ch["vol_corr"].items()]
    )
    mo.vstack([
        mo.md(
            f"""
            ### H1. Volatility gauge? **No.**

            A VIX-like risk gauge would be *strongly positively* correlated with realized
            vol. This one is **negative** at every window, so it is *not* a risk or
            volatility product.
            """
        ),
        mo.ui.table(_vol, selection=None),
    ])
    return


@app.cell
def _(ch, mo):
    mo.callout(
        mo.md(
            f"""
            ### H2. Just repackaged price? **Largely yes, about {ch['price_r2']:.0%} of it.**

            We line the signal up against the ETF's own price and its recent averages, and
            ask how much of the signal that explains. The answer is most of it: the signal
            is **{ch['level_corr']:.0%}** correlated with the price level.

            So a big chunk of the signal is just a copy of the price we already have on our
            screens. That copied part is what makes the *raw* signal look like a coin flip
            in the next step.

            *But about {1 - ch['price_r2']:.0%} of it is something else. That leftover is
            where we go looking.*
            """
        ),
        kind="warn",
    )
    return


@app.cell
def _(ch, mo, pd):
    _ic = pd.DataFrame([
        {"what we test": "Price alone, detrended (free, we own this)", "5-day score": round(ch["ic_detr_price"], 3)},
        {"what we test": "Signal, detrended", "5-day score": round(ch["ic_detr_signal"], 3)},
        {"what we test": "Signal's independent part (not the price)", "5-day score": round(ch["ic_signal_residual"], 3)},
    ])
    mo.vstack([
        mo.md("### H3. Does the *non-price* part forecast? **Yes, and it's the whole story.**"),
        mo.ui.table(_ic, selection=None),
        mo.callout(
            mo.md(
                f"""
                Read these three numbers like a detective:

                - **Price on its own doesn't forecast** here (score = {ch['ic_detr_price']:+.3f}, which
                  is *negative*). So the predictive power is **not** just price mean reversion
                  that we could capture for free.
                - **The signal's independent part forecasts best** (score = {ch['ic_signal_residual']:+.3f}),
                  and it holds up even after we account for the price's own behaviour
                  ({ch['partial_corr_resid']:+.3f}). We carve out that independent part
                  *walk-forward*, using only past data at each point, so it never peeks at the
                  future.

                **Conclusion:** the signal genuinely contains forward-looking information that the
                ETF's own price does **not**. It's not circular, and it's not snake oil. It's just
                buried under a big, distracting copy of the price. *That* is the insight you only get
                by asking what the signal is instead of assuming.
                """
            ),
            kind="success",
        ),
    ])
    return


@app.cell
def _(ch, mo, pd):
    _mom = pd.DataFrame(
        [{"free factor": f"{_w}-day momentum (past return)", "5-day score": round(_v, 3)}
         for _w, _v in ch["mom_ic"].items()]
    )
    mo.vstack([
        mo.md("### H3c. Is the edge just free momentum we could build ourselves?"),
        mo.md(
            "The obvious worry: maybe the 'independent' part is just **trailing-return "
            "momentum**, which we can compute for free from the price alone. So we test it "
            "two ways. First, does plain past-return momentum forecast the next 5 days here? "
            "And second, does the signal still forecast *after* we strip every momentum "
            "look-back out of it?"
        ),
        mo.ui.table(_mom, selection=None),
        mo.callout(
            mo.md(
                f"""
                - **Free momentum is flat** here. Its scores sit at or below zero, so simple
                  past returns do **not** predict the next week.
                - **Strip all of it out and the signal still scores {ch['ic_signal_ex_momentum']:+.3f}**
                  (it was {ch['ic_signal_with_momentum_rows']:+.3f} before). The edge does not
                  come from momentum.

                So the signal is not a repackaged momentum factor either. That is the second
                free thing it could have been, and it isn't.
                """
            ),
            kind="success",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 5. Lead or lag? (does it predict, or just react?)

        One more identity check before we score it. We line up today's signal against the
        price move **k days away**. A real forecaster should be strongest *ahead* of the
        price (k > 0). If it only lights up at or behind k = 0, it's just describing what
        already happened.
        """
    )
    return


@app.cell
def _(alt, clean_df, lead_lag, mo, pd):
    _ll = lead_lag(clean_df)
    _long = pd.concat([
        _ll.assign(series="raw signal", corr=_ll["corr_raw"]),
        _ll.assign(series="detrended signal", corr=_ll["corr_detr"]),
    ])[["lag_k", "kind", "series", "corr"]]
    _long["label"] = _long["lag_k"].astype(str)
    _chart = (
        alt.Chart(_long)
        .mark_bar()
        .encode(
            x=alt.X("label:N", title="lag k (days): negative = past, positive = future",
                    sort=sorted(_long["lag_k"].unique())),
            y=alt.Y("corr:Q", title="correlation with the day's return"),
            color=alt.Color("series:N", legend=alt.Legend(title=None, orient="top")),
            xOffset="series:N",
            tooltip=["lag_k", "series", alt.Tooltip("corr:Q", format=".4f")],
        )
        .properties(height=240)
    )
    _peak = int(_ll.loc[_ll["corr_detr"].idxmax(), "lag_k"])
    mo.vstack([
        mo.ui.altair_chart(_chart),
        mo.md(
            f"""
            Two honest readings here.

            The **raw** signal is flat in every direction. It is barely linked to the past
            *or* the future, because it is mostly just a copy of today's price.

            The **detrended** signal is the one we care about, and it does peak in the
            future (strongest at k = +{_peak} days), so there is genuine lead. But notice it
            also lights up a bit on the *past* side. So it is not a pure crystal ball: it is
            partly riding what just happened and partly anticipating what comes next. The
            forward edge is real, it is just not the whole picture.
            """
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 6. Now the forecast test (and why "raw" looks bad)

        We test the thing that matters: **does today's signal predict where the price
        goes next?**

        The score we use is the *Information Coefficient*, which is just how closely the
        signal today lines up with the return over the next N days.

        - A score near **0** means useless, a coin flip.
        - A score of **0.05** is already a decent quant signal.
        - A score of **0.20** is genuinely strong.
        """
    )
    return


@app.cell
def _(clean_df, signal_effectiveness):
    eff = signal_effectiveness(clean_df)
    return (eff,)


@app.cell
def _(alt, eff, mo, pd):
    _rows = []
    for _h, _v in eff["ic"].items():
        _rows.append({"horizon": _h, "version": "raw signal", "IC": _v["pearson"]})
    for _h, _v in eff["ic_detr"].items():
        _rows.append({"horizon": _h, "version": "detrended signal", "IC": _v["pearson"]})
    _icdf = pd.DataFrame(_rows)
    _chart = (
        alt.Chart(_icdf)
        .mark_bar()
        .encode(
            x=alt.X("version:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("IC:Q", title="Information Coefficient"),
            color=alt.Color("version:N", legend=None),
            column=alt.Column("horizon:N", title="Forecast horizon (trading days)"),
            tooltip=["version", "horizon", alt.Tooltip("IC:Q", format=".3f")],
        )
        .properties(width=80, height=220)
    )
    mo.vstack([
        mo.md("### Information Coefficient: raw vs. detrended signal"),
        mo.ui.altair_chart(_chart),
    ])
    return


@app.cell
def _(eff, mo):
    _raw5 = eff["ic"][5]["pearson"]
    _detr5 = eff["ic_detr"][5]["pearson"]
    _lvl = eff["level_corr"]
    mo.callout(
        mo.md(
            f"""
            ### The twist

            - **Raw signal, 5-day score = {_raw5:+.3f}.** Basically a coin flip. Taken at face
              value, the signal looks useless.
            - **But the signal is {_lvl:.0%} correlated with the *current price level*.** It mostly
              just copies where the price already is, which tells you nothing about the future.
            - **Strip out that copied price (detrend it) and the 5-day score jumps to {_detr5:+.3f}.**
              *That's a strong signal.* The edge was real. It was just buried.

            **Plain-English verdict:** there's a genuine forecasting signal in here, but it does
            **not** work out of the box. You have to do real modelling to dig it out.
            """
        ),
        kind="info",
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 7. Robustness: is the edge real or a fluke?

        A signal that only works in one stretch of history is worthless. So we split the
        timeline in half and re-measure the detrended score in each half on its own. If it's
        positive in *both* halves, the edge is stable, not a one-off lucky fit.
        """
    )
    return


@app.cell
def _(clean_df, mo, pd, split_half_ic):
    _rob = pd.DataFrame([split_half_ic(clean_df, horizon=_h) for _h in (5, 10)])
    _both = bool((_rob[["first_half", "second_half"]] > 0).all(axis=None))
    _h5 = _rob[_rob["horizon"] == 5].iloc[0]
    mo.vstack([
        mo.ui.table(_rob.round(3), selection=None),
        mo.callout(
            mo.md(
                f"""
                The edge is **positive in both halves** at the 1 to 2 week horizon, so it is
                not a single-period fluke. But let's be straight about it: it is **not evenly
                spread**. At the 5-day horizon the score is only {_h5['first_half']:+.3f} in
                the first half and {_h5['second_half']:+.3f} in the second. Most of the
                measured edge is concentrated in the back half of the sample.

                That is enough to call the effect real rather than a lucky fit, but not enough
                to call it rock-steady. It is one more reason we want a longer, fresh
                out-of-sample stretch before trusting it with real money.
                """
                if _both else
                "Mixed across halves, so treat with caution."
            ),
            kind="success" if _both else "warn",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 8. Play with it yourself

        The "detrend" just means: *how much is the signal above or below its own recent
        average?* Drag the sliders to change the look-back window and the forecast horizon,
        and watch the predictive power move.
        """
    )
    return


@app.cell
def _(DETREND_WINDOW, mo):
    window = mo.ui.slider(20, 150, value=DETREND_WINDOW, step=10, label="Detrend look-back (days):", show_value=True)
    horizon = mo.ui.slider(1, 20, value=5, step=1, label="Forecast horizon (days):", show_value=True)
    mo.vstack([window, horizon])
    return horizon, window


@app.cell
def _(clean_df, horizon, mo, pd, window):
    _px = clean_df["Adj Close"]
    _detr = clean_df["Signal"] - clean_df["Signal"].rolling(window.value, min_periods=window.value).mean()
    _fwd = _px.shift(-horizon.value) / _px - 1.0
    _pair = pd.concat([_detr, _fwd], axis=1).dropna()
    _ic = _pair.iloc[:, 0].corr(_pair.iloc[:, 1])
    _raw_ic = pd.concat([clean_df["Signal"], _fwd], axis=1).dropna().corr().iloc[0, 1]
    mo.vstack([
        mo.md(f"**Detrended score** (window={window.value}d, horizon={horizon.value}d): "
              f"# {_ic:+.3f}"),
        mo.md(f"For reference, the **raw** signal score at this horizon is `{_raw_ic:+.3f}`."),
        mo.callout(
            mo.md("Notice the detrended number stays meaningfully positive across most "
                  "settings, while the raw signal stays stuck near zero. That robustness is "
                  "what makes us believe the effect is real and not a lucky fit."),
            kind="neutral",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 9. What would it have made us? (a simple backtest)

        Toy strategy: **hold the ETF when the detrended signal is positive, sit in cash
        otherwise.** No leverage, no shorting, no magic. Compared against just buying and
        holding the ETF.
        """
    )
    return


@app.cell
def _(eff, mo, pd):
    _bt = eff["backtest"]
    _cost = _bt["cost_bps"]

    def _row(_name, _key):
        _s = _bt[_key]
        return {
            "strategy": _name,
            "annual (gross)": f"{_s['annual_return'] * 100:.1f}%",
            "annual (net)": f"{_s['annual_return_net'] * 100:.1f}%",
            "vol": f"{_s['vol'] * 100:.1f}%",
            "Sharpe (gross)": round(_s["sharpe"], 2),
            "Sharpe (net)": round(_s["sharpe_net"], 2),
            "flips/yr": round(_s["turnover_per_yr"]),
        }

    _tbl = pd.DataFrame([
        _row("Raw signal (naive)", "raw_signal_strategy"),
        _row("Detrended signal (the right way)", "detrended_signal_strategy"),
        _row("Buy & hold the ETF", "buy_and_hold"),
    ])
    _ds = _bt["detrended_signal_strategy"]
    mo.vstack([
        mo.ui.table(_tbl, selection=None),
        mo.callout(
            mo.md(
                f"""
                **Sharpe ratio** = return per unit of risk, so higher is better. Three honest
                caveats, because a backtest is the easiest place to fool yourself.

                First, **costs are not optional.** The signal rules flip in and out of the
                market about **{round(_ds['turnover_per_yr'])} times a year**, and every flip
                pays a spread. At a conservative **{_cost:.0f} basis points per flip**, the
                detrended rule's Sharpe drops from **{_ds['sharpe']:.2f} gross to
                {_ds['sharpe_net']:.2f} net**. Push the cost higher and the edge thins out
                fast, so this is a real input we'd want to nail down, not a footnote.

                Second, don't be fooled that the *raw* strategy posts the highest Sharpe. That
                isn't forecasting skill. It's just being long almost every day in a market
                that only went up (its forecast score is about 0). The detrended rule earns
                its return from actual signal, which is why we trust it more.

                Third, a good backtest over *one* bull-market path is encouraging, **not**
                proof. Read the email: we'd want to see this alongside our existing book, on a
                longer history, before believing it.
                """
            ),
            kind="warn",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Step 10. Is the Sharpe real skill, or just less market?

        One honest worry about the backtest: our rule sits in cash about 40% of the time, so
        it naturally carries less risk than buy-and-hold. Maybe the whole Sharpe story is just
        *that*, holding less of the index, not actual timing skill.

        So we run the classic check: regress the strategy's daily return on the ETF's own
        return. The slope (**beta**) is how much market it really holds. The intercept
        (**alpha**) is the return left over *after* accounting for that exposure: the part that
        is genuine timing, not just de-risking.
        """
    )
    return


@app.cell
def _(clean_df, market_model, mo, pd):
    _mm = market_model(clean_df)
    _tbl = pd.DataFrame([
        {"measure": "Alpha (per year)", "value": f"{_mm['alpha_annual'] * 100:.1f}%"},
        {"measure": "Market beta", "value": f"{_mm['beta_mkt']:.2f}"},
        {"measure": "Alpha t-stat (plain)", "value": f"{_mm['alpha_t_ols']:.2f}"},
        {"measure": f"Alpha t-stat (Newey-West, {_mm['nw_lags']}-lag)", "value": f"{_mm['alpha_t_nw']:.2f}"},
        {"measure": "Strategy vol vs market vol", "value": f"{_mm['strat_vol'] * 100:.0f}% vs {_mm['mkt_vol'] * 100:.0f}%"},
    ])
    mo.vstack([
        mo.ui.table(_tbl, selection=None),
        mo.callout(
            mo.md(
                f"""
                **Beta is {_mm['beta_mkt']:.2f}**, well below 1, so yes, the strategy holds less
                market than buy-and-hold. But there's still **{_mm['alpha_annual'] * 100:.1f}% a
                year of alpha** on top of that, with a t-stat of about
                {_mm['alpha_t_nw']:.1f}. A t-stat near 2 means it's *probably* not luck.

                So the answer is: **not just de-risking.** There is real timing skill left over
                after we account for the lower market exposure.

                The honest limit: this is in-sample on one bull-market path, so read the t-stat
                as suggestive, not proof. And it does **not** replace the test that actually
                decides it, which is running this against the signals we already own.
                """
            ),
            kind="success",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Bottom line for the desk

        | Question | Answer |
        |---|---|
        | Is the data clean? | **No.** 27 impossible values, all fixed and all logged. |
        | What is the signal? | About 60% the ETF's own price, about 40% something independent. **Not** a vol gauge. |
        | Does the raw signal forecast? | **No.** Score near 0, a coin flip (the copied price drowns it). |
        | Is there *real, independent* signal? | **Yes.** The non-price part forecasts (score about 0.2 to 0.29), and price alone does **not**. |
        | Can we use it as-is? | **No.** We'd extract the signal ourselves. |
        | Should we buy it? | **Maybe.** It's believable. Next: longer history plus a test against our own signals. |

        *Cleaning logic lives in `analysis.py`; this notebook just makes it clickable.*
        """
    )
    return


@app.cell
def _():
    # --- imports & shared analysis engine (kept at the bottom, marimo runs by dependency) ---
    import marimo as mo
    import pandas as pd
    import altair as alt
    from analysis import (
        load_raw, audit, clean, characterize_signal, signal_effectiveness,
        lead_lag, split_half_ic, market_model, DETREND_WINDOW,
    )
    return (
        DETREND_WINDOW, alt, audit, characterize_signal, clean, lead_lag,
        load_raw, market_model, mo, pd, signal_effectiveness, split_half_ic,
    )


if __name__ == "__main__":
    app.run()
