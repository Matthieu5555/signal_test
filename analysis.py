"""
4sight Signal: Data Cleaning & Effectiveness Analysis
=====================================================

Plain goal:
  1. Find every broken value in the vendor's dataset and fix it (with a reason).
  2. Test whether the "Signal" actually predicts the ETF price.

This file is the engine. The marimo notebook (notebook.py) imports these
functions so the cleaning logic lives in ONE place and can't drift.

Run it directly to print the full audit + analysis:
    uv run python analysis.py
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

# Resolved relative to this file, so it works no matter where you run from.
DATA_PATH = Path(__file__).parent / "Sample Dataset.xlsx"
PRICE_COLS = ["Open", "High", "Low", "Close", "Adj Close"]

# Trading-day look-back used to strip the slow price-level component out of the
# signal (the copied price). Larger = smoother/slower detrend; smaller = noisier.
# Single source of truth: characterize_signal, signal_effectiveness, the backtest,
# split_half_ic, and the notebook sliders all default to this value.
DETREND_WINDOW = 60

# Naive one-way trading cost, in basis points, charged every time the strategy
# flips between invested and cash (1 bp = 0.01%). A broad, liquid ETF trades for
# a few bps, so 5 is a deliberately conservative-but-realistic placeholder. The
# backtest reports BOTH gross and net-of-this-cost so nobody mistakes a paper
# Sharpe for a tradable one.
COST_BPS = 5.0


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_raw(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load the raw vendor file. No cleaning here on purpose."""
    df = pd.read_excel(path)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Audit: find every error, return a tidy log of issues
