import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime as dt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1d" (or "1h") to run everything below at a different bar frequency

def sma_strategy(df: pd.DataFrame, fast_window: int = 10, slow_window: int = 50, interval: str = INTERVAL):
    fast_ma = df['close'].rolling(window=fast_window).mean()
    slow_ma = df['close'].rolling(window=slow_window).mean()

    # signal/position vector: the position at each bar
    df['signal'] = np.where(fast_ma > slow_ma, 1, 0)

    df['return'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['strategy_return'] = apply_slippage(df['signal'], df['return'])

    r = df['strategy_return']
    gross_loss = r[r < 0].abs().sum()
    profit_factor = r[r > 0].sum() / gross_loss if gross_loss > 0 else np.nan

    bars_per_year = BAR_CONFIG[interval]["bars_per_year"]
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year) if r.std() > 0 else np.nan

    return profit_factor, sharpe_ratio, df[['close', 'signal', 'return', 'strategy_return']]


def optimize_sma_strategy(df: pd.DataFrame, interval: str = INTERVAL):
    best_pf = 0
    best_windows = (-1, -1)
    for fast_window in range(5, 50, 5):
        for slow_window in range(20, 210, 10):
            if fast_window >= slow_window:
                continue
            pf, _, _ = sma_strategy(df.copy(), fast_window, slow_window, interval)
            if pf > best_pf:
                best_pf = pf
                best_windows = (fast_window, slow_window)
    return best_windows, best_pf


def walkforward_sma(ohlc: pd.DataFrame, interval: str = INTERVAL,
                     train_lookback: int = BAR_CONFIG[INTERVAL]["train_lookback"],
                     train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):

    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None

    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_windows, _ = optimize_sma_strategy(ohlc.iloc[i-train_lookback:i], interval=interval)
            fast_window, slow_window = best_windows
            _, _, tmp_df = sma_strategy(ohlc, fast_window, slow_window, interval=interval)
            tmp_signal = tmp_df['signal']
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]

    return wf_signal

if __name__ == "__main__":
    df = get_bars("WMT", dt.date(2016, 1, 1), dt.date.today()+dt.timedelta(days=1), interval=INTERVAL)
    profit_factor, sharpe_ratio, df_sma = sma_strategy(df, interval=INTERVAL)

    bars_per_year = BAR_CONFIG[INTERVAL]["bars_per_year"]
    bh_r = df_sma['return'].dropna()
    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year)

    r = df_sma['strategy_return'].dropna()
    strategy_return = np.exp(r.sum()) - 1

    print(f"Buy and Hold Return: {bh_return:.2%}, Sharpe Ratio: {bh_sharpe:.2f}")
    print(f"Strategy Return: {strategy_return:.2%}, Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")

    gross_profit = r[r > 0].sum()
    gross_loss = r[r < 0].abs().sum()
    win_rate = (r > 0).sum() / (r != 0).sum()
    print(f"Gross Profit: {gross_profit:.4f}")
    print(f"Gross Loss: {gross_loss:.4f}")
    print(f"Win Rate: {win_rate:.2%}")

    plt.style.use("dark_background")
    df_sma['strategy_return'].cumsum().plot(color='red')
    plt.title("In-Sample SMA Strategy")
    plt.ylabel('Cumulative Log Return')
    plt.show()