import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1h" (or any other BAR_CONFIG key) to run everything below at a different bar frequency

def donchian_breakout(ohlc: pd.DataFrame, lookback: int):
    # input df is assumed to have a 'close' column
    upper = ohlc['close'].rolling(lookback - 1).max().shift(1)
    lower = ohlc['close'].rolling(lookback - 1).min().shift(1)
    signal = pd.Series(np.full(len(ohlc), np.nan), index=ohlc.index)
    signal.loc[ohlc['close'] > upper] = 1
    signal.loc[ohlc['close'] < lower] = -1
    signal = signal.ffill()
    return signal


def optimize_donchian(ohlc: pd.DataFrame, min_trades: int = 20):

    best_pf = 0
    best_lookback = -1
    r = np.log(ohlc['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    for lookback in range(12, 169):
        signal = donchian_breakout(ohlc, lookback)

        # skip lookbacks with too few trades to mean anything -- PF on a handful of trades is
        # noise, and a lookback with zero losing trades gives a 0-division PF (inf/NaN)
        if (signal.diff().fillna(0) != 0).sum() < min_trades:
            continue

        sig_rets = apply_slippage(signal, r)
        gross_loss = sig_rets[sig_rets < 0].abs().sum()
        if gross_loss == 0:
            continue

        sig_pf = sig_rets[sig_rets > 0].sum() / gross_loss
        if sig_pf > best_pf:
            best_pf = sig_pf
            best_lookback = lookback

    return best_lookback, best_pf

def walkforward_donch(ohlc: pd.DataFrame,
                       train_lookback: int = BAR_CONFIG[INTERVAL]["train_lookback"],
                       train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):

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

    df = get_bars("APLD", dt.date(2020, 1, 1), dt.date.today()+dt.timedelta(days=1), interval=INTERVAL)

    best_lookback, best_real_pf = optimize_donchian(df)
    print(f"Best lookback: {best_lookback}, Best PF: {best_real_pf:.2f}")

    signal = donchian_breakout(df, best_lookback)

    df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['donch_r'] = apply_slippage(signal, df['r'])

    bars_per_year = BAR_CONFIG[INTERVAL]["bars_per_year"]
    bh_r = df['r'].dropna()
    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year)

    r = df['donch_r'].dropna()
    strategy_return = np.exp(r.sum()) - 1
    profit_factor = r[r > 0].sum() / r[r < 0].abs().sum()
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)

    print(f"Buy and Hold Return: {bh_return:.2%}, Sharpe Ratio: {bh_sharpe:.2f}")
    print(f"Strategy Return: {strategy_return:.2%}, Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")

    plt.style.use("dark_background")
    df['donch_r'].cumsum().plot(color='red', label='In-Sample')
    plt.title("In-Sample Donchian Breakout")
    plt.ylabel('Cumulative Log Return')


    wf_signal = walkforward_donch(df)

    df['wf_r'] = apply_slippage(pd.Series(wf_signal, index=df.index), df['r'])
    wf_r = df['wf_r'].dropna()
    wf_pf = wf_r[wf_r > 0].sum() / wf_r[wf_r < 0].abs().sum()
    print(f"Walk-Forward PF: {wf_pf:.2f}")

    plt.style.use("dark_background")
    df['wf_r'].cumsum().plot(color='cyan', label='Walk-Forward')
    plt.title("In-Sample vs Walk-Forward Donchian Breakout (AAPL, daily)")
    plt.ylabel("Cumulative Log Return")
    plt.legend()

    plt.show()