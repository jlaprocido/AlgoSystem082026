import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1h" (or any other BAR_CONFIG key) to run everything below at a different bar frequency

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df['close'].shift(1)
    return pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)


def vol_regime_strategy(df: pd.DataFrame, breakout_lookback: int = 20, atr_lookback: int = 14,
                         atr_baseline: int = 100, vol_multiplier: float = 1.0, interval: str = INTERVAL):

    # Donchian-style breakout: long above the recent high, short below the recent low,
    # holding the position until the opposite breakout fires
    upper = df['close'].rolling(breakout_lookback - 1).max().shift(1)
    lower = df['close'].rolling(breakout_lookback - 1).min().shift(1)
    breakout = pd.Series(np.nan, index=df.index)
    breakout.loc[df['close'] > upper] = 1
    breakout.loc[df['close'] < lower] = -1
    breakout = breakout.ffill().fillna(0)

    # only take the breakout when volatility is expanding relative to its own baseline --
    # a breakout in a dead, range-bound market is usually just noise
    atr = true_range(df).rolling(atr_lookback).mean()
    atr_baseline_avg = atr.rolling(atr_baseline).mean().shift(1)
    vol_expanding = atr > atr_baseline_avg * vol_multiplier

    df['signal'] = np.where(vol_expanding, breakout, 0)
    return df


def optimize_vol_regime_strategy(df: pd.DataFrame, interval: str = INTERVAL, min_trades: int = 20):
    best_pf = 0
    best_params = (-1, -1.0)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    for breakout_lookback in range(10, 60, 10):
        for vol_multiplier in np.arange(0.0, 2.2, 0.2):
            temp_df = vol_regime_strategy(df.copy(), breakout_lookback, vol_multiplier=float(vol_multiplier), interval=interval)  # type: ignore[reportArgumentType]
            signal = temp_df['signal']

            # skip combos with too few trades to mean anything -- PF on a handful of
            # trades is noise, and a combo with zero losing trades gives a 0-division PF
            if (signal != 0).sum() < min_trades:
                continue

            strategy_r = apply_slippage(signal, r)
            gross_loss = strategy_r[strategy_r < 0].abs().sum()
            if gross_loss == 0:
                continue

            pf = strategy_r[strategy_r > 0].sum() / gross_loss
            if pf > best_pf:
                best_pf = pf
                best_params = (breakout_lookback, float(vol_multiplier))

    return best_params, best_pf


def walkforward_vol_regime(ohlc: pd.DataFrame, interval: str = INTERVAL,
                            train_lookback: int = BAR_CONFIG[INTERVAL]["train_lookback"],
                            train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):

    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None

    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_params, _ = optimize_vol_regime_strategy(ohlc.iloc[i-train_lookback:i], interval)
            best_breakout_lookback, best_vol_multiplier = best_params
            tmp_df = vol_regime_strategy(ohlc, best_breakout_lookback, vol_multiplier=best_vol_multiplier, interval=interval)
            tmp_signal = tmp_df['signal']
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]

    return wf_signal


if __name__ == "__main__":
    df = get_bars("AAPL", dt.date(2016, 1, 1), dt.date.today()+dt.timedelta(days=1), interval=INTERVAL)

    best_params, best_pf = optimize_vol_regime_strategy(df, interval=INTERVAL)
    best_breakout_lookback, best_vol_multiplier = best_params
    print(f"Best Breakout Lookback: {best_breakout_lookback}, Best Vol Multiplier: {best_vol_multiplier}, In-Sample PF: {best_pf:.2f}")

    signals_df = vol_regime_strategy(df.copy(), best_breakout_lookback, vol_multiplier=best_vol_multiplier, interval=INTERVAL)

    df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['vol_regime_r'] = apply_slippage(signals_df['signal'], df['r'])

    bars_per_year = BAR_CONFIG[INTERVAL]["bars_per_year"]

    bh_r = df['r'].dropna()
    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year)

    r = df['vol_regime_r'].dropna()
    strategy_return = np.exp(r.sum()) - 1
    profit_factor = r[r > 0].sum() / r[r < 0].abs().sum()
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)

    print(f"Buy and Hold Return: {bh_return:.2%}, Sharpe Ratio: {bh_sharpe:.2f}")
    print(f"Strategy Return: {strategy_return:.2%}, Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")

    wf_signal = walkforward_vol_regime(df, interval=INTERVAL)
    wf_signal = pd.Series(wf_signal, index=df.index)
    df['wf_r'] = apply_slippage(wf_signal, df['r'])
    wf_pf = df['wf_r'][df['wf_r'] > 0].sum() / df['wf_r'][df['wf_r'] < 0].abs().sum()
    print(f"Walk-Forward PF: {wf_pf:.2f}")

    plt.style.use("dark_background")
    plt.title("In-Sample vs Walk-Forward Volatility Regime Breakout (SPY, 1d)")
    plt.plot(df['r'].cumsum(), label='Buy and Hold')
    plt.plot(df['vol_regime_r'].cumsum(), label='In-Sample')
    plt.plot(df['wf_r'].cumsum(), label='Walk-Forward')
    plt.ylabel('Cumulative Log Return')
    plt.legend()
    plt.show()
