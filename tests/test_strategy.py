import pandas as pd
import numpy as np
import datetime as dt
from tqdm import tqdm

from src.data.market_data import get_bars, INTRADAY_INTERVALS
from src.backtest.costs import apply_slippage
from src.bar_config import BAR_CONFIG

from tests.sma.sma import sma_strategy, optimize_sma_strategy
from tests.three_sma.three_sma import three_sma_strategy, optimize_three_sma_strategy
from tests.donchian.donchian import donchian_breakout, optimize_donchian
from tests.mean_reversion.mean_reversion import mean_reversion, optimize_mean_reversion
from tests.volume_spike.volume_spike import volume_spike_strategy, optimize_volume_spike_strategy
from tests.vol_regime.vol_regime import vol_regime_strategy, optimize_vol_regime_strategy

# Starter universe spanning mega-cap, mid-cap, small/micro-cap, and a few index/sector ETFs --
# the point isn't full market coverage, it's variety, since an edge is more likely to show up
# in a less efficiently-priced small-cap than in SPY. Swap this out for a bigger list (e.g. a
# CSV of Russell 2000 constituents) once you know a strategy is worth testing more broadly.
UNIVERSE = [
    # mega-cap
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "XOM", "JNJ",
    # mid-cap
    "ETSY", "ROKU", "PINS", "CHWY", "RCL", "DKS", "FIVE", "WSM", "ULTA", "DECK",
    # small/micro-cap and speculative names
    "NPKI", "APLD", "PLUG", "RIOT", "MARA", "SOFI", "UPST", "IONQ", "RKLB", "ACHR", "JOBY", "BBAI",
    # ETFs (index and sector)
    "SPY", "QQQ", "IWM", "XLF", "XLE", "ARKK",
]


def _summarize(bh_r: pd.Series, strategy_r: pd.Series, interval: str) -> dict:
    bh_r = bh_r.dropna()
    strategy_r = strategy_r.dropna()
    bars_per_year = BAR_CONFIG[interval]["bars_per_year"]

    bh_return = np.exp(bh_r.sum()) - 1
    bh_sharpe = (bh_r.mean() / bh_r.std()) * np.sqrt(bars_per_year) if bh_r.std() > 0 else np.nan

    strategy_return = np.exp(strategy_r.sum()) - 1
    gross_loss = strategy_r[strategy_r < 0].abs().sum()
    profit_factor = strategy_r[strategy_r > 0].sum() / gross_loss if gross_loss > 0 else np.nan
    sharpe_ratio = (strategy_r.mean() / strategy_r.std()) * np.sqrt(bars_per_year) if strategy_r.std() > 0 else np.nan

    return {
        "bh_return": bh_return,
        "bh_sharpe": bh_sharpe,
        "strategy_return": strategy_return,
        "sharpe_ratio": sharpe_ratio,
        "profit_factor": profit_factor,
    }


# Each adapter takes a raw OHLCV df and returns (best_params, buy_and_hold_returns, strategy_returns, signal).
# This is the only place that needs to know each strategy's particular function signature --
# scan_universe() below just needs any function shaped like this, which is what makes strategies
# swappable via the STRATEGIES dict. `signal` is returned so scan_universe can count how many
# trades the winning parameters actually produced, on top of the trade counting each strategy's
# own optimizer already does internally to pick those parameters.

def _run_sma(df: pd.DataFrame, interval: str):
    best_windows, _ = optimize_sma_strategy(df, interval=interval)
    fast_window, slow_window = best_windows
    _, _, out_df = sma_strategy(df.copy(), fast_window, slow_window, interval=interval)
    return best_windows, out_df['return'], out_df['strategy_return'], out_df['signal']


def _run_three_sma(df: pd.DataFrame, interval: str):
    best_windows, _ = optimize_three_sma_strategy(df, interval=interval)
    fast_window, med_window, slow_window = best_windows
    _, _, out_df = three_sma_strategy(df.copy(), fast_window, med_window, slow_window, interval=interval)
    return best_windows, out_df['return'], out_df['strategy_return'], out_df['signal']


def _run_donchian(df: pd.DataFrame, interval: str):
    best_lookback, _ = optimize_donchian(df)
    signal = donchian_breakout(df, best_lookback)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    strategy_r = apply_slippage(signal, r)
    return (best_lookback,), r, strategy_r, signal


