"""Multi-asset backtest harness.

The single-symbol backtests multiply one 0/1 signal by one return series. A portfolio is the same
idea with a *weights table*: one column per symbol, one row per day, each row says what fraction of
the account to hold in each symbol at that day's close (rows sum to <= 1; whatever is missing is
cash, which earns 0 here to keep things simple).
"""
import datetime as dt

import numpy as np
import pandas as pd

from src.assets import asset_for

SLIPPAGE_PCT = 0.0005  # same per-unit-of-turnover cost as src/backtest/costs.apply_slippage


def load_ohlcv(symbols: list[str], start: dt.date, end: dt.date, interval: str = "1d") -> dict[str, pd.DataFrame]:
    """OHLCV per symbol at `interval`, trimmed to the timestamps every symbol has. The asset
    adapter picks the data source (stocks vs crypto); mix only symbols that share a calendar --
    trimming stocks + crypto together would silently drop every crypto weekend."""
    if len({asset_for(s).name for s in symbols}) > 1:
        raise ValueError(f"Mixing stocks and crypto in one backtest drops every crypto weekend: {symbols}")
    raw = {}
    for s in symbols:
        df = asset_for(s).get_bars(s, start, end, interval).set_index("timestamp")
        raw[s] = df[["open", "high", "low", "close", "volume"]]
    common = raw[symbols[0]].index
    for df in raw.values():
        common = common.intersection(df.index)
    return {s: df.loc[common] for s, df in raw.items()}


def closes(ohlcv: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({s: df["close"] for s, df in ohlcv.items()})


def portfolio_returns(weights: pd.DataFrame, close: pd.DataFrame, slippage_pct: float = SLIPPAGE_PCT) -> pd.Series:
    """Daily net return of holding `weights` (decided at each day's close) through the next day."""
    asset_ret = close.pct_change().shift(-1)          # return earned *after* the day's close
    gross = (weights * asset_ret).sum(axis=1)
    cost = slippage_pct * weights.diff().abs().sum(axis=1)
    return (gross - cost).dropna()


def summary(r: pd.Series, periods_per_year: int = 252) -> dict:
    """Total return, annualized return, Sharpe and max drawdown of a per-bar return series.
    periods_per_year: 252 for daily stock bars, 365 for daily crypto bars (see assets.py)."""
    equity = (1 + r).cumprod()
    years = len(r) / periods_per_year
    return {
        "total_return": equity.iloc[-1] - 1,
        "cagr": equity.iloc[-1] ** (1 / years) - 1,
        "sharpe": r.mean() / r.std() * np.sqrt(periods_per_year) if r.std() > 0 else np.nan,
        "max_drawdown": (equity / equity.cummax() - 1).min(),
    }
