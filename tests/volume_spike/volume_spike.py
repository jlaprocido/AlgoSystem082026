import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt

from src.data.market_data import get_bars
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

INTERVAL = "1d"  # flip to "1h" (or any other BAR_CONFIG key) to run everything below at a different bar frequency

def volume_spike_strategy(df: pd.DataFrame, lookback: int = 20, multiplier: float = 2.0, interval: str = INTERVAL):
    # trailing average volume, shifted so this bar's own volume isn't part of its own threshold
    avg_volume = df['volume'].rolling(lookback).mean().shift(1)
    volume_spike = df['volume'] > avg_volume * multiplier
    up_bar = df['close'] > df['open']

    # long for the next bar only when this bar prints an unusually large, up-close volume spike
    df['signal'] = np.where(volume_spike & up_bar, 1, 0)
    return df


def optimize_volume_spike_strategy(df: pd.DataFrame, interval: str = INTERVAL, min_trades: int = 20):
    best_pf = 0
    best_params = (-1, -1.0)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    for lookback in range(10, 60, 10):
        for multiplier in np.arange(1.5, 4.0, 0.5):
            temp_df = volume_spike_strategy(df.copy(), lookback, float(multiplier), interval)  # type: ignore[reportArgumentType]
            signal = temp_df['signal']

            # skip combos with too few trades to mean anything -- PF on 3 trades is noise,
            # and a combo with zero losing trades gives a 0-division PF (inf/NaN)
            if signal.sum() < min_trades:
                continue

            strategy_r = apply_slippage(signal, r)
            gross_loss = strategy_r[strategy_r < 0].abs().sum()
            if gross_loss == 0:
                continue

            pf = strategy_r[strategy_r > 0].sum() / gross_loss
            if pf > best_pf:
                best_pf = pf
                best_params = (lookback, float(multiplier))

    return best_params, best_pf


def walkforward_vs(ohlc: pd.DataFrame, interval: str = INTERVAL,
                    train_lookback: int = BAR_CONFIG[INTERVAL]["train_lookback"],
                    train_step: int = BAR_CONFIG[INTERVAL]["train_step"]):

    n = len(ohlc)
    wf_signal = np.full(n, np.nan)
    tmp_signal = None

    next_train = train_lookback
    for i in range(next_train, n):
        if i == next_train:
            best_params, _ = optimize_volume_spike_strategy(ohlc.iloc[i-train_lookback:i], interval)
            best_lookback, best_multiplier = best_params
            tmp_df = volume_spike_strategy(ohlc, best_lookback, best_multiplier, interval)
            tmp_signal = tmp_df['signal']
            next_train += train_step
        assert tmp_signal is not None
        wf_signal[i] = tmp_signal.iloc[i]

    return wf_signal


if __name__ == "__main__":
    df = get_bars("NPKI", dt.date(2020, 8, 1), dt.date.today()+dt.timedelta(days=1), interval=INTERVAL)

    best_params, best_pf = optimize_volume_spike_strategy(df, interval=INTERVAL)
    best_lookback, best_multiplier = best_params
    print(f"Best Lookback: {best_lookback}, Best Multiplier: {best_multiplier}, In-Sample PF: {best_pf:.2f}")

    signals_df = volume_spike_strategy(df.copy(), best_lookback, best_multiplier, interval=INTERVAL)

    df['r'] = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    df['volume_spike_r'] = apply_slippage(signals_df['signal'], df['r'])

    bars_per_year = BAR_CONFIG[INTERVAL]["bars_per_year"]

    bh_r = df['r'].dropna()
    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year)

    r = df['volume_spike_r'].dropna()
    strategy_return = np.exp(r.sum()) - 1
    profit_factor = r[r > 0].sum() / r[r < 0].abs().sum()
    sharpe_ratio = (r.mean() / r.std()) * np.sqrt(bars_per_year)

    print(f"Buy and Hold Return: {bh_return:.2%}, Sharpe Ratio: {bh_sharpe:.2f}")
    print(f"Strategy Return: {strategy_return:.2%}, Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")

    wf_signal = walkforward_vs(df, interval=INTERVAL)
    wf_signal = pd.Series(wf_signal, index=df.index)
    df['wf_r'] = apply_slippage(wf_signal, df['r'])
    wf_pf = df['wf_r'][df['wf_r'] > 0].sum() / df['wf_r'][df['wf_r'] < 0].abs().sum()
    print(f"Walk-Forward PF: {wf_pf:.2f}")

    plt.style.use("dark_background")
    plt.title("In-Sample vs Walk-Forward Volume Spike Momentum (SPY, 1d)")
    plt.plot(df['r'].cumsum(), label='Buy and Hold')
    plt.plot(df['volume_spike_r'].cumsum(), label='In-Sample')
    plt.plot(df['wf_r'].cumsum(), label='Walk-Forward')
    plt.ylabel('Cumulative Log Return')
    plt.legend()
    plt.show()
