"""Dual momentum: each month hold the single strongest asset, or cash if nothing is going up.

  relative momentum: rank the assets by their return over the last `lookback` days, pick the best
  absolute momentum: only hold it if that return is positive; otherwise sit in cash

Rebalances once a month (last trading day), so it trades rarely and costs almost nothing.
"""
import datetime as dt

import numpy as np
import pandas as pd

from src.backtest.portfolio import load_ohlcv, closes, portfolio_returns, summary

UNIVERSE = ["SPY", "EFA", "TLT", "GLD"]   # US stocks, international stocks, long bonds, gold
LOOKBACKS = [63, 126, 189, 252]           # ~3, 6, 9, 12 months of trading days


def dual_momentum_weights(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    mom = close.pct_change(lookback).fillna(-np.inf)   # no history yet -> never picked
    best = mom.idxmax(axis=1)                       # strongest asset each day
    best_ret = mom.max(axis=1)

    # 1.0 in the best asset's column, but only on days its momentum is positive
    is_best = pd.DataFrame(close.columns.values == best.values[:, None], index=close.index, columns=close.columns)
    weights = is_best.mul(best_ret > 0, axis=0).astype(float)

    # only change the holding on the last trading day of each month, carry it otherwise
    month_end = close.index.to_series().groupby(close.index.tz_localize(None).to_period("M")).transform("max") == close.index
    return weights.where(month_end).ffill().fillna(0.0)


def run_lookbacks(close: pd.DataFrame, lookbacks=LOOKBACKS) -> dict:
    return {lb: portfolio_returns(dual_momentum_weights(close, lb), close) for lb in lookbacks}


if __name__ == "__main__":
    ohlcv = load_ohlcv(UNIVERSE, dt.date(2008, 1, 1), dt.date.today() + dt.timedelta(days=1))
    close = closes(ohlcv)
    print(f"{close.index[0].date()} to {close.index[-1].date()}, {len(close)} days\n")

    start = close.index[max(LOOKBACKS)]   # same window for all
    rows = {f"dual momentum {lb}d": summary(r.loc[start:]) for lb, r in run_lookbacks(close).items()}
    for sym in UNIVERSE:
        rows[f"buy&hold {sym}"] = summary(close[sym].pct_change().loc[start:].dropna())
    rows["equal-weight all (daily rebal)"] = summary(close.pct_change().loc[start:].mean(axis=1).dropna())

    out = pd.DataFrame(rows).T
    pd.options.display.float_format = "{:.2f}".format
    print(out.assign(total_return=out.total_return * 100, cagr=out.cagr * 100, max_drawdown=out.max_drawdown * 100)
             .rename(columns={"total_return": "total %", "cagr": "cagr %", "max_drawdown": "maxDD %"}))
