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
3. Copy `.env.example` to `.env` and fill in your real Alpaca API key/secret (required) and, optionally, an `NTFY_TOPIC` for push notifications — see `.env.example` for details on each. `.env` is git-ignored — never commit real credentials. Running via GitHub Actions instead of locally uses the same values, stored as repo Secrets rather than a `.env` file (see "Automation" below).

## Project Structure

```
src/
  config.py           # loads .env, builds the shared Alpaca clients (get_alpaca_client for data,
                       # get_alpaca_trading_client for orders), the ALPACA_PAPER paper/live flag,
                       # and the optional NTFY_TOPIC notification setting
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
                            # runs once per trading day near market open, scheduled by
                            # .github/workflows/run_daily.yml (see "Automation" below)
    eod_summary.py           # separate entrypoint, runs once after market close: sends a daily
                             # PnL + portfolio-stats notification (eod_summary.yml)
    intraday_check.py        # separate entrypoint, runs ~hourly during market hours: the fast
                             # circuit breaker leverage needs (intraday_check.yml)
  risk/
    risk_manager.py         # market-hours check, max-drawdown kill switch (persisted halt requiring
                             # manual risk_manager.clear_halt()), daily loss limit (self-clearing),
                             # flatten_position()
  dashboard/
    build_dashboard.py      # renders data/orders/trade_log.csv + live Alpaca account/portfolio
                             # data into a single static index.html (no server, no JS) --
                             # published to GitHub Pages as the last step of every workflow
  notifications/
    notifier.py             # send_notification(): push via ntfy.sh (plain HTTPS POST, no account
                             # needed). Optional -- config is read lazily, so nothing else breaks
                             # if it's left unconfigured
  utils/                # (empty for now)

data/                   # tracked in git -- see .gitignore's negated patterns and the
                        # "Automation" section below for why (ephemeral GitHub Actions runners)
  orders/trade_log.csv  # append-only log of every rebalance order run_daily.py submits
  risk/halt_state.json         # present only when the max-drawdown kill switch has tripped
  risk/daily_loss_state.json   # same-day dedup so intraday_check.py doesn't re-notify hourly
  risk/eod_summary_state.json  # same-day dedup for eod_summary.py's DST double-scheduling

public/                 # src/dashboard/build_dashboard.py's output -- gitignored, never
                        # committed, exists only transiently on the runner before Pages upload

.github/workflows/      # run_daily.yml, eod_summary.yml, intraday_check.yml -- see "Automation" below

tests/                  # NOTE: this is a strategy research/prototyping area, not pytest unit tests
  bar_permute.py         # Monte Carlo permutation testing utility shared by every strategy below
  donchian/
    donchian.py            # Donchian channel breakout: core strategy, in-sample vs. walk-forward
    insample_donchian_mcpt.py    # permutation test: is the in-sample result just overfitting?
    walkforward_donchian_mcpt.py # permutation test: is the walk-forward result statistically real?
  sma/
    sma.py                 # 2-SMA crossover strategy, with annualized Sharpe ratio and profit factor
    insample_sma_mcpt.py         # permutation test for the SMA in-sample result
    walkforward_sma_mcpt.py      # permutation test for the walk-forward result
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

The first strategy graduated from `tests/sma/` into live (currently **paper**) execution. Three entrypoints, each scheduled by its own GitHub Actions workflow — see "Automation" below for how and when:

- `python -m src.trading.run_daily` — meant to run once per trading day near market open. Order of operations: is the kill switch already tripped? → is the market even open? → has max drawdown breached? → has today's loss limit breached? → compute today's signal from fresh bars → if the signal doesn't actually imply a different position than the one currently held, do nothing → otherwise size and submit a marketable-limit rebalance order, wait for it to fill, log it.
- `python -m src.trading.eod_summary` — a separate entrypoint, meant to run once after market close: sends a notification with today's equity, PnL, drawdown, and position size.
- `python -m src.trading.intraday_check` — meant to run every 1-2 hours *during* market hours, not once a day. Shares `run_daily.py`'s `check_risk_limits()` (same drawdown/daily-loss checks, same flatten-and-log-and-notify behavior) but never computes a signal or opens a new position — it exists purely as a faster circuit breaker. See "Leverage" below for why this exists.

**Risk controls** (`src/risk/risk_manager.py`):
- **Max drawdown kill switch**: flattens the position and writes `data/risk/halt_state.json`, which blocks every future run until `risk_manager.clear_halt()` is called manually after reviewing what happened — deliberately does not auto-resume, since a large drawdown should get a human's attention, not just time passing.
- **Daily loss limit**: flattens for the rest of *that calendar day only*, then clears itself automatically the next trading day — a single bad day is normal variance in a way a large drawdown isn't.
- **Market-hours check**, so it never trades against stale after-hours quotes.
- Both breach checks live in `run_daily.py`'s `check_risk_limits()`, shared with `intraday_check.py` rather than duplicated — see "Leverage" below for why a second, more frequent caller of this same function exists at all.

**Notifications** (`src/notifications/notifier.py`, optional): a push via [ntfy.sh](https://ntfy.sh) (a plain HTTPS POST to a topic you pick, read via the ntfy app) fires on every order placed, on each of the four conditions above, and on the end-of-day summary. Started as email-to-SMS (Gmail SMTP → a carrier's gateway address), but two different gateways (AT&T's `txt.att.net`, then a third-party alternative) both silently failed to deliver — email relay failures happen *asynchronously* (a bounce email arrives back at the sender, sometimes minutes later), so a script has no way to detect them at send time at all. ntfy's plain synchronous HTTP response fixes that: a delivery failure raises immediately, in the same process, instead of arriving as an email bounce after the script has already exited. A notification failure is always non-fatal either way — it never blocks the actual trading/risk logic (see `run_daily.py`'s `notify()` wrapper).

**Position sizing**: `TARGET_ALLOCATION_PCT` in `src/strategy/aapl_sma.py` (currently `1.0`, i.e. all-in) is a fraction of account equity rather than a fixed dollar/share amount — the same mechanism will support running several strategies off one account later by giving each a smaller slice.

**Leverage**: `LEVERAGE_MULTIPLIER` in `src/strategy/aapl_sma.py` is currently `2.0` (2x overnight Reg T margin — this strategy always holds positions across multiple days, so the *intraday* 4x day-trading buying power some accounts get is never actually applicable here, regardless of what it's set to). `executor.get_target_shares` computes the target as `equity * allocation_pct * leverage_multiplier` explicitly, rather than reading `account.buying_power`/`regt_buying_power` directly — those reflect *remaining* capacity after any existing position rather than the intended total target, and Alpaca's own `account.multiplier` can read `4` even on a small paper account (it simulates a >$25k pattern-day-trader account regardless of actual equity; a real live account this size would not get that multiplier at all). Losses scale with leverage exactly as much as gains do — this is *why* `intraday_check.py` exists: without it, a fast intraday move on a 2x position could trigger an Alpaca-forced margin-call liquidation hours before `run_daily.py`'s next scheduled check would ever see it. `MAX_DRAWDOWN_PCT`/`MAX_DAILY_LOSS_PCT` stay valid as equity-percentage limits regardless of leverage, but a levered position hits them faster for the same underlying price move. Margin interest on the borrowed portion is also a real, ongoing cost that isn't modeled anywhere in `apply_slippage` or the backtests.

**A known simplification worth knowing about**: only whole shares are traded (no fractional/`notional` orders), and price/equity are rechecked live on every run, so the exact share count bought/sold can vary slightly day to day even when nothing strategic changed — this is why `run_daily.py` explicitly skips trading when the signal hasn't actually flipped, rather than re-sizing to a fresh target every run.

## Automation (GitHub Actions)

Three workflows in `.github/workflows/` (`run_daily.yml`, `eod_summary.yml`, `intraday_check.yml`) schedule the three entrypoints above, each also runnable on demand via `workflow_dispatch`. Requires three repo secrets: `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `NTFY_TOPIC`.

