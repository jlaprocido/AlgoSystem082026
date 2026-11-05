"""Multi-asset backtest harness.

The single-symbol backtests multiply one 0/1 signal by one return series. A portfolio is the same
idea with a *weights table*: one column per symbol, one row per day, each row says what fraction of
the account to hold in each symbol at that day's close (rows sum to <= 1; whatever is missing is
cash, which earns 0 here to keep things simple).
"""
import datetime as dt

import numpy as np
import pandas as pd

from src.data.market_data import get_bars

SLIPPAGE_PCT = 0.0005  # same per-unit-of-turnover cost as src/backtest/costs.apply_slippage


def load_ohlcv(symbols: list[str], start: dt.date, end: dt.date) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per symbol, all trimmed to the dates every symbol has (indexed by date)."""
    raw = {}
    for s in symbols:
        df = get_bars(s, start, end, interval="1d").set_index("timestamp")
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


def summary(r: pd.Series) -> dict:
    """Total return, annualized return, Sharpe and max drawdown of a daily return series."""
    equity = (1 + r).cumprod()
    years = len(r) / 252
    return {
        "total_return": equity.iloc[-1] - 1,
        "cagr": equity.iloc[-1] ** (1 / years) - 1,
        "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
        "max_drawdown": (equity / equity.cummax() - 1).min(),
    }
