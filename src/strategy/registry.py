"""The registry: a named, runnable deployment = strategy function + symbols + interval + params.

Adding a strategy = write (or reuse) one function in library.py and add one entry here. Then:

    python -m src.backtest.lab <name>                 # backtest it vs buy-and-hold, any asset class
    python -m src.trading.run_strategy <name>          # run it live (paper) once
    python -m src.trading.run_strategy <name> --dry-run

Rules the engine relies on (checked by tests/unit/test_registry.py):
  - one TRADING strategy (allocation > 0) per symbol (positions are per symbol, so two strategies on BTC would fight)
  - all symbols in one strategy share an asset class (stocks and crypto have different calendars)
  - allocation_pct is the share of account equity this strategy may use; the sum of the
    allocations that trade the same asset class should stay <= 1.0
"""
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from src.assets import asset_for
from src.strategy import aapl_sma, library


@dataclass(frozen=True)
class Strategy:
    name: str
    fn: Callable[..., pd.DataFrame]
    symbols: list[str]
    interval: str                          # decision cadence: how often cron-job.org should run it
    params: dict = field(default_factory=dict)
    allocation_pct: float = 1.0            # fraction of account equity for this strategy's sleeve
    leverage: float = 1.0                  # multiplies weights; crypto stays at 1.0 (no margin)
    reduce_move_pct: float | None = None   # daily drop that cuts the position to 1x (None = never)
    flatten_move_pct: float | None = None  # daily drop that sells everything until tomorrow
    lookback_days: int = 365               # calendar days of history the live run pulls

    @property
    def asset(self):
        return asset_for(self.symbols[0])

    def weights(self, ohlcv: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Target weights as a fraction of the strategy's sleeve: long-only, leverage applied."""
        return (self.fn(ohlcv, **self.params).clip(lower=0.0) * self.leverage)


REGISTRY: dict[str, Strategy] = {s.name: s for s in [
    # the live bot, unchanged in behavior: 5/20 SMA on AAPL, 2x, daily. Constants come from
    # aapl_sma.py so there is still one place to change them.
    Strategy(
        "aapl_sma", library.sma, [aapl_sma.SYMBOL], "1d",
        params={"fast": aapl_sma.FAST_WINDOW, "slow": aapl_sma.SLOW_WINDOW},
        allocation_pct=aapl_sma.TARGET_ALLOCATION_PCT, leverage=aapl_sma.LEVERAGE_MULTIPLIER,
        reduce_move_pct=0.025, flatten_move_pct=0.05, lookback_days=365,
    ),
    # crypto: 1x, 24/7. A 10% daily drop is routine for crypto, so the stock thresholds would
    # flatten it constantly; flatten at -15% instead and never "reduce" (there is no leverage).
    Strategy(
        "btc_sma", library.sma, ["BTC/USD"], "1d",
        params={"fast": 5, "slow": 20}, allocation_pct=0.10,
        flatten_move_pct=0.15, lookback_days=365,
    ),
    Strategy(
        "eth_donchian", library.donchian, ["ETH/USD"], "1d",
        params={"lookback": 20}, allocation_pct=0.10,
        flatten_move_pct=0.15, lookback_days=365,
    ),
    # research-only (allocation 0.0): backtestable with src.backtest.lab, refused by the live
    # engine. Promote one by giving it an allocation once its after-cost backtest beats buy-and-hold.
    Strategy("three_sma", library.three_sma, ["SPY"], "1d", params={"fast": 10, "med": 25, "slow": 50}, allocation_pct=0.0),
    Strategy("mean_reversion", library.mean_reversion, ["SPY"], "1d", params={"window": 20, "zscore": 2.0}, allocation_pct=0.0),
    Strategy("volume_spike", library.volume_spike, ["SPY"], "1d", params={"lookback": 20, "multiplier": 2.0}, allocation_pct=0.0),
    Strategy("vol_regime", library.vol_regime, ["SPY"], "1d", allocation_pct=0.0),
    Strategy("dual_momentum", library.dual_momentum, ["SPY", "EFA", "TLT", "GLD"], "1d",
             params={"lookback": 126}, allocation_pct=0.0),
]}


def get_strategy(name: str) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"Unknown strategy '{name}'. Available: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]