**Scheduling around DST without timezone-aware cron**: GitHub's `schedule:` trigger is UTC-only, and US/Eastern flips between UTC-4 (EDT) and UTC-5 (EST) across the year. Rather than hand-adjusting the cron twice a year, `run_daily`/`eod_summary` each schedule *both* UTC equivalents of their target ET time. The "wrong" one of the two either finds the market closed (clean early exit) or — for `run_daily` — finds the signal already matches the held position (the signal-unchanged skip) and no-ops; for `eod_summary`, which has no such natural guard, a small same-day dedup state file (`data/risk/eod_summary_state.json`) makes the second firing a silent no-op instead of a duplicate notification. `intraday_check` runs hourly across a wider UTC band (14:15-20:15) that covers market hours in both DST states, with the same tolerant just-print-and-exit behavior outside actual market hours.

**Ephemeral-runner state persistence**: every scheduled run starts from a fresh `git checkout` — nothing written to disk (the trade log, halt state) would survive to the next run otherwise. Each workflow's last step commits `data/orders/trade_log.csv` and anything under `data/risk/` back to the repo (`git diff --cached --quiet` guards against an empty commit when nothing changed). This required un-ignoring those specific files in `.gitignore`, which still ignores every other CSV/JSON by default. Getting this right surfaced a real, previously-invisible bug: `.gitignore` does **not** support trailing inline comments — a `#` anywhere but the start of a line is read as a literal part of the pattern, not a comment. `data/risk/*.json  # some comment` and `*.csv  # some comment` had silently matched nothing since the day they were written, meaning those ignore rules had never actually been active (harmless by luck, since the only files that ever landed there were the ones meant to be tracked anyway — but any stray CSV or JSON would have been trackable too, which was never the intent). Fixed by moving every comment onto its own line.