def _run_mean_reversion(df: pd.DataFrame, interval: str, window: int = 20):
    best_zscore, _ = optimize_mean_reversion(df, window=window, interval=interval, zscore=1)
    signals_df = mean_reversion(df.copy(), window, interval, best_zscore)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    strategy_r = apply_slippage(signals_df['signal'], r)
    return (window, best_zscore), r, strategy_r, signals_df['signal']


def _run_volume_spike(df: pd.DataFrame, interval: str):
    best_params, _ = optimize_volume_spike_strategy(df, interval=interval)
    lookback, multiplier = best_params
    out_df = volume_spike_strategy(df.copy(), lookback, multiplier, interval=interval)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    strategy_r = apply_slippage(out_df['signal'], r)
    return best_params, r, strategy_r, out_df['signal']


def _run_vol_regime(df: pd.DataFrame, interval: str):
    best_params, _ = optimize_vol_regime_strategy(df, interval=interval)
    breakout_lookback, vol_multiplier = best_params
    out_df = vol_regime_strategy(df.copy(), breakout_lookback, vol_multiplier=vol_multiplier, interval=interval)
    r = np.log(df['close']).diff().shift(-1) # type: ignore[reportAttributeAccessIssue]
    strategy_r = apply_slippage(out_df['signal'], r)
    return best_params, r, strategy_r, out_df['signal']


STRATEGIES = {
    "sma": _run_sma,
    "three_sma": _run_three_sma,
    "donchian": _run_donchian,
    "mean_reversion": _run_mean_reversion,
    "volume_spike": _run_volume_spike,
    "vol_regime": _run_vol_regime,
}


def scan_universe(strategy_name: str, universe: list, interval: str = "1d",
                   start: dt.date | None = None, end: dt.date | None = None,
                   min_bars: int = 300, min_trades: int = 20) -> pd.DataFrame:

    if strategy_name not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy_name}'. Choose from: {list(STRATEGIES)}")
    run_fn = STRATEGIES[strategy_name]

    if start is None:
        # match each interval to a start date get_bars won't reject -- see the "Data Sources"
        # section of the root README for why intraday can't reach back before mid-2020
        start = dt.date(2020, 8, 1) if interval in INTRADAY_INTERVALS else dt.date(2016, 1, 1)
    if end is None:
        end = dt.date.today() + dt.timedelta(days=1)

    results = []
    for symbol in tqdm(universe):
        try:
            df = get_bars(symbol, start, end, interval=interval)
        except Exception as e:
            print(f"Skipping {symbol}: could not fetch data ({e})")
            continue

        if len(df) < min_bars:
            print(f"Skipping {symbol}: only {len(df)} bars, need at least {min_bars}")
            continue

        try:
            best_params, bh_r, strategy_r, signal = run_fn(df, interval)
        except Exception as e:
            print(f"Skipping {symbol}: strategy failed ({e})")
            continue

        # a thinly-traded small-cap can hand the optimizer "great" params that only fired a
        # handful of times -- same issue as volume_spike's own optimizer guard, but here it's
        # checking the *winning* params on the *whole* series, not every combo mid-search
        n_trades = int((signal.diff().fillna(0) != 0).sum())
        if n_trades < min_trades:
            print(f"Skipping {symbol}: best params only produced {n_trades} trades, need at least {min_trades}")
            continue

        summary = _summarize(bh_r, strategy_r, interval)
        results.append({"symbol": symbol, "best_params": best_params, "n_trades": n_trades, **summary})

    if not results:
        raise ValueError("No symbols produced usable results -- check the universe, date range, and interval")

    return pd.DataFrame(results).sort_values("sharpe_ratio", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    STRATEGY = "donchian"  # flip to any key in STRATEGIES to switch which strategy is scanned
    INTERVAL = "1d"

    results_df = scan_universe(STRATEGY, UNIVERSE, interval=INTERVAL)

    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")
    print(f"\n{STRATEGY} results across {len(results_df)} symbols (of {len(UNIVERSE)} attempted):")
    print(results_df.to_string(index=False))

    best = results_df.iloc[0]
    print(
        f"\nBest Sharpe Ratio: {best['symbol']} "
        f"(Sharpe {best['sharpe_ratio']:.2f}, Strategy Return {best['strategy_return']:.2%}, "
        f"Profit Factor {best['profit_factor']:.2f}, Best Params {best['best_params']})"
    )
