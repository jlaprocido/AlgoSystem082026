"""Backtest any registered strategy on its own symbols, next to buy-and-hold. Same function the
live engine runs, so the number you see here is the rule you would trade.

    python -m src.backtest.lab btc_sma
    python -m src.backtest.lab btc_sma --symbols ETH/USD --interval 1h --days 90 --bps 25
    python -m src.backtest.lab --all

--symbols swaps the asset (stocks or crypto, never mixed); --interval swaps the bar size.
Costs are per unit of turnover; crypto defaults to 25 bps (Alpaca's taker fee), stocks to 5 bps.
Results assume you trade at the bar's close, the same assumption as the research backtests.
"""
import argparse
import dataclasses
import datetime as dt

import pandas as pd

from src.backtest.portfolio import closes, load_ohlcv, portfolio_returns, summary
from src.strategy.registry import REGISTRY, get_strategy


def backtest(name: str, symbols: list[str] | None = None, interval: str | None = None,
             days: int = 730, bps: float | None = None) -> dict[str, dict]:
    strategy = get_strategy(name)
    if symbols or interval:
        strategy = dataclasses.replace(strategy, symbols=symbols or strategy.symbols,
                                       interval=interval or strategy.interval)
    asset = strategy.asset
    if bps is None:
        bps = 25.0 if asset.name == "crypto" else 5.0

    end = dt.date.today() + dt.timedelta(days=1)
    ohlcv = load_ohlcv(strategy.symbols, end - dt.timedelta(days=days), end, strategy.interval)
    close = closes(ohlcv)
    ppy = asset.bars_per_year[strategy.interval]

    # warm-up: skip the bars before the slowest indicator has any history
    weights = strategy.weights(ohlcv)
    first_valid = weights.index[min(len(weights) - 1, 100)]
    r = portfolio_returns(weights, close, slippage_pct=bps / 10_000).loc[first_valid:]

    rows = {f"{strategy.name} @ {bps:g}bps": summary(r, ppy)}
    for sym in strategy.symbols:
        rows[f"buy&hold {sym}"] = summary(close[sym].pct_change().loc[first_valid:].dropna(), ppy)
    rows["_window"] = {"start": close.loc[first_valid:].index[0].date(), "end": close.index[-1].date(),  # type: ignore[reportAttributeAccessIssue]
                       "bars": len(r)}
    return rows


def show(name: str, rows: dict) -> None:
    window = rows.pop("_window")
    print(f"\n== {name}: {window['start']} to {window['end']} ({window['bars']} bars)")
    out = pd.DataFrame(rows).T
    pd.options.display.float_format = "{:.2f}".format
    print(out.assign(total_return=out.total_return * 100, cagr=out.cagr * 100, max_drawdown=out.max_drawdown * 100)
             .rename(columns={"total_return": "total %", "cagr": "cagr %", "max_drawdown": "maxDD %"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("strategy", nargs="?", choices=sorted(REGISTRY))
    parser.add_argument("--all", action="store_true", help="every registered strategy")
    parser.add_argument("--symbols", nargs="+", help="override the strategy's symbols (e.g. ETH/USD)")
    parser.add_argument("--interval", help="override bar size: 1d, 1h, 30m, 15m, 5m")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--bps", type=float, help="cost per unit of turnover, in basis points")
    args = parser.parse_args()

    names = sorted(REGISTRY) if args.all else [args.strategy]
    if not names[0]:
        parser.error("give a strategy name or --all")
    for name in names:
        show(name, backtest(name, args.symbols, args.interval, args.days, args.bps))


if __name__ == "__main__":
    main()