**Same-day duplicate-notification guards**: two small state files, both self-clearing by design (checked against `dt.date.today()`, so a new day naturally invalidates them with no cleanup needed) — `eod_summary_state.json` (above) and `data/risk/daily_loss_state.json`, which stops `intraday_check.py` from re-flattening (harmlessly) and re-notifying every single hourly check on a day where the daily-loss limit stays breached. The max-drawdown breach doesn't need an equivalent, since its halt already persists via `risk_manager.is_halted()`.

## Dashboard (GitHub Pages)

`src/dashboard/build_dashboard.py` renders a single static `index.html` (dark theme, no JavaScript, no external assets — everything, including the equity curve, is inline SVG/CSS) from `data/orders/trade_log.csv` plus Alpaca's live account/portfolio-history endpoints: current equity, today's PnL, drawdown from peak, annualized Sharpe ratio, position size, a halted-status banner when relevant, an equity curve, and a recent-activity table. No database — the CSV and Alpaca's own API are the only sources of truth, matching the rest of this system's design. Sharpe uses the same `(mean / std) * sqrt(bars_per_year)` convention as every strategy file in `tests/`, computed from Alpaca's daily portfolio-history equity curve rather than a backtest's return column, and renders as "N/A" rather than a misleading number when there isn't enough history yet or equity hasn't moved at all.

It's a **build step, not a server**: every one of the three workflows (`run_daily`, `eod_summary`, `intraday_check`) runs it as its last step and publishes the result via `actions/upload-pages-artifact` + `actions/deploy-pages`, so the page refreshes on whatever cadence the workflow that happened to run last dictates — up to roughly hourly during market hours via `intraday_check`. The generated `public/` directory is never committed to the repo (gitignored) — it only exists transiently on the runner between generation and upload.

**One manual step required** (can't be done via a file change): in the repo's Settings → Pages, set **Source** to **"GitHub Actions"** (not the older branch-based option) — this is what makes the `actions/deploy-pages` step have somewhere to publish to. After that, the workflows handle everything else.

## Next Steps: Cloud VM

A cloud VM remains the planned move for if/when this grows into intraday strategies, at which point once-an-hour `intraday_check` cadence and GitHub's scheduling imprecision (documented several-minute delays, occasional skips under load) stop being good enough. The trading code itself needs no changes to move (`git clone` + recreate `.env` + `pip install -r requirements.txt`) — only the scheduling layer (`cron` with the VM's timezone set to `America/New_York`, instead of GitHub Actions), and the dashboard would need to become a persistent Flask/similar server run as a `systemd` service rather than a static-site build step, since a VM doesn't have GitHub Pages' free static hosting built in the way this repo does.

One thing to watch if research/backtest scripts ever run at scale on a VM: yfinance is occasionally rate-limited from datacenter IP ranges (see "Data Sources" above). Not expected to matter for the live AAPL SMA path itself, since its daily data pull already routes through Alpaca.
