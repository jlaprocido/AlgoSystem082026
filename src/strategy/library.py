"""Every strategy is one function with this exact shape:

    strategy_fn(ohlcv: dict[str, DataFrame], **params) -> DataFrame

  ohlcv   one DataFrame per symbol (columns open/high/low/close/volume), oldest bar first, all
          sharing one index
  result  a weights table: same index, one column per symbol. Row t is the target position
          decided at bar t's close, as a fraction of the strategy's money: 0 = flat, 1 = fully
          invested. Shorts come back as -1 and are clipped to 0 by `Strategy.weights` (crypto
          cannot be shorted and the live book is long-only), so backtest == live.

The same function backs the lab backtest and the live engine. A strategy never knows whether it
is trading stocks or crypto, or which interval the bars are. Window sizes are bar counts, so
"20" means 20 days on daily bars and 20 hours on hourly bars.

These mirror the signal code in tests/<name>/<name>.py (the research versions with grid search
and permutation tests); this is the lean, swappable form of the same logic.
"""
import numpy as np
import pandas as pd


def _table(per_symbol: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(per_symbol)


def sma(ohlcv: dict[str, pd.DataFrame], fast: int = 5, slow: int = 20) -> pd.DataFrame:
    """Long while the fast moving average is above the slow one."""
    out = {}
    for sym, df in ohlcv.items():
        out[sym] = (df["close"].rolling(fast).mean() > df["close"].rolling(slow).mean()).astype(float)
    return _table(out)


def three_sma(ohlcv: dict[str, pd.DataFrame], fast: int = 10, med: int = 25, slow: int = 50) -> pd.DataFrame:
    """Long only when fast > med > slow are all aligned."""
    out = {}
    for sym, df in ohlcv.items():
        f, m, s = (df["close"].rolling(w).mean() for w in (fast, med, slow))
        out[sym] = ((f > m) & (m > s)).astype(float)
    return _table(out)


def donchian(ohlcv: dict[str, pd.DataFrame], lookback: int = 20) -> pd.DataFrame:
    """Long above the recent high, short below the recent low, hold until the opposite break."""
    out = {}
    for sym, df in ohlcv.items():
        upper = df["close"].rolling(lookback - 1).max().shift(1)
        lower = df["close"].rolling(lookback - 1).min().shift(1)
        sig = pd.Series(np.nan, index=df.index)
        sig.loc[df["close"] > upper] = 1
        sig.loc[df["close"] < lower] = -1
        out[sym] = sig.ffill().fillna(0.0)
    return _table(out)


def mean_reversion(ohlcv: dict[str, pd.DataFrame], window: int = 20, zscore: float = 2.0) -> pd.DataFrame:
    """Bollinger bands: buy below the lower band, sell (go flat) above the upper band."""
    out = {}
    for sym, df in ohlcv.items():
        ma = df["close"].rolling(window).mean()
        band = zscore * df["close"].rolling(window).std().shift(1)
        out[sym] = pd.Series(np.where(df["close"] < ma - band, 1.0, np.where(df["close"] > ma + band, -1.0, 0.0)),
                             index=df.index)
    return _table(out)


def volume_spike(ohlcv: dict[str, pd.DataFrame], lookback: int = 20, multiplier: float = 2.0) -> pd.DataFrame:
    """Long for the next bar after an unusually large, up-close volume bar."""
    out = {}
    for sym, df in ohlcv.items():
        avg_volume = df["volume"].rolling(lookback).mean().shift(1)
        out[sym] = ((df["volume"] > avg_volume * multiplier) & (df["close"] > df["open"])).astype(float)
    return _table(out)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
                     axis=1).max(axis=1)


def vol_regime(ohlcv: dict[str, pd.DataFrame], breakout_lookback: int = 20, atr_lookback: int = 14,
               atr_baseline: int = 100, vol_multiplier: float = 1.0) -> pd.DataFrame:
    """Donchian breakout that only fires while volatility (ATR) is expanding vs. its own baseline."""
    breakout = donchian(ohlcv, breakout_lookback)
    out = {}
    for sym, df in ohlcv.items():
        atr = _true_range(df).rolling(atr_lookback).mean()
        expanding = atr > atr.rolling(atr_baseline).mean().shift(1) * vol_multiplier
        out[sym] = breakout[sym].where(expanding, 0.0)
    return _table(out)


def dual_momentum_weights(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    mom = close.pct_change(lookback).fillna(-np.inf)   # no history yet -> never picked
    best = mom.idxmax(axis=1)                          # strongest asset each day
    best_ret = mom.max(axis=1)

    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for date in close.index:
        if best_ret[date] > 0:
            weights.loc[date, best[date]] = 1.0

    # only change the holding on the last trading day of each month, carry it otherwise
    month_end = close.index.to_series().groupby(close.index.tz_localize(None).to_period("M")).transform("max") == close.index
    return weights.where(month_end).ffill().fillna(0.0)


def dual_momentum(ohlcv: dict[str, pd.DataFrame], lookback: int = 126) -> pd.DataFrame:
    """Hold the single strongest asset (by `lookback`-bar return) if it is rising, else cash. Monthly."""
    close = pd.DataFrame({sym: df["close"] for sym, df in ohlcv.items()})
    return dual_momentum_weights(close, lookback)
