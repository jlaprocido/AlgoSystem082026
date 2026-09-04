import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime as dt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1d" (or "1h") to run everything below at a different bar frequency

def three_sma_strategy(df: pd.DataFrame, fast_window: int = 10, med_window: int = 25, slow_window: int = 50,
                        interval: str = INTERVAL):

    fast_ma = df['close'].rolling(window=fast_window).mean()
    med_ma = df['close'].rolling(window=med_window).mean()
    slow_ma = df['close'].rolling(window=slow_window).mean()

    # long only when all three are aligned bullish (fast > med > slow), flat otherwise
    df['signal'] = np.where((fast_ma > med_ma) & (med_ma > slow_ma), 1, 0)

    df['return'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['strategy_return'] = apply_slippage(df['signal'], df['return'])

    r = df['strategy_return']
    profit_factor = r[r > 0].sum() / r[r < 0].abs().sum()

    bars_per_year = BAR_CONFIG[interval]["bars_per_year"]
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)

    return profit_factor, sharpe_ratio, df[['close', 'signal', 'return', 'strategy_return']]


def optimize_three_sma_strategy(df: pd.DataFrame, interval: str = INTERVAL):
    best_pf = 0
    best_windows = (-1, -1, -1)
    for fast_window in range(5, 30, 5):
        for med_window in range(20, 60, 10):
            for slow_window in range(50, 210, 20):
                if not (fast_window < med_window < slow_window):
                    continue
                pf, _, _ = three_sma_strategy(df.copy(), fast_window, med_window, slow_window, interval)
                if pf > best_pf:
                    best_pf = pf
                    best_windows = (fast_window, med_window, slow_window)
    return best_windows, best_pf

if __name__ == "__main__":
    df = get_bars("SPY", dt.date(2016, 1, 1), dt.date.today()+dt.timedelta(days=1), source="yfinance", interval=INTERVAL)
    profit_factor, sharpe_ratio, df_sma = three_sma_strategy(df, interval=INTERVAL)
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

    r = df_sma['strategy_return']
    gross_profit = r[r > 0].sum()
    gross_loss = r[r < 0].abs().sum()
    win_rate = (r > 0).sum() / (r != 0).sum()
    print(f"Gross Profit: {gross_profit:.4f}")
    print(f"Gross Loss: {gross_loss:.4f}")
    print(f"Win Rate: {win_rate:.2%}")

    plt.style.use("dark_background")
    df_sma['strategy_return'].cumsum().plot(color='red')
    plt.title("In-Sample 3-SMA Strategy")
    plt.ylabel('Cumulative Log Return')
    plt.show()
