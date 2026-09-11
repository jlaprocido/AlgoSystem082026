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
  config.py           # loads .env, builds the shared Alpaca clients (get_alpaca_client for data,
                       # get_alpaca_trading_client for orders) and the ALPACA_PAPER paper/live flag
  bar_config.py        # BAR_CONFIG: per-interval constants (annualization, walk-forward retrain cadence)
  data/
    market_data.py      # get_bars(): unified yfinance/Alpaca data fetcher, same output shape either way
  backtest/
    costs.py            # apply_slippage(): shared trading-cost model, used by every strategy backtest
  strategy/
    aapl_sma.py            # the live, chosen version of tests/sma/sma.py's crossover for AAPL --
                            # given today's bars, what's today's position? (no backtest/optimizer code)
  trading/
    executor.py            # order sizing, marketable-limit submission (with client_order_id
                            # idempotency), fill reconciliation, and CSV trade logging
    run_daily.py            # entrypoint: risk checks -> compute signal -> rebalance -> log -> notify.
                            # meant to run once per trading day (scheduling is external -- cron /
                            # Task Scheduler / the `schedule` skill, not built into this repo)
    eod_summary.py           # separate entrypoint, meant to run once after market close: sends a
                             # daily PnL + portfolio-stats notification
  risk/
    risk_manager.py         # market-hours check, max-drawdown kill switch (persisted halt requiring
                             # manual risk_manager.clear_halt()), daily loss limit (self-clearing),
                             # flatten_position()
  dashboard/            # (empty for now — reserved for the results dashboard; data/orders/trade_log.csv
                        # is written in a shape meant to be read from here)
  notifications/
    notifier.py             # send_notification(): push via ntfy.sh (plain HTTPS POST, no account
                             # needed). Optional -- config is read lazily, so nothing else breaks
                             # if it's left unconfigured
  utils/                # (empty for now)

data/
  orders/trade_log.csv  # append-only log of every rebalance order run_daily.py submits (git-ignored)
  risk/halt_state.json  # present only when the max-drawdown kill switch has tripped (git-ignored)

tests/                  # NOTE: this is a strategy research/prototyping area, not pytest unit tests
  bar_permute.py         # Monte Carlo permutation testing utility shared by every strategy below
  donchian/
    donchian.py            # Donchian channel breakout: core strategy, in-sample vs. walk-forward
    insample_donchian_mcpt.py    # permutation test: is the in-sample result just overfitting?
    walkforward_donchian_mcpt.py # permutation test: is the walk-forward result statistically real?
  sma/
    sma.py                 # 2-SMA crossover strategy, with annualized Sharpe ratio and profit factor
    insample_sma_mcpt.py         # permutation test for the SMA in-sample result
  three_sma/
    three_sma.py                 # 3-SMA variant: long only when fast > med > slow are all aligned
    insample_three_sma_mcpt.py   # permutation test for the 3-SMA in-sample result
  mean_reversion/
    mean_reversion.py            # Bollinger-Band mean reversion: core strategy, in-sample vs. walk-forward, with slippage modeled
    insample_mean_reversion_mcpt.py  # permutation test for the mean-reversion in-sample result
  volume_spike/
    volume_spike.py               # volume-spike momentum: long after an unusually large, up-close volume bar
    insample_volume_spike_mcpt.py # permutation test for the volume-spike in-sample result (volume-aware permutation)
  vol_regime/
    vol_regime.py                 # Donchian breakout gated to only fire when ATR is expanding vs. its own baseline
    insample_vol_regime_mcpt.py   # permutation test for the vol-regime in-sample result
