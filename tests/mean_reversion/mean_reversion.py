import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1d" (or "1h") to run everything below at a different bar frequency

def mean_reversion(df: pd.DataFrame, window: int, interval: str, zscore: float):

    # create base moving average and Bollinger Bands
    df["SMA"] = df["close"].rolling(window).mean()
    df["Upper"] = df["SMA"] + zscore * df["close"].rolling(window).std().shift(1)
    df["Lower"] = df["SMA"] - zscore * df["close"].rolling(window).std().shift(1)

    # signal/position vector
    df['signal'] = np.where(df['close'] < df['Lower'], 1, np.where(df['close'] > df['Upper'], -1, 0))
    return df

def optimize_mean_reversion(df: pd.DataFrame, window: int, interval: str, zscore: float):
    best_zscore = zscore
    best_pf = -1
    for z in np.arange(0.1, 3, 0.1):
        temp_df = mean_reversion(df.copy(), window, interval, z) # type: ignore[reportAttributeAccessIssue]
        strategy_r = apply_slippage(temp_df['signal'].shift(1), temp_df['close'].pct_change())
        profit = strategy_r.sum()
        if profit > best_pf:
            best_pf = profit
            best_zscore = float(z)
    return best_zscore, best_pf

def walkforward_mean_reversion(ohlc: pd.DataFrame, window: int, interval: str,
                                train_lookback: int = BAR_CONFIG[INTERVAL]["train_lookback"],
                                train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):

    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None

    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_zscore, _ = optimize_mean_reversion(ohlc.iloc[i-train_lookback:i], window, interval, zscore=1)
            tmp_df = mean_reversion(ohlc, window, interval, best_zscore)
            tmp_signal = tmp_df['signal']
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]

    return wf_signal


if __name__ == '__main__':
    df = get_bars("WMT", dt.date(2020, 8, 1), dt.date.today()+dt.timedelta(days=1), source="alpaca", interval=INTERVAL)

    best_zscore, best_pf = optimize_mean_reversion(df, window=20, interval=INTERVAL, zscore=1)
    print(f"Best Z-Score: {best_zscore}, Best Profit: {best_pf}")

    signals_df = mean_reversion(df.copy(), window=20, interval=INTERVAL, zscore=best_zscore)

    df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['mean_reversion_r'] = apply_slippage(signals_df['signal'], df['r'])

    wf_signal = walkforward_mean_reversion(df, window=20, interval=INTERVAL)
    wf_signal = pd.Series(wf_signal, index=df.index)
    df['wf_r'] = apply_slippage(wf_signal, df['r'])
    wf_pf = df['wf_r'][df['wf_r'] > 0].sum() / df['wf_r'][df['wf_r'] < 0].abs().sum()
    print(f"Walk-Forward PF: {wf_pf}")

    plt.style.use("dark_background")
    plt.title("In-Sample vs Walk-Forward Mean Reversion Performance")
    plt.plot(df['r'].cumsum(), label='Buy and Hold')
    plt.plot(df['mean_reversion_r'].cumsum(), label='In-Sample')
    plt.plot(df['wf_r'].cumsum(), label='Walk-Forward')
    plt.legend()
    plt.show()