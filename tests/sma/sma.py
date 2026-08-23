import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime as dt

from src.data.market_data import get_bars

def sma_strategy(df: pd.DataFrame, fast_window: int = 10, slow_window: int = 50, interval: str = "1d"):
    fast_ma = df['close'].rolling(window=fast_window).mean()
    slow_ma = df['close'].rolling(window=slow_window).mean()

    # signal/position vector: the position at each bar
    df['signal'] = np.where(fast_ma > slow_ma, 1, 0)

    df['return'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['strategy_return'] = df['signal'] * df['return']

    r = df['strategy_return']
    profit_factor = r[r > 0].sum() / r[r < 0].abs().sum()

    if interval == "1m":
        bars_per_year = 252 * 390
    elif interval == "1h":
        bars_per_year = 252 * 7
    elif interval == "1d":
        bars_per_year = 252
    else:
        raise ValueError(f"Unknown interval: {interval}")

    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)

    return profit_factor, sharpe_ratio, df[['close', 'signal', 'return', 'strategy_return']]

if __name__ == "__main__":
    df = get_bars("SPY", dt.date(2026, 1, 1), dt.date.today()+dt.timedelta(days=1), source="alpaca", interval="1m")
    profit_factor, sharpe_ratio, df_sma = sma_strategy(df, interval="1m")
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
    plt.title("In-Sample SMA Strategy")
    plt.ylabel('Cumulative Log Return')
    plt.show()