```

See `tests/README.md` for more detail on the strategy research area and what Monte Carlo permutation testing (MCPT) is actually checking for.

## Data Sources: yfinance vs. Alpaca

`get_bars(symbol, start, end, interval=...)` in `src/data/market_data.py` is the single entry point for both data sources — it always returns the same shape (`timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume`), so strategy code never needs to know which source it's using, and **doesn't choose one**: the source is derived entirely from `interval` and `start`. The rule: **Alpaca whenever the whole requested range is covered by its IEX feed (`start >= 2020-07-27`), yfinance otherwise.** That means intraday bars always come from Alpaca (yfinance can't serve enough intraday history to be useful here anyway) or raise if `start` predates the IEX horizon, while daily-and-coarser bars (`"1d"`, `"1wk"`, `"1mo"`) go to Alpaca for any range starting on/after 2020-07-27 and fall back to yfinance only when older history is actually needed. This mapping exists because the two sources have very different limitations:

### yfinance (used when history before 2020-07-27 is needed)
- **No API key needed** — zero setup, works immediately.
- **Daily/weekly/monthly bars**: full history, often going back decades — this is the only reason it's used at all now that Alpaca handles everything from 2020-07-27 onward.
- Intraday bars are deliberately never requested from yfinance here — Yahoo only serves roughly the **last 7-8 days** for 1-minute bars and **~60 days** for 5m/15m/30m/1h, which isn't enough history for the walk-forward/MCPT testing this project does.
- Prices come back split/dividend-adjusted (`auto_adjust=True`).
- Read-only — there's no way to place trades through yfinance. It's a data source only.
- Worth knowing if this ever runs on a cloud server instead of a home connection: Yahoo occasionally rate-limits or blocks requests from datacenter IP ranges more aggressively than residential ones. Not a problem seen yet, but a real, documented risk of yfinance specifically — one more reason to prefer Alpaca whenever the date range allows it.

### Alpaca (used whenever the full requested range is on/after 2020-07-27, any interval)
- **Requires an API key/secret** (see Setup above) — free tier is enough for this project's data needs.
- Historical data here is pulled from the **IEX feed** (`feed='iex'` in `get_alpaca_bars`), which is free but has its own limitation: **no historical coverage before 2020-07-27**. Without a guard, requesting an earlier start date wouldn't fail — it would silently come back with bars starting at 2020-07-27 instead of your actual requested range (confirmed by testing: minute-bar requests going back to 2018/2020-01 silently truncate). `get_bars` raises a `ValueError` instead of allowing that silent truncation for intraday requests — see "Guardrails" below. (Daily+ requests before the horizon don't need a guard; they just route to yfinance instead.)
- Once you're inside that window, **intraday granularity is available across the full multi-year range** — 1-minute, 5-minute, 15-minute, 30-minute, hourly, all with years of history, not just a few days/months like yfinance.
- `adjustment='all'` is used, so both stock splits and dividends are adjusted for — important since a live stock split (e.g. AAPL's 4-for-1 split on 2020-08-31) would otherwise show up as a fake ~75% price crash in the raw series.
- Alpaca is also the source `src/trading/` actually places live/paper orders through — using it for data too (whenever possible) means the live trading path and its data path share one dependency instead of two.

### Guardrails

`get_bars` raises `ValueError` up front — before ever hitting the network — instead of letting either source's limitation silently corrupt a backtest:

| Situation | What happens |
|---|---|
| Intraday interval (`1m`/`5m`/`15m`/`30m`/`1h`) with `start` before 2020-07-27 | Raises immediately, naming the exact cutoff. Without this, Alpaca would silently start the series at 2020-07-27, and a strategy backtesting "2018-2024" would actually only be testing 2020-2024 with no indication anything was cut. |
| Alpaca returns zero bars for a valid request (bad symbol, market holiday range, etc.) | `get_alpaca_bars` raises `ValueError` naming the symbol/date range/interval, rather than returning an empty frame that would silently break every rolling calculation downstream. |

If you need years of intraday history *and* it must predate mid-2020, neither free source covers that — you'd need a paid data vendor, which is out of scope for this project. A request spanning both sides of 2020-07-27 (e.g. `start=2016`) is served entirely from yfinance rather than being stitched across both sources — this avoids a discontinuity in the series from two vendors' slightly different adjustment methodologies, at the cost of not using Alpaca for the recent portion of a long-history request. If you need to force a specific source for some other reason, call `get_yfinance_bars` / `get_alpaca_bars` directly instead of `get_bars`.

## The `INTERVAL` / `BAR_CONFIG` pattern

Several strategy files (see `tests/mean_reversion/mean_reversion.py` for the clearest example) define one `INTERVAL = "1m"` constant at the top of the file. Everything that's *mechanically* derived from bar frequency — Sharpe ratio annualization, walk-forward retrain cadence (`train_lookback`/`train_step`) — is looked up from `src/bar_config.py`'s `BAR_CONFIG[INTERVAL]` dict instead of being hardcoded. Flipping `INTERVAL` to `"1d"`, `"1h"`, `"5m"`, `"15m"`, or `"30m"` updates all of that automatically.

What does **not** auto-scale: things like the rolling `window` size or a strategy's parameter-sweep range (e.g. the z-score range in `mean_reversion.py`) are strategy-specific choices, not something derivable from interval alone — "20 bars" means something very different as 20 minutes vs. 20 days, so those still need to be tuned by hand whenever you change `INTERVAL`.

## Live Trading (AAPL SMA)

The first strategy graduated from `tests/sma/` into live (currently **paper**) execution. Two entrypoints, meant to run on a schedule — not automated yet, see "Next Steps" below:

- `python -m src.trading.run_daily` — meant to run once per trading day near market open. Order of operations: is the kill switch already tripped? → is the market even open? → has max drawdown breached? → has today's loss limit breached? → compute today's signal from fresh bars → if the signal doesn't actually imply a different position than the one currently held, do nothing → otherwise size and submit a marketable-limit rebalance order, wait for it to fill, log it.
- `python -m src.trading.eod_summary` — a separate entrypoint, meant to run once after market close: sends a notification with today's equity, PnL, drawdown, and position size.

**Risk controls** (`src/risk/risk_manager.py`):
- **Max drawdown kill switch**: flattens the position and writes `data/risk/halt_state.json`, which blocks every future run until `risk_manager.clear_halt()` is called manually after reviewing what happened — deliberately does not auto-resume, since a large drawdown should get a human's attention, not just time passing.
- **Daily loss limit**: flattens for the rest of *that calendar day only*, then clears itself automatically the next trading day — a single bad day is normal variance in a way a large drawdown isn't.
- **Market-hours check**, so it never trades against stale after-hours quotes.

**Notifications** (`src/notifications/notifier.py`, optional): a push via [ntfy.sh](https://ntfy.sh) (a plain HTTPS POST to a topic you pick, read via the ntfy app) fires on every order placed, on each of the four conditions above, and on the end-of-day summary. Started as email-to-SMS (Gmail SMTP → a carrier's gateway address), but two different gateways (AT&T's `txt.att.net`, then a third-party alternative) both silently failed to deliver — email relay failures happen *asynchronously* (a bounce email arrives back at the sender, sometimes minutes later), so a script has no way to detect them at send time at all. ntfy's plain synchronous HTTP response fixes that: a delivery failure raises immediately, in the same process, instead of arriving as an email bounce after the script has already exited. A notification failure is always non-fatal either way — it never blocks the actual trading/risk logic (see `run_daily.py`'s `notify()` wrapper).

**Position sizing**: `TARGET_ALLOCATION_PCT` in `src/strategy/aapl_sma.py` (currently `1.0`, i.e. all-in) is a fraction of account equity rather than a fixed dollar/share amount — the same mechanism will support running several strategies off one account later by giving each a smaller slice.

**A known simplification worth knowing about**: only whole shares are traded (no fractional/`notional` orders), and price/equity are rechecked live on every run, so the exact share count bought/sold can vary slightly day to day even when nothing strategic changed — this is why `run_daily.py` explicitly skips trading when the signal hasn't actually flipped, rather than re-sizing to a fresh target every run.

## Next Steps: Dashboard & Cloud Hosting

Not built yet — planned once paper trading has run long enough to trust the mechanics above:

1. **A local dashboard** (`src/dashboard/`, still empty): a small Flask app reading `data/orders/trade_log.csv` plus Alpaca's live account/portfolio-history endpoints, rendering one auto-refreshing page (a stats header + a recent-trades table). No database needed — the CSV and Alpaca's own API are the only sources of truth.
2. **Move both the scheduled bot and the dashboard to a small cloud VM** (~$4-6/month — DigitalOcean, Linode, Vultr, or AWS Lightsail are all fine) once the dashboard exists and paper trading is confirmed working correctly. This is what actually makes the system "always on": running `run_daily.py`/`eod_summary.py` from Windows Task Scheduler and hosting the dashboard locally both require this machine to be powered on — a small VM removes that dependency for both at once. The move needs no changes to the trading logic itself (`git clone` + recreate `.env` + `pip install -r requirements.txt`), just infrastructure: Linux `cron` in place of Task Scheduler (set the VM's timezone to `America/New_York` to avoid doing UTC/DST arithmetic by hand), and the dashboard running as a persistent `systemd` service — not a bare terminal process that dies on disconnect — behind at least basic password auth, since it displays real account data.
3. One thing to watch after that move: yfinance is occasionally rate-limited from datacenter IP ranges (see "Data Sources" above). Not expected to matter for the live AAPL SMA path specifically, since its daily data pull already routes through Alpaca — but worth knowing if any research/backtest scripts end up running at scale on the same VM.
