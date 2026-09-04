Outlined below is an algorthimic trading system with the goal of making a profit trading US equities / ETFs at a reasonable return while providing live metrics to an html dashboard and daily updates to investors.

Plan
1. Create data pulling file that creates a pandas dataframe of a universe of stocks from strategy file. Take in Alpaca and yfinance
2. strategy file that runs backtest, outlines what to trade, presents backtesting results
3. orders file that files orders with Alpaca, saves record of those orders to .csv or other saving system
4. risk management file that limits portfolio to a maximum loss and drawdown before selling all stocks / stocks at loss
5. dashboard file that shows current results on html website, ytd, full year, and by stock comparison
6. notification file that sends messages to my phone with daily results

Extra
- is there a way to host this data in the cloud?
- can I personalize the dashboard per investor?
    - can I model in what it would look like for those investors given fees?

## Setup

1. `pip install -r requirements.txt`
2. `pip install -e .` — installs `src` and `tests` as importable packages (see `pyproject.toml`), so `from src.data.market_data import get_bars` and `from tests.donchian.donchian import ...` work no matter where a script is run from.
3. Copy `.env.example` to `.env` and fill in your real Alpaca API key/secret. `.env` is git-ignored — never commit real credentials.

## Project Structure

```
src/
  config.py           # loads .env, builds the shared Alpaca client (get_alpaca_client)
  bar_config.py        # BAR_CONFIG: per-interval constants (annualization, walk-forward retrain cadence)
  data/
    market_data.py      # get_bars(): unified yfinance/Alpaca data fetcher, same output shape either way
  backtest/
    costs.py            # apply_slippage(): shared trading-cost model, used by every strategy backtest
  strategy/             # (empty for now — reserved for the "live" version of a chosen strategy)
  trading/              # (empty for now — reserved for order placement against Alpaca)
  risk/                 # (empty for now — reserved for the risk gate: max loss/drawdown checks)
  dashboard/            # (empty for now — reserved for the results dashboard)
  notifications/        # (empty for now — reserved for daily result alerts)
  utils/                # (empty for now)

tests/                  # NOTE: this is a strategy research/prototyping area, not pytest unit tests
  bar_permute.py         # Monte Carlo permutation testing utility shared by every strategy below
  donchian/
    donchian.py            # Donchian channel breakout: core strategy, in-sample vs. walk-forward
    insample_donchian_mcpt.py    # permutation test: is the in-sample result just overfitting?
    walkforward_donchian_mcpt.py # permutation test: is the walk-forward result statistically real?
  sma/
    sma.py                 # 2-SMA crossover strategy, with annualized Sharpe ratio and profit factor
    3sma.py                # 3-SMA variant: long only when fast > med > slow are all aligned
  mean_reversion/
    mean_reversion.py            # Bollinger-Band mean reversion: core strategy, in-sample vs. walk-forward, with slippage modeled
    insample_mean_reversion_mcpt.py  # permutation test for the mean-reversion in-sample result
```

See `tests/README.md` for more detail on the strategy research area and what Monte Carlo permutation testing (MCPT) is actually checking for.

## Data Sources: yfinance vs. Alpaca

`get_bars(symbol, start, end, source="yfinance"|"alpaca", interval=...)` in `src/data/market_data.py` is the single entry point for both data sources — it always returns the same shape (`timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume`), so strategy code never needs to know which source it's using. Choosing the right source matters a lot, though, because the two have very different limitations:

### yfinance (`source="yfinance"`)
- **No API key needed** — zero setup, works immediately.
- **Daily/weekly/monthly bars (`interval="1d"`, etc.)**: full history, often going back decades. This is its main strength.
- **1-minute bars (`interval="1m"`)**: Yahoo only serves roughly the **last 7-8 days**. Request anything older and you'll get an empty or truncated result — not a bug, a hard limit on their end.
- **Other intraday intervals (`"5m"`, `"15m"`, `"30m"`, `"1h"`, etc.)**: Yahoo allows a longer window than 1-minute, but still only roughly the **last 60 days**. Same failure mode if you go further back.
- Prices come back split/dividend-adjusted (`auto_adjust=True`).
- Read-only — there's no way to place trades through yfinance. It's a data source only.

### Alpaca (`source="alpaca"`)
- **Requires an API key/secret** (see Setup above) — free tier is enough for this project's data needs.
- Historical data here is pulled from the **IEX feed** (`feed='iex'` in `get_alpaca_bars`), which is free but has its own limitation: **no historical coverage before roughly 2020-07-27**, regardless of the interval you ask for. Requesting daily bars from 2016 on Alpaca will come back empty — this isn't a bug, it's the feed's actual data horizon (confirmed by testing: minute-bar requests going back to 2018/2020-01 silently start returning data only from 2020-07-27 onward).
- Once you're inside that window, though, **intraday granularity is available across the full multi-year range** — 1-minute, 5-minute, 15-minute, 30-minute, hourly, all with years of history, not just a few days/months like yfinance.
- `adjustment='all'` is used, so both stock splits and dividends are adjusted for — important since a live stock split (e.g. AAPL's 4-for-1 split on 2020-08-31) would otherwise show up as a fake ~75% price crash in the raw series.
- Alpaca is also the only source that matters for **live/paper trading** later — `src/trading/` will eventually place real orders through the same Alpaca account this data comes from.

### When to use which

| Situation | Use |
|---|---|
| Daily-bar backtest that needs history before ~2020 | **yfinance** (`source="yfinance"`) |
| Any intraday backtest (`1m`/`5m`/`15m`/`30m`/`1h`) needing more than a couple months of history | **Alpaca** (`source="alpaca"`) — but nothing before ~2020-07-27 |
| Quick daily check, no `.env`/API key set up yet | **yfinance** — zero config |
| Anything that will eventually connect to live/paper order execution | **Alpaca** — it's the only source backed by a real broker account |

If you need years of intraday history *and* it must predate mid-2020, neither free source covers that — you'd need a paid data vendor, which is out of scope for this project.

## The `INTERVAL` / `BAR_CONFIG` pattern

Several strategy files (see `tests/mean_reversion/mean_reversion.py` for the clearest example) define one `INTERVAL = "1m"` constant at the top of the file. Everything that's *mechanically* derived from bar frequency — Sharpe ratio annualization, walk-forward retrain cadence (`train_lookback`/`train_step`) — is looked up from `src/bar_config.py`'s `BAR_CONFIG[INTERVAL]` dict instead of being hardcoded. Flipping `INTERVAL` to `"1d"`, `"1h"`, `"5m"`, `"15m"`, or `"30m"` updates all of that automatically.

What does **not** auto-scale: things like the rolling `window` size or a strategy's parameter-sweep range (e.g. the z-score range in `mean_reversion.py`) are strategy-specific choices, not something derivable from interval alone — "20 bars" means something very different as 20 minutes vs. 20 days, so those still need to be tuned by hand whenever you change `INTERVAL`.
