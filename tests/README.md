# Strategy Research

Despite the folder name, this isn't a `pytest` unit-test suite — it's where trading strategies get prototyped, backtested, and stress-tested before (eventually) graduating into `src/strategy/` for live use. Each strategy has its own subfolder with a runnable `__main__` block you can execute directly (e.g. `python tests/mean_reversion/mean_reversion.py`).

## Core concepts used across every strategy here

**In-sample vs. walk-forward.** An in-sample result picks the "best" parameter (lookback, z-score, window, etc.) by testing every candidate on the full dataset, then evaluates performance on that *same* dataset — which means the number you get is a best-case, likely overfit result, not a fair estimate of real performance. A walk-forward result instead re-optimizes on a rolling training window and only ever trades the *next*, unseen period with whatever parameter won on the data before it — much closer to how the strategy would actually behave live. Every strategy file here computes and plots both, so you can see the gap between them.

**Monte Carlo Permutation Testing (MCPT)**, done in `bar_permute.py`. `get_permutation()` takes a real OHLC series and generates a randomized-but-statistically-similar fake version of it (it shuffles the relative bar-to-bar moves while preserving the same overall volatility/return characteristics). The `insample_*_mcpt.py` / `walkforward_*_mcpt.py` scripts run a strategy's optimizer against hundreds of these fake permutations and check how often a *random* dataset would have produced a result as good as the real one. That fraction is a pseudo-p-value: **under ~1% is a good sign the edge is real; over ~5% means the "edge" is probably just data-mining bias** (you'd have found an equally good "strategy" on pure noise almost as often).

**Slippage / trading costs**, applied via `src/backtest/costs.py`'s `apply_slippage()`. Alpaca charges 0% commission, but every real trade still crosses the bid-ask spread — `apply_slippage` charges a cost proportional to how much the position size changed (a full flip from long to short costs double a simple entry, since it's really two trades). Not every strategy file has this wired in yet; `mean_reversion.py` does.

## Files

- **`bar_permute.py`** — the permutation-generation utility shared by every MCPT script below. Its own `__main__` block is a standalone demo (real vs. permuted return statistics for one or two symbols), not something other files import.

- **`donchian/`** — Donchian channel breakout (go long on a new N-bar high, short on a new N-bar low).
  - `donchian.py` — `donchian_breakout()` (signal), `optimize_donchian()` (in-sample lookback search), `walkforward_donch()` (rolling re-optimization). The `__main__` block plots in-sample vs. walk-forward cumulative return.
  - `insample_donchian_mcpt.py` — MCPT against the in-sample result, to check if the "best lookback" is a real edge or noise.
  - `walkforward_donchian_mcpt.py` — MCPT against the walk-forward result instead — a stricter, more honest test since walk-forward is already less prone to overfitting than in-sample.

- **`sma/`** — moving-average crossover strategies.
  - `sma.py` — classic 2-SMA crossover (long when fast MA > slow MA), with an annualized Sharpe ratio (scaled by `BAR_CONFIG`-style bar frequency logic inline) and profit factor.
  - `3sma.py` — 3-SMA variant: long only when fast > medium > slow are all aligned bullish, flat otherwise.

- **`mean_reversion/`** — Bollinger-Band mean reversion (go long when price falls below its own SMA by more than N standard deviations, short when it rises above).
  - `mean_reversion.py` — `mean_reversion()` (signal), `optimize_mean_reversion()` (in-sample z-score search), `walkforward_mean_reversion()` (rolling re-optimization). Uses the `INTERVAL`/`BAR_CONFIG` pattern (see root `README.md`) and applies slippage costs via `apply_slippage()`. The `__main__` block plots buy-and-hold, in-sample, and walk-forward cumulative return together.
  - `insample_mean_reversion_mcpt.py` — MCPT against the in-sample z-score result.

## A note on data ranges

Several `__main__` blocks and MCPT scripts hardcode specific start dates (e.g. `2020, 8, 1` for Alpaca-sourced intraday data, `2016, 1, 1` for yfinance-sourced daily data). These aren't arbitrary — see the "Data Sources" section in the root `README.md` for why: Alpaca's free IEX feed has no history before ~2020-07-27, and yfinance's intraday data is capped at the last 7-8 days (1-minute) or ~60 days (5m/15m/30m/1h) but has deep daily history. Copying a script to test a different date range or interval means checking whether the source (`source="yfinance"` vs `"alpaca"`) still makes sense for that range.
