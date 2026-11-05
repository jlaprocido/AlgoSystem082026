import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_yfinance_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"
SYMBOL = "IBIT"
START = dt.date(2024, 1, 11)  # IBIT's first trading day
TRAIN_LOOKBACK = 252  # ~1 year -- BAR_CONFIG's 4 years is longer than IBIT's whole history
FILTER_LOOKBACKS = [0, 5, 10, 20, 40, 60, 90, 120]  # 0 = no filter, hold every night


def get_ibit_bars() -> pd.DataFrame:
    # calls yfinance directly instead of get_bars(): this start date would route to Alpaca's IEX
    # feed, and this strategy trades the official open and close, which IEX prints may not match
    return get_yfinance_bars(SYMBOL, START, dt.date.today() + dt.timedelta(days=1), interval=INTERVAL)


def overnight_signal(df: pd.DataFrame, filter_lookback: int = 0) -> pd.Series:
    # 1 at bar i means: buy at bar i's close, sell at bar i+1's open.
    # filter_lookback > 0 only holds tonight if recent nights have made money on average
    if filter_lookback == 0:
        return pd.Series(1.0, index=df.index)
    # the shift means only nights already finished by this bar's close are used
    past_nights = np.log(df['open'] / df['close'].shift(1))
    return (past_nights.rolling(filter_lookback).mean() > 0).astype(float)


def overnight_returns(df: pd.DataFrame, signal: pd.Series, slippage_pct: float = 0.0005) -> pd.Series:
    # apply_slippage only charges when the signal changes, and a held-every-night signal never
    # changes -- so run it on close/open steps (long overnight, flat all day), which charges
    # both the buy and the sell of every night actually held
    tonight = np.log(df['open'].shift(-1) / df['close']).to_numpy()
    steps_signal = pd.Series(np.column_stack([signal.to_numpy(), np.zeros(len(df))]).ravel())
    steps_return = pd.Series(np.column_stack([tonight, np.zeros(len(df))]).ravel())
    steps_net = apply_slippage(steps_signal, steps_return, slippage_pct).fillna(0.0).to_numpy()
    net = steps_net[0::2] + steps_net[1::2]
    net[np.isnan(tonight)] = np.nan  # the last bar has no next open yet
    return pd.Series(net, index=df.index)


def profit_factor(r: pd.Series) -> float:
    gross_loss = r[r < 0].abs().sum()
    return r[r > 0].sum() / gross_loss if gross_loss > 0 else np.nan


def optimize_overnight(df: pd.DataFrame, min_trades: int = 20):
    best_pf = 0
    best_lookback = -1
    for filter_lookback in FILTER_LOOKBACKS:
        signal = overnight_signal(df, filter_lookback)
        if signal.sum() < min_trades:
            continue
        pf = profit_factor(overnight_returns(df, signal))
        if pf > best_pf:
            best_pf = pf
            best_lookback = filter_lookback
    return best_lookback, best_pf


def walkforward_overnight(ohlc: pd.DataFrame, train_lookback: int = TRAIN_LOOKBACK,
                          train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):
    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None

    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_lookback, _ = optimize_overnight(ohlc.iloc[i-train_lookback:i])
            tmp_signal = overnight_signal(ohlc, max(best_lookback, 0))
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]

    return wf_signal


def get_overnight_permutation(ohlc: pd.DataFrame, start_index: int = 0) -> pd.DataFrame:
    # tests/bar_permute.py can't test this strategy: it shuffles the gaps only among themselves,
    # so the total overnight return -- all this strategy earns -- stays the same in every
    # permutation. The question here is whether nights beat days, so each day randomly swaps
    # its overnight move with its intraday move, keeping that day's two moves and the total drift
    log_open = np.log(ohlc['open'].to_numpy())
    log_close = np.log(ohlc['close'].to_numpy())
    gaps = log_open[1:] - log_close[:-1]
    days = log_close[1:] - log_open[1:]

    swap = np.random.random(len(gaps)) < 0.5
    swap[:start_index] = False
    new_gaps = np.where(swap, days, gaps)
    new_days = np.where(swap, gaps, days)

    perm_open = log_open.copy()
    perm_close = log_close.copy()
    for i in range(1, len(ohlc)):
        perm_open[i] = perm_close[i-1] + new_gaps[i-1]
        perm_close[i] = perm_open[i] + new_days[i-1]

    perm = ohlc.copy()
    perm['open'] = np.exp(perm_open)
    perm['close'] = np.exp(perm_close)
    perm['high'] = perm[['open', 'close']].max(axis=1)  # this strategy never reads high or low
    perm['low'] = perm[['open', 'close']].min(axis=1)
    return perm


