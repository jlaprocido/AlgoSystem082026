"""Dual momentum: each month hold the single strongest asset, or cash if nothing is going up.

  relative momentum: rank the assets by their return over the last `lookback` days, pick the best
  absolute momentum: only hold it if that return is positive; otherwise sit in cash

Rebalances once a month (last trading day), so it trades rarely and costs almost nothing.
"""
import datetime as dt

import numpy as np
import pandas as pd

from src.backtest.portfolio import load_ohlcv, closes, portfolio_returns, summary
from src.strategy.library import dual_momentum_weights  # the strategy function now lives in the library

UNIVERSE = ["SPY", "EFA", "TLT", "GLD"]   # US stocks, international stocks, long bonds, gold
LOOKBACKS = [63, 126, 189, 252]           # ~3, 6, 9, 12 months of trading days


def run_lookbacks(close: pd.DataFrame, lookbacks=LOOKBACKS) -> dict:
    return {lb: portfolio_returns(dual_momentum_weights(close, lb), close) for lb in lookbacks}


if __name__ == "__main__":
    ohlcv = load_ohlcv(UNIVERSE, dt.date(2008, 1, 1), dt.date.today() + dt.timedelta(days=1))
    close = closes(ohlcv)
    print(f"{close.index[0].date()} to {close.index[-1].date()}, {len(close)} days\n")

    rows = {}
    for lb, r in run_lookbacks(close).items():
        rows[f"dual momentum {lb}d"] = summary(r.loc[close.index[max(LOOKBACKS)]:])   # same window for all
    start = close.index[max(LOOKBACKS)]
    for sym in UNIVERSE:
        rows[f"buy&hold {sym}"] = summary(close[sym].pct_change().loc[start:].dropna())
    rows["equal-weight all (daily rebal)"] = summary(close.pct_change().loc[start:].mean(axis=1).dropna())

    out = pd.DataFrame(rows).T
    pd.options.display.float_format = "{:.2f}".format
    print(out.assign(total_return=out.total_return * 100, cagr=out.cagr * 100, max_drawdown=out.max_drawdown * 100)
             .rename(columns={"total_return": "total %", "cagr": "cagr %", "max_drawdown": "maxDD %"}))
