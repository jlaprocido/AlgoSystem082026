# Strategy Research

Despite the folder name, this isn't a `pytest` unit-test suite — it's where trading strategies get prototyped, backtested, and stress-tested before (eventually) graduating into `src/strategy/` for live use. Each strategy has its own subfolder with a runnable `__main__` block you can execute directly (e.g. `python tests/mean_reversion/mean_reversion.py`).

## Core concepts used across every strategy here

**In-sample vs. walk-forward.** An in-sample result picks the "best" parameter (lookback, z-score, window, etc.) by testing every candidate on the full dataset, then evaluates performance on that *same* dataset — which means the number you get is a best-case, likely overfit result, not a fair estimate of real performance. A walk-forward result instead re-optimizes on a rolling training window and only ever trades the *next*, unseen period with whatever parameter won on the data before it — much closer to how the strategy would actually behave live. Every strategy file here computes and plots both, so you can see the gap between them.

**Monte Carlo Permutation Testing (MCPT)**, done in `bar_permute.py`. `get_permutation()` takes a real OHLC series and generates a randomized-but-statistically-similar fake version of it (it shuffles the relative bar-to-bar moves while preserving the same overall volatility/return characteristics). The `insample_*_mcpt.py` / `walkforward_*_mcpt.py` scripts run a strategy's optimizer against hundreds of these fake permutations and check how often a *random* dataset would have produced a result as good as the real one. That fraction is a pseudo-p-value: **under ~1% is a good sign the edge is real; over ~5% means the "edge" is probably just data-mining bias** (you'd have found an equally good "strategy" on pure noise almost as often).

**Slippage / trading costs**, applied via `src/backtest/costs.py`'s `apply_slippage()`. Alpaca charges 0% commission, but every real trade still crosses the bid-ask spread — `apply_slippage` charges a cost proportional to how much the position size changed (a full flip from long to short costs double a simple entry, since it's really two trades). Every strategy file below has this wired in, including their MCPT/walk-forward scripts.

## Files

- **`bar_permute.py`** — the permutation-generation utility shared by every MCPT script below. Its own `__main__` block is a standalone demo (real vs. permuted return statistics for one or two symbols), not something other files import.

- **`donchian/`** — Donchian channel breakout (go long on a new N-bar high, short on a new N-bar low).
  - `donchian.py` — `donchian_breakout()` (signal), `optimize_donchian()` (in-sample lookback search), `walkforward_donch()` (rolling re-optimization). The `__main__` block plots in-sample vs. walk-forward cumulative return.
  - `insample_donchian_mcpt.py` — MCPT against the in-sample result, to check if the "best lookback" is a real edge or noise.
  - `walkforward_donchian_mcpt.py` — MCPT against the walk-forward result instead — a stricter, more honest test since walk-forward is already less prone to overfitting than in-sample.

- **`sma/`** — 2-SMA crossover (long when fast MA > slow MA), with annualized Sharpe ratio and profit factor.
  - `sma.py` — `sma_strategy()`, `optimize_sma_strategy()` (in-sample window search), `walkforward_sma()` (rolling re-optimization). Uses the `INTERVAL`/`BAR_CONFIG` pattern and applies slippage via `apply_slippage()`.
  - `insample_sma_mcpt.py` — MCPT against the in-sample window-search result.
  - `walkforward_sma_mcpt.py` — MCPT against the walk-forward result. Note the data slice pulled here is *twice* `BAR_CONFIG`'s `train_lookback` (8 years, not 4) — the training window alone would otherwise consume the entire slice, leaving nothing to actually walk forward across.

- **`three_sma/`** — 3-SMA variant: long only when fast > medium > slow are all aligned bullish, flat otherwise.
  - `three_sma.py` — `three_sma_strategy()`, `optimize_three_sma_strategy()`.
  - `insample_three_sma_mcpt.py` — MCPT against the in-sample result.

- **`mean_reversion/`** — Bollinger-Band mean reversion (go long when price falls below its own SMA by more than N standard deviations, short when it rises above).
  - `mean_reversion.py` — `mean_reversion()` (signal), `optimize_mean_reversion()` (in-sample z-score search), `walkforward_mean_reversion()` (rolling re-optimization). Uses the `INTERVAL`/`BAR_CONFIG` pattern (see root `README.md`) and applies slippage costs via `apply_slippage()`. The `__main__` block plots buy-and-hold, in-sample, and walk-forward cumulative return together.
  - `insample_mean_reversion_mcpt.py` — MCPT against the in-sample z-score result.

- **`volume_spike/`** — volume-spike momentum: long for the next bar when this bar's volume is an unusual multiple of its own trailing average *and* it closed up — a bet on "unusual participation precedes follow-through," a different signal family from the trend/mean-reversion strategies above.
  - `volume_spike.py` — `volume_spike_strategy()`, `optimize_volume_spike_strategy()` (grid search over lookback × multiplier, with a `min_trades` floor so the optimizer can't pick a degenerate, near-zero-trade corner of the grid), `walkforward_vs()`.
  - `insample_volume_spike_mcpt.py` — MCPT against the in-sample result. This is the one strategy where the permutation itself matters: `get_permutation()` shuffles `volume` alongside the intrabar price shuffle (see `bar_permute.py`) so a bar's volume stays paired with its own range, since this strategy reads `df['volume']` directly.

- **`vol_regime/`** — Donchian-style breakout, but only taken when ATR is expanding relative to its own rolling baseline — a regime filter on top of trend-following, on the theory that breakouts in a dead, range-bound market are usually just noise.
  - `vol_regime.py` — `true_range()`, `vol_regime_strategy()`, `optimize_vol_regime_strategy()`, `walkforward_vol_regime()`.
  - `insample_vol_regime_mcpt.py` — MCPT against the in-sample result. Uses only OHLC, so the plain (non-volume) permutation is fine here.

## A note on data ranges

Several `__main__` blocks and MCPT scripts hardcode specific start dates (e.g. `2020, 8, 1` for intraday intervals, `2016, 1, 1` for daily). These aren't arbitrary — see the "Data Sources" section in the root `README.md`: `get_bars()` picks its source from `interval` *and* `start` together — Alpaca whenever the whole requested range is on/after 2020-07-27 (any interval), yfinance otherwise (needed for daily+ history predating that). Alpaca's free IEX feed has no history before 2020-07-27 at all, so `get_bars` raises immediately if you ask for an earlier *intraday* start rather than letting it silently truncate (daily+ requests before that date just route to yfinance instead, no guard needed). Copying a script to test a different date range mainly matters for intraday intervals: that start still needs to clear the 2020-07-27 floor.