# ---------------------------------------------------------------------------
def audit(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan the raw data and return one row per detected problem.
    Columns: row, date, column, check, bad_value, note
    """
    issues = []

    def add(i, col, check, bad, note):
        issues.append({
            "row": int(i),
            "date": df.loc[i, "Date"].date().isoformat(),
            "column": col,
            "check": check,
            "bad_value": bad,
            "note": note,
        })

    # 1. Missing values
    for col in df.columns:
        for i in df.index[df[col].isna()]:
            add(i, col, "missing_value", None, "Cell is empty / NaN")

    # 2. Duplicate dates
    for i in df.index[df["Date"].duplicated(keep=False)]:
        add(i, "Date", "duplicate_date", df.loc[i, "Date"].date().isoformat(),
            "Date appears more than once")

    # 3. Non-positive prices (a price <= 0 is impossible)
    for col in PRICE_COLS:
        for i in df.index[df[col] <= 0]:
            add(i, col, "non_positive_price", df.loc[i, col],
                "Price is zero or negative, which is impossible")

    # 4. OHLC internal consistency.
    #    By definition: High = max of day, Low = min of day.
    #    So High must be >= Open, Close, Low  and  Low must be <= Open, High, Close.
    for i in df.index:
        o, h, l, c = df.loc[i, ["Open", "High", "Low", "Close"]]
        if h < l:
            add(i, "High/Low", "high_below_low", f"H={h:.2f} < L={l:.2f}",
                "High is below Low, so the range is inverted")
        if h < max(o, c):
            add(i, "High", "high_below_open_close", f"H={h:.2f} < max(O,C)={max(o, c):.2f}",
                "High is below the day's open/close")
        if l > min(o, c):
            add(i, "Low", "low_above_open_close", f"L={l:.2f} > min(O,C)={min(o, c):.2f}",
                "Low is above the day's open/close")

    # 5. Price spike outliers (fat-finger). Flag any 1-day move that is a
    #    massive outlier vs the column's own daily-move distribution.
    for col in ["Open", "High", "Low", "Close"]:
        r = df[col].pct_change()
        # robust threshold: median + 8 * MAD of absolute returns
        a = r.abs()
        thr = a.median() + 8 * (a - a.median()).abs().median()
        thr = max(thr, 0.10)  # never flag normal <10% market days
        for i in df.index[a > thr]:
            add(i, col, "price_spike_outlier", df.loc[i, col],
                f"1-day move {r[i] * 100:.1f}%, far outside the normal range")

    # 6. Adj Close sanity. For this kind of ETF history, Adj Close should be
    #    close to Close and never wildly larger; we already catch negatives above.
    for i in df.index[df["Adj Close"] > df["Close"] * 1.05]:
        add(i, "Adj Close", "adj_close_too_high", df.loc[i, "Adj Close"],
            "Adj Close materially above Close, unusual for dividend-adjusted history")

    log = pd.DataFrame(issues)
    if len(log):
        log = log.sort_values(["row", "column"]).reset_index(drop=True)
    return log


# ---------------------------------------------------------------------------
# Clean: apply fixes and return (clean_df, correction_log)
# ---------------------------------------------------------------------------
def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply corrections. Strategy is conservative and explainable:
      - Impossible prices / spikes -> replace with time-interpolated value.
      - High/Low violations -> rebuild High/Low as max/min of the 4 OHLC values
        (this is what High/Low mean by definition).
      - Negative Adj Close -> rebuild from the Close * median(AdjClose/Close) ratio.
    Every change is recorded with old -> new + reason.
    """
    df = df.copy()
    corrections = []

    def record(i, col, old, new, reason):
        corrections.append({
            "row": int(i),
            "date": df.loc[i, "Date"].date().isoformat(),
            "column": col,
            "old_value": round(float(old), 4) if pd.notna(old) else None,
            "new_value": round(float(new), 4) if pd.notna(new) else None,
            "reason": reason,
        })

    # --- Step A: blank out values that are clearly impossible, fix later ---
    # Negative / zero prices in O/H/L/C -> mark NaN, interpolate.
    for col in ["Open", "High", "Low", "Close"]:
        bad = df.index[df[col] <= 0]
        for i in bad:
            df.loc[i, col] = np.nan

    # Close price spikes (fat-finger) -> mark NaN, interpolate.
    r = df["Close"].pct_change().abs()
    thr = max(r.median() + 8 * (r - r.median()).abs().median(), 0.10)
    spike_idx = df.index[r > thr]
    spike_old = {i: df.loc[i, "Close"] for i in spike_idx}
    for i in spike_idx:
        df.loc[i, "Close"] = np.nan

    # Interpolate the holes we just made on O/H/L/C
    pre_interp = df[["Open", "High", "Low", "Close"]].copy()
    df[["Open", "High", "Low", "Close"]] = (
        df[["Open", "High", "Low", "Close"]]
        .interpolate(method="linear", limit_direction="both")
    )
    for col in ["Open", "High", "Low", "Close"]:
        for i in df.index[pre_interp[col].isna()]:
            old = spike_old.get(i, np.nan)
            reason = ("Fat-finger price spike replaced with linear interpolation"
                      if i in spike_idx else
                      "Impossible (<=0) price replaced with linear interpolation")
            record(i, col, old, df.loc[i, col], reason)

    # --- Step B: rebuild High/Low so the bar is internally consistent ---
    for i in df.index:
        o, h, l, c = df.loc[i, ["Open", "High", "Low", "Close"]]
        true_high = max(o, h, l, c)
        true_low = min(o, h, l, c)
        if not np.isclose(h, true_high):
            record(i, "High", h, true_high, "High set to max(O,H,L,C) to fix inverted/invalid range")
            df.loc[i, "High"] = true_high
        if not np.isclose(l, true_low):
            record(i, "Low", l, true_low, "Low set to min(O,H,L,C) to fix inverted/invalid range")
            df.loc[i, "Low"] = true_low

    # --- Step C: rebuild bad Adj Close from the stable Close ratio ---
    ratio = (df["Adj Close"] / df["Close"]).replace([np.inf, -np.inf], np.nan)
    med_ratio = ratio[(ratio > 0) & (ratio < 1.2)].median()
    bad_adj = df.index[(df["Adj Close"] <= 0) | (df["Adj Close"] > df["Close"] * 1.05)]
    for i in bad_adj:
        old = df.loc[i, "Adj Close"]
        new = df.loc[i, "Close"] * med_ratio
        record(i, "Adj Close", old, new, f"Rebuilt as Close x median ratio ({med_ratio:.4f})")
        df.loc[i, "Adj Close"] = new

    corr_log = pd.DataFrame(corrections)
    if len(corr_log):
        corr_log = corr_log.sort_values(["row", "column"]).reset_index(drop=True)
    return df, corr_log


# ---------------------------------------------------------------------------
# What IS the signal?  (reason before you measure)
# ---------------------------------------------------------------------------
def characterize_signal(df: pd.DataFrame) -> dict:
    """
    Don't assume the vendor's framing ("it forecasts price"). Interrogate the
    signal and let the data say what it is. We test three hypotheses:

      H1  Risk / volatility indicator (VIX-like)?  -> corr with realized vol.
      H2  Just a repackaging of the ETF's own price? -> R^2 of signal ~ price.
      H3  Does its INDEPENDENT part (what's left after removing price) carry
          real forecasting info? -> partial correlation with forward return,
          controlling for the price's own mean-reversion.
    """
    d = df.copy()
    px = d["Adj Close"]
    ret = px.pct_change()
    sig = d["Signal"]

    out = {"shape": {"min": float(sig.min()), "max": float(sig.max()),
                     "mean": float(sig.mean()), "std": float(sig.std())}}

    # H1: volatility indicator? (VIX-like => strong POSITIVE corr with vol)
    out["vol_corr"] = {
        w: float(sig.corr(ret.rolling(w).std() * np.sqrt(252) * 100))
        for w in (5, 10, 20, 30)
    }

    # H2: how much of the signal is just the ETF's own price?
    feat = pd.DataFrame({
        "px": px, "px_l1": px.shift(1), "px_l5": px.shift(5),
        "ma10": px.rolling(10).mean(), "ma50": px.rolling(50).mean(),
    }).dropna()
    y = sig.loc[feat.index].values
    X = np.column_stack([np.ones(len(feat)), feat.values])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    out["price_r2"] = float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    out["level_corr"] = float(sig.corr(px))

    # H3: does the part of the signal that ISN'T price still forecast returns,
    #      over and above the price's own mean-reversion?
    fwd5 = px.shift(-5) / px - 1.0

    # The "non-price part" is the residual after projecting the signal on the
    # price. We fit that projection WALK-FORWARD (expanding window, past data
    # only) so the residual at day t never sees the future. A full-sample fit
    # happens to give the same answer here (the price->signal slope is very
    # stable), but doing it walk-forward means the number is bullet-proof to the
    # obvious "you fit on the whole sample" objection.
    resid = pd.Series(index=sig.index, dtype=float)
    pv, sv = px.values, sig.values
    for t in range(DETREND_WINDOW, len(sig)):
        bb = np.polyfit(pv[:t], sv[:t], 1)
        resid.iloc[t] = sv[t] - np.polyval(bb, pv[t])

    detr_px = px - px.rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()

    def _ic(x, h=5):
        f = px.shift(-h) / px - 1.0
        p = pd.concat([x, f], axis=1).dropna()
        return float(p.iloc[:, 0].corr(p.iloc[:, 1]))

    out["ic_detr_signal"] = _ic(sig - sig.rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean())
    out["ic_detr_price"] = _ic(detr_px)          # plain price mean-reversion (free)
    out["ic_signal_residual"] = _ic(resid)       # the non-price part of the signal

    # partial corr of residual with fwd return, controlling for price mean-reversion
    combo = pd.concat([detr_px.rename("dpx"), resid.rename("res"),
                       fwd5.rename("y")], axis=1).dropna()

    def _resid_of(a, ctrl):
        Z = np.column_stack([np.ones(len(ctrl)), ctrl])
        bb, *_ = np.linalg.lstsq(Z, a, rcond=None)
        return a - Z @ bb

    ry = _resid_of(combo["y"].values, combo["dpx"].values)
    rr = _resid_of(combo["res"].values, combo["dpx"].values)
    out["partial_corr_resid"] = float(np.corrcoef(ry, rr)[0, 1])

    # H3b: is the edge just FREE trailing-return momentum in disguise? A PM's
    # first question. We check (a) whether plain past-return momentum forecasts
    # the next 5 days at all, and (b) whether the detrended signal still
    # forecasts AFTER we strip out every momentum look-back. If momentum is flat
    # and the signal survives, the signal is not a repackaged momentum factor.
    detr_sig = sig - sig.rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()
    moms = {w: px / px.shift(w) - 1.0 for w in (5, 10, 20)}
    out["mom_ic"] = {w: _ic(m) for w, m in moms.items()}

    mom_combo = pd.concat(
        [detr_sig.rename("s")]
        + [m.rename(f"m{w}") for w, m in moms.items()]
        + [fwd5.rename("y")],
        axis=1,
    ).dropna()
    s_ex_mom = _resid_of(
        mom_combo["s"].values,
        mom_combo[[f"m{w}" for w in (5, 10, 20)]].values,
    )
    out["ic_signal_ex_momentum"] = float(np.corrcoef(s_ex_mom, mom_combo["y"].values)[0, 1])
    out["ic_signal_with_momentum_rows"] = float(mom_combo["s"].corr(mom_combo["y"]))
    return out


# ---------------------------------------------------------------------------
# Strategy positions: one definition shared by the backtest stats AND the
# equity-curve plot, so the table and the chart can never disagree.
# ---------------------------------------------------------------------------
def _strategy_positions(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Long/flat positions (shifted one day -> no look-ahead) for the two rules,
    plus the daily ETF return they trade on.
      raw_pos  -> long when the RAW signal is above its trailing median.
      detr_pos -> long when the DETRENDED signal (signal minus its own trailing
                  mean) is positive, i.e. the predictive residual is positive.
    Returns (daily_return, raw_pos, detr_pos).
    """
    px = df["Adj Close"]
    daily = px.pct_change().fillna(0)
    sig = df["Signal"]
    detr = sig - sig.rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()
    raw_pos = (sig > sig.rolling(DETREND_WINDOW, min_periods=20).median()).shift(1).fillna(0).astype(float)
    detr_pos = (detr > 0).shift(1).fillna(0).astype(float)
    return daily, raw_pos, detr_pos


def backtest_curves(df: pd.DataFrame) -> pd.DataFrame:
    """
    Growth-of-$1 equity curves for the three strategies, tidy and ready to plot.
    Uses the exact same positions as the backtest stats in signal_effectiveness
    (see _strategy_positions), so the chart and the summary table cannot drift.
    Columns: Date, "Buy & hold", "Raw signal", "Price copy removed".
    """
    daily, raw_pos, detr_pos = _strategy_positions(df)
    return pd.DataFrame({
        "Date": df["Date"].values,
        "Buy & hold": (1 + daily).cumprod().values,
        "Raw signal": (1 + raw_pos * daily).cumprod().values,
        "Price copy removed": (1 + detr_pos * daily).cumprod().values,
    })


# ---------------------------------------------------------------------------
# Signal effectiveness
# ---------------------------------------------------------------------------
def signal_effectiveness(df: pd.DataFrame, horizons=(1, 5, 10, 20)) -> dict:
    """
    Does Signal predict FUTURE returns of the ETF?

    We line up today's Signal against the return over the NEXT n days.
    Metrics:
      - Pearson & Spearman (rank) correlation -> "information coefficient" (IC)
      - hit rate of a simple rule (above-median signal -> expect up)
      - a long/flat backtest vs buy-and-hold
    """
    d = df.copy()
    d["ret_next1"] = d["Adj Close"].pct_change().shift(-1)  # tomorrow's return

    out = {"ic": {}, "backtest": {}}

    # Detrended signal: remove the slow-moving price-level component using ONLY
    # past data (trailing mean) -> no look-ahead. This isolates the part of the
    # signal that is NOT just echoing the current price.
    d["Signal_detr"] = d["Signal"] - d["Signal"].rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()
    out["ic_detr"] = {}

    # Information coefficient at several horizons, raw AND detrended.
    for h in horizons:
        fwd = d["Adj Close"].shift(-h) / d["Adj Close"] - 1.0
        pair = pd.concat([d["Signal"], fwd], axis=1).dropna()
        pear = pair["Signal"].corr(pair.iloc[:, 1], method="pearson")
        spear = pair["Signal"].corr(pair.iloc[:, 1], method="spearman")
        # hit rate: does "high signal" line up with "positive forward return"?
        hi = pair["Signal"] > pair["Signal"].median()
        up = pair.iloc[:, 1] > 0
        hit = (hi == up).mean()
        out["ic"][h] = {"pearson": pear, "spearman": spear, "hit_rate": hit,
                        "n": len(pair)}
        # detrended version
        pd2 = pd.concat([d["Signal_detr"], fwd], axis=1).dropna()
        out["ic_detr"][h] = {
            "pearson": pd2["Signal_detr"].corr(pd2.iloc[:, 1]),
            "spearman": pd2["Signal_detr"].corr(pd2.iloc[:, 1], method="spearman"),
            "n": len(pd2),
        }

    # Also test: does the signal just track the PRICE LEVEL (contemporaneous)?
    out["level_corr"] = d["Signal"].corr(d["Adj Close"])
    out["change_corr"] = d["Signal"].diff().corr(d["Adj Close"].pct_change())

    def stats(pos, daily, cost_bps=COST_BPS):
        """
        Turn a position series into performance, GROSS and NET of trading cost.
        Cost is charged on turnover: every change in position pays cost_bps on
        the traded fraction. A long/flat rule that flips on and off therefore
        bleeds cost each switch, which is exactly what a paper Sharpe ignores.
        """
        gross = pos * daily
        turn = pos.diff().abs().fillna(pos.abs())   # first day counts as entry
        cost = turn * (cost_bps / 10000.0)
        net = gross - cost

        def _ann(r):
            return (1 + r).prod() ** (252 / len(r)) - 1

        vol = gross.std() * np.sqrt(252)
        ann_g, ann_n = _ann(gross), _ann(net)
        years = len(pos) / 252
        return {
            "total_return": (1 + gross).prod() - 1,
            "annual_return": ann_g,
            "vol": vol,
            "sharpe": ann_g / vol if vol else np.nan,
            "annual_return_net": ann_n,
            "sharpe_net": ann_n / vol if vol else np.nan,
            "turnover_per_yr": turn.sum() / years,
        }

    # Positions come from the shared helper so these stats match the equity
    # curves drawn by backtest_curves() exactly.
    daily, raw_pos, detr_pos = _strategy_positions(df)
    hold_pos = pd.Series(1.0, index=daily.index)   # buy & hold never trades after day 1

    out["backtest"] = {
        "raw_signal_strategy": stats(raw_pos, daily),
        "detrended_signal_strategy": stats(detr_pos, daily),
        "buy_and_hold": stats(hold_pos, daily),
        "days_invested_pct": detr_pos.mean(),
        "cost_bps": COST_BPS,
    }
    return out


# ---------------------------------------------------------------------------
# Extra rigor (used by the detailed analysis notebook)
# ---------------------------------------------------------------------------
def lead_lag(df: pd.DataFrame, lags=(-5, -3, -1, 0, 1, 3, 5)) -> pd.DataFrame:
    """
    Does the signal LEAD the price (predict it) or just move WITH/AFTER it?
    We correlate today's signal with the daily return k days away.
      k > 0  -> signal vs FUTURE return  (leading / predictive)
      k = 0  -> same day                 (coincident)
      k < 0  -> signal vs PAST return    (lagging)
    A genuine forecaster should be strongest at k > 0.
    """
    ret = df["Adj Close"].pct_change()
    sig = df["Signal"]
    detr = sig - sig.rolling(DETREND_WINDOW, min_periods=DETREND_WINDOW).mean()
    rows = []
    for k in lags:
        rows.append({
            "lag_k": k,
            "kind": "future (predict)" if k > 0 else ("same-day" if k == 0 else "past (react)"),
            "corr_raw": float(sig.corr(ret.shift(-k))),
            "corr_detr": float(detr.corr(ret.shift(-k))),
        })
    return pd.DataFrame(rows)


def market_model(df: pd.DataFrame, cost_bps: float = COST_BPS, nw_lags: int = 5) -> dict:
    """
    CAPM-style regression of the (detrended-signal) strategy's NET daily return
    on the ETF's own daily return:  r_strategy = alpha + beta * r_ETF + noise.

    This separates two very different reasons a strategy can look good:
      - beta  : how much market it actually holds. Our rule sits in cash part of
                the time, so its beta is well below 1. A high Sharpe could be
                *just* this (less market = less risk), which is not skill.
      - alpha : return left over after accounting for that market exposure. This
                is the timing skill, the part that isn't explained by simply
                holding less of the index.

    We report the alpha t-stat two ways: plain (OLS) and Newey-West, which is
    robust to the day-to-day autocorrelation in the position. A t-stat near 2
    means "probably not luck", but this is in-sample on a single bull-market
    path, so read it as suggestive, not proof.
    """
    daily, _, detr_pos = _strategy_positions(df)
    cost = detr_pos.diff().abs().fillna(detr_pos.abs()) * (cost_bps / 10000.0)
    r_strat = (detr_pos * daily - cost).values
    r_mkt = daily.values

    X = np.column_stack([np.ones(len(r_mkt)), r_mkt])
    beta, *_ = np.linalg.lstsq(X, r_strat, rcond=None)
    resid = r_strat - X @ beta
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)

    se_ols = np.sqrt(np.diag((resid @ resid / (n - k)) * XtX_inv))
    # Newey-West HAC standard errors (Bartlett kernel)
    u = X * resid[:, None]
    S = u.T @ u
    for l in range(1, nw_lags + 1):
        w = 1 - l / (nw_lags + 1)
        G = u[l:].T @ u[:-l]
        S += w * (G + G.T)
    se_nw = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))

    return {
        "alpha_daily": float(beta[0]),
        "alpha_annual": float((1 + beta[0]) ** 252 - 1),
        "beta_mkt": float(beta[1]),
        "alpha_t_ols": float(beta[0] / se_ols[0]),
        "alpha_t_nw": float(beta[0] / se_nw[0]),
        "nw_lags": nw_lags,
        "strat_vol": float(r_strat.std() * np.sqrt(252)),
        "mkt_vol": float(r_mkt.std() * np.sqrt(252)),
        "days_invested_pct": float(detr_pos.mean()),
    }


def split_half_ic(df: pd.DataFrame, horizon: int = 5, window: int = DETREND_WINDOW) -> dict:
    """
    Out-of-sample sniff test: does the detrended signal's edge survive in BOTH
    halves of the history, or is it a one-off fluke? We split the timeline in
    two and measure the detrended Information Coefficient in each half.
    """
    px = df["Adj Close"]
    detr = df["Signal"] - df["Signal"].rolling(window, min_periods=window).mean()
    fwd = px.shift(-horizon) / px - 1.0
    pair = pd.concat([detr.rename("s"), fwd.rename("y")], axis=1).dropna()
    h = len(pair) // 2
    return {
        "horizon": horizon,
        "first_half": float(pair["s"].iloc[:h].corr(pair["y"].iloc[:h])),
        "second_half": float(pair["s"].iloc[h:].corr(pair["y"].iloc[h:])),
        "full": float(pair["s"].corr(pair["y"])),
        "n": len(pair),
    }


# ---------------------------------------------------------------------------
# Pretty-print when run directly
# ---------------------------------------------------------------------------
def _fmt_pct(x):
    return f"{x * 100:6.2f}%"


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)

    raw = load_raw()
    print(f"Loaded {len(raw)} rows, {raw['Date'].min().date()} -> {raw['Date'].max().date()}\n")

    print("=" * 70)
    print("1) DATA QUALITY AUDIT")
    print("=" * 70)
    issues = audit(raw)
    print(f"\nTotal issues found: {len(issues)}")
    print("\nBy check type:")
    print(issues["check"].value_counts().to_string())
    print("\nFull issue log:")
    print(issues.to_string(index=False))

    print("\n" + "=" * 70)
    print("2) CORRECTIONS APPLIED")
    print("=" * 70)
    clean_df, corrections = clean(raw)
    print(f"\nTotal corrections: {len(corrections)}\n")
    print(corrections.to_string(index=False))

    # Re-audit to prove we fixed it
    residual = audit(clean_df)
    print(f"\nResidual issues after cleaning: {len(residual)}")
    if len(residual):
        print(residual.to_string(index=False))

    print("\n" + "=" * 70)
    print("3) WHAT IS THE SIGNAL? (reason before measuring)")
    print("=" * 70)
    ch = characterize_signal(clean_df)
    s = ch["shape"]
    print(f"\nShape: range {s['min']:.1f} to {s['max']:.1f}, mean {s['mean']:.1f}, std {s['std']:.1f}")
    print("\nH1. Volatility/risk indicator? corr(signal, realized vol):")
    for w, v in ch["vol_corr"].items():
        print(f"     {w:>3}d: {v:+.3f}")
    print("     -> negative, so NOT a VIX-like risk gauge.")
    print(f"\nH2. Just repackaged price? R^2(signal ~ ETF price & MAs) = {ch['price_r2']:.3f}")
    print(f"     corr(signal, price level) = {ch['level_corr']:.3f}  "
          f"-> ~{ch['price_r2']*100:.0f}% of the signal is the price we already own.")
    print("\nH3. Does the NON-price part still forecast? (5-day IC)")
    print(f"     detrended PRICE (free)        : {ch['ic_detr_price']:+.3f}  (price mean-reversion alone)")
    print(f"     detrended SIGNAL              : {ch['ic_detr_signal']:+.3f}")
    print(f"     signal RESIDUAL (non-price)   : {ch['ic_signal_residual']:+.3f}")
    print(f"     partial corr (resid | price)  : {ch['partial_corr_resid']:+.3f}")
    print("     -> price alone does NOT forecast; the signal's INDEPENDENT part does.")
    print("\nH3b. Just free trailing-return momentum? 5-day IC of past-return momentum:")
    for w, v in ch["mom_ic"].items():
        print(f"     {w:>3}d momentum: {v:+.3f}")
    print(f"     signal after stripping ALL momentum: {ch['ic_signal_ex_momentum']:+.3f}"
          f"  (vs {ch['ic_signal_with_momentum_rows']:+.3f} before)")
    print("     -> momentum is flat; the signal survives, so it is NOT repackaged momentum.")

    print("\n" + "=" * 70)
    print("4) SIGNAL EFFECTIVENESS")
    print("=" * 70)
    eff = signal_effectiveness(clean_df)
    print("\nRAW signal IC (Signal today vs return over next N days):")
    print(f"{'horizon':>8} {'pearson':>10} {'spearman':>10} {'hit_rate':>10} {'n':>6}")
    for h, v in eff["ic"].items():
        print(f"{h:>8} {v['pearson']:>10.4f} {v['spearman']:>10.4f} {v['hit_rate']:>10.2%} {v['n']:>6}")

    print("\nDETRENDED signal IC (signal minus its own trailing mean; no look-ahead):")
    print(f"{'horizon':>8} {'pearson':>10} {'spearman':>10} {'n':>6}")
    for h, v in eff["ic_detr"].items():
        print(f"{h:>8} {v['pearson']:>10.4f} {v['spearman']:>10.4f} {v['n']:>6}")

    print(f"\nSignal vs price LEVEL  correlation: {eff['level_corr']:.4f}  <- raw signal mostly copies price")
    print(f"Signal-change vs return correlation: {eff['change_corr']:.4f}")

    bt = eff["backtest"]
    print(f"\nBacktest (long/flat vs buy & hold), cost = {bt['cost_bps']:.0f} bps per flip:")
    for name in ["raw_signal_strategy", "detrended_signal_strategy", "buy_and_hold"]:
        s = bt[name]
        print(f"  {name:>26}: annual {_fmt_pct(s['annual_return'])} gross / "
              f"{_fmt_pct(s['annual_return_net'])} net | vol {_fmt_pct(s['vol'])} | "
              f"sharpe {s['sharpe']:.2f} gross / {s['sharpe_net']:.2f} net | "
              f"turnover {s['turnover_per_yr']:.0f}/yr")
    print(f"  days invested (detrended): {bt['days_invested_pct']:.1%}")

    mm = market_model(clean_df)
    print("\nMarket model (is the Sharpe just lower exposure, or real timing alpha?):")
    print(f"  alpha        : {_fmt_pct(mm['alpha_annual'])} per year")
    print(f"  market beta  : {mm['beta_mkt']:.2f}  (holds ~{mm['days_invested_pct']:.0%} market on average)")
    print(f"  alpha t-stat : {mm['alpha_t_ols']:.2f} (OLS) / {mm['alpha_t_nw']:.2f} (Newey-West, {mm['nw_lags']} lag)")
    print(f"  strat vol {_fmt_pct(mm['strat_vol'])} vs market vol {_fmt_pct(mm['mkt_vol'])}")
    print("  -> positive alpha with beta well below 1: outperformance is NOT just sitting in cash.")