if __name__ == "__main__":
    df = get_ibit_bars()
    print(f"{SYMBOL}: {df['timestamp'].iloc[0].date()} to {df['timestamp'].iloc[-1].date()}, {len(df)} bars")

    bars_per_year = BAR_CONFIG[INTERVAL]["bars_per_year"]
    df['r'] = np.log(df['close']).diff().shift(-1)  # type: ignore[reportAttributeAccessIssue]
    bh_r = df['r'].dropna()
    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year)
    print(f"Buy and Hold Return: {bh_return:.2%}, Sharpe Ratio: {bh_sharpe:.2f}")

    # the plain rule with no filter, at the repo's default cost (5 bps per side)
    df['overnight_r'] = overnight_returns(df, overnight_signal(df))
    r = df['overnight_r'].dropna()
    strategy_return = np.exp(r.sum()) - 1
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)
    print(f"Strategy Return: {strategy_return:.2%}, Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Profit Factor: {profit_factor(r):.2f}")
    print(f"Gross Profit: {r[r > 0].sum():.4f}")
    print(f"Gross Loss: {r[r < 0].abs().sum():.4f}")
    print(f"Win Rate: {(r > 0).sum() / (r != 0).sum():.2%}")

    # what the result looks like if real costs differ from the repo's default
    for slippage_pct in [0.0, 0.0001, 0.00025, 0.00035, 0.0005]:
        c = overnight_returns(df, overnight_signal(df), slippage_pct).dropna()
        print(f"  {slippage_pct * 2e4:.0f} bps round trip: Return {np.exp(c.sum()) - 1:.2%}, "
              f"Sharpe {(c.mean() / c.std()) * np.sqrt(bars_per_year):.2f}, PF {profit_factor(c):.2f}")

    best_lookback, best_pf = optimize_overnight(df)
    print(f"Best Filter Lookback: {best_lookback}, In-Sample PF: {best_pf:.2f}")
    df['is_r'] = overnight_returns(df, overnight_signal(df, best_lookback))

    wf_signal = pd.Series(walkforward_overnight(df), index=df.index)
    df['wf_r'] = overnight_returns(df, wf_signal.fillna(0.0))
    df.loc[wf_signal.isna(), 'wf_r'] = np.nan
    wf_r = df['wf_r'].dropna()
    wf_bh = df['r'][wf_r.index].dropna()
    print(f"Walk-Forward PF: {profit_factor(wf_r):.2f}, Return: {np.exp(wf_r.sum()) - 1:.2%}, "
          f"Sharpe: {(wf_r.mean() / wf_r.std()) * np.sqrt(bars_per_year):.2f}")
    print(f"Buy and Hold over the same walk-forward bars: Return: {np.exp(wf_bh.sum()) - 1:.2%}, "
          f"Sharpe: {(wf_bh.mean() / wf_bh.std()) * np.sqrt(bars_per_year):.2f}")

    plt.style.use("dark_background")
    plt.title("IBIT Overnight: Plain Rule, In-Sample Filter and Walk-Forward")
    plt.plot(df['r'].cumsum(), label='Buy and Hold')
    plt.plot(df['overnight_r'].cumsum(), label='Plain Rule')
    plt.plot(df['is_r'].cumsum(), label='In-Sample')
    plt.plot(df['wf_r'].cumsum(), label='Walk-Forward')
    plt.ylabel('Cumulative Log Return')
    plt.legend()
    plt.show()
