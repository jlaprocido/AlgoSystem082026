import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_bars

def donchian_breakout(ohlc: pd.DataFrame, lookback: int):
    # input df is assumed to have a 'close' column
    upper = ohlc['close'].rolling(lookback - 1).max().shift(1)
    lower = ohlc['close'].rolling(lookback - 1).min().shift(1)
    signal = pd.Series(np.full(len(ohlc), np.nan), index=ohlc.index)
    signal.loc[ohlc['close'] > upper] = 1
    signal.loc[ohlc['close'] < lower] = -1
    signal = signal.ffill()
    return signal


def optimize_donchian(ohlc: pd.DataFrame):

    best_pf = 0
    best_lookback = -1
    r = np.log(ohlc['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    for lookback in range(12, 169):
        signal = donchian_breakout(ohlc, lookback)
        sig_rets = signal * r
        sig_pf = sig_rets[sig_rets > 0].sum() / sig_rets[sig_rets < 0].abs().sum()

        if sig_pf > best_pf:
            best_pf = sig_pf
            best_lookback = lookback

    return best_lookback, best_pf

# 252 * 4 = 4 years of daily data, 21 = 1 month of daily data
# for hourly, 6.5 * 252 * 4 = 4 years of hourly data, 6.5 * 21 = 1 month of hourly data
# this should change depending on the data frequency, but for now, we will assume daily data

def walkforward_donch(ohlc: pd.DataFrame, train_lookback: int = 252 * 4, train_step: int = 21):

    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None
    
    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_lookback, _ = optimize_donchian(ohlc.iloc[i-train_lookback:i])
            tmp_signal = donchian_breakout(ohlc, best_lookback)
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]
    
    return wf_signal


if __name__ == '__main__':

    df = get_bars("APLD", dt.date(2020, 1, 1), dt.date.today()+dt.timedelta(days=1), source="alpaca", interval="1d")

    best_lookback, best_real_pf = optimize_donchian(df)

    print(f"Best lookback: {best_lookback}, Best PF: {best_real_pf}")
    
    signal = donchian_breakout(df, best_lookback) 

    df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['donch_r'] = df['r'] * signal

    plt.style.use("dark_background")
    df['donch_r'].cumsum().plot(color='red', label='In-Sample')
    plt.title("In-Sample Donchian Breakout")
    plt.ylabel('Cumulative Log Return')


    wf_signal = walkforward_donch(df, train_lookback=252 * 4, train_step=21)

    df['r'] = np.log(df['close']).diff().shift(-1)  # type: ignore
    df['wf_r'] = df['r'] * wf_signal
    wf_pf = df['wf_r'][df['wf_r'] > 0].sum() / df['wf_r'][df['wf_r'] < 0].abs().sum()
    print(f"Walk-Forward PF: {wf_pf}")

    plt.style.use("dark_background")
    df['wf_r'].cumsum().plot(color='cyan', label='Walk-Forward')
    plt.title("In-Sample vs Walk-Forward Donchian Breakout (AAPL, daily)")
    plt.ylabel("Cumulative Log Return")
    plt.legend()

    plt.show()