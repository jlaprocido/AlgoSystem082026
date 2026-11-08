"""The generic strategy runner. One code path for every strategy and both asset classes.

    run(name)    -> risk checks -> pull bars -> strategy function -> target weights -> orders
    check(name)  -> risk checks only (the fast circuit breaker; never opens a position)

Everything asset-specific is behind `strategy.asset` (src/assets.py); everything strategy-
specific is behind `strategy.weights()` (src/strategy/). Scheduling is external: cron-job.org
dispatches a workflow at each strategy's own interval.
"""
import datetime as dt

import pandas as pd

from src.assets import INTERVAL_SECONDS
from src.notifications import notifier
from src.risk import risk_manager as rm
from src.strategy.registry import Strategy, get_strategy
from src.trading import executor

MAX_DRAWDOWN_PCT = 0.15     # account equity from its peak -- the global kill switch
REBALANCE_BAND_PCT = 0.05   # skip rebalances smaller than this fraction of the target position
STALE_STOCK_DAYS = 4        # a long weekend/holiday is the normal worst case for stocks


def notify(message: str) -> None:
    # a notification failure (missing config, network hiccup, etc.) must never take down or
    # interrupt the actual trading/risk logic -- this is always the last, best-effort step
    try:
        notifier.send_notification(message)
    except Exception as e:
        print(f"Notification failed (non-fatal): {e}")


def get_trading_client(strategy: Strategy):
    """The Alpaca account this strategy trades in: stocks and crypto are separate accounts."""
    return strategy.asset.trading_client()


def label(strategy: Strategy) -> str:
    return f"{strategy.name} ({', '.join(strategy.symbols)})"


def load_ohlcv(strategy: Strategy, today: dt.date | None = None) -> dict[str, pd.DataFrame]:
    """Recent bars per symbol, trimmed to the timestamps every symbol has, with a staleness guard."""
    today = today or dt.date.today()
    asset = strategy.asset
    raw = {}
    for sym in strategy.symbols:
        df = asset.get_bars(sym, today - dt.timedelta(days=strategy.lookback_days), today + dt.timedelta(days=1),
                            strategy.interval)
        # yfinance can hand back a placeholder row for the current day (volume present, OHLC all
        # NaN) before the day's data has posted -- a signal computed on it would be silently wrong
        raw[sym] = df.dropna(subset=["close"]).set_index("timestamp")[["open", "high", "low", "close", "volume"]]

    common = raw[strategy.symbols[0]].index
    for df in raw.values():
        common = common.intersection(df.index)
    ohlcv = {sym: df.loc[common] for sym, df in raw.items()}

    newest = common[-1]
    age = (pd.Timestamp.now(tz="UTC") - newest).total_seconds()
    max_age = STALE_STOCK_DAYS * 86400 if asset.name == "stock" else 3 * INTERVAL_SECONDS[strategy.interval]
    if age > max_age:
        raise ValueError(f"Latest usable bar for {label(strategy)} is from {newest}, {age / 3600:.1f}h old "
                         f"-- data looks stale, refusing to trade on it.")
    return ohlcv


def check_risk_limits(trading_client, strategy: Strategy) -> bool:
    """Returns True if trading should proceed. On a breach, flattens (and, for a drawdown breach,
    halts everything), logs it, notifies, and returns False.

    Shared between run() and check(): the latter is the fast circuit breaker a leveraged position
    needs, since a fast move between two scheduled runs could otherwise be liquidated by Alpaca
    before we ever saw it.
    """
    asset = strategy.asset
    first = strategy.symbols[0]

    # PER ACCOUNT: this account's drawdown flattens every strategy in it and halts until a human clears it
    dd_breached, drawdown_pct = rm.check_max_drawdown(trading_client, MAX_DRAWDOWN_PCT)
    if dd_breached:
        print(f"Max drawdown breached ({drawdown_pct:.2%} >= {MAX_DRAWDOWN_PCT:.2%}) -- flattening the {asset.name} account and halting it.")
        rm.flatten_all(trading_client)
        rm.set_halted(f"Max drawdown {drawdown_pct:.2%} breached limit {MAX_DRAWDOWN_PCT:.2%}", asset.name)
        executor.log_trade(None, first, strategy.name, None, note=f"max_drawdown_breach_{drawdown_pct:.2%}")
        notify(f"{strategy.name} bot: MAX DRAWDOWN BREACH ({drawdown_pct:.2%}) -- every position in the {asset.name} account flattened, halted until manually cleared.")
        return False

    # PER-STRATEGY: this strategy's own daily move limits and same-day memory
    level = rm.get_daily_loss_level(strategy.name)
    if level == "flattened":
        print("Already flattened for today's move -- staying quiet.")
        return False

    move_pct = min(rm.get_position_move_today(trading_client, asset.position_symbol(s)) for s in strategy.symbols)
    if strategy.flatten_move_pct is not None and move_pct <= -strategy.flatten_move_pct:
        print(f"{strategy.name} down {move_pct:.2%} today (limit -{strategy.flatten_move_pct:.2%}) -- flattening for today only.")
        for sym in strategy.symbols:
            rm.flatten_position(trading_client, asset.position_symbol(sym))
        rm.set_daily_loss_level(strategy.name, "flattened")
        executor.log_trade(None, first, strategy.name, None, note=f"daily_loss_flatten_{move_pct:.2%}")
        notify(f"{strategy.name} bot: down {move_pct:.2%} today -- position flattened for today, resumes tomorrow.")
        return False

    if level == "reduced":
        print("Already cut to 1x for today's move -- staying quiet.")
        return False

    if strategy.reduce_move_pct is not None and move_pct <= -strategy.reduce_move_pct:
        reduce_to_1x(trading_client, strategy, move_pct)
        return False

    return True


def reduce_to_1x(trading_client, strategy: Strategy, move_pct: float) -> None:
    print(f"{strategy.name} down {move_pct:.2%} today (limit -{strategy.reduce_move_pct:.2%}) -- cutting to 1x for today only.")
    asset = strategy.asset
    equity = float(trading_client.get_account().equity)
    cut = []
    for sym in strategy.symbols:
        current = executor.get_current_qty(trading_client, asset, sym)
        if current <= 0:
            continue
        target = executor.get_target_qty(equity, asset, sym, 1.0, strategy.allocation_pct)
        order = None
        if target < current:  # only ever sells down, never adds
            order = executor.submit_rebalance_order(
                trading_client, asset, sym, strategy.name, target, current, id_suffix="reduce", interval=strategy.interval
            )
            if order is not None:
                order = executor.reconcile_fill(trading_client, order.id)
        cut.append(f"{sym} {current:g} -> {target:g}")
        if order is not None:
            executor.log_trade(order, sym, strategy.name, 1)

    rm.set_daily_loss_level(strategy.name, "reduced")
    executor.log_trade(None, strategy.symbols[0], strategy.name, None, note=f"daily_loss_reduce_{move_pct:.2%}")
    notify(f"{strategy.name} bot: down {move_pct:.2%} today -- cut to 1x ({'; '.join(cut) or 'nothing held'}), re-levers next bar.")


def run(name: str, dry_run: bool = False) -> None:
    strategy = get_strategy(name)
    asset = strategy.asset
    first = strategy.symbols[0]
    if strategy.allocation_pct <= 0:
        print(f"{strategy.name} has allocation_pct=0 (research-only) -- give it an allocation in the registry to trade it.")
        return
    trading_client = get_trading_client(strategy)

    if rm.is_halted(asset.name):
        print(f"Halted (max drawdown previously breached in the {asset.name} account) -- run risk_manager.clear_halt('{asset.name}') after review.")
        if not dry_run:
            executor.log_trade(None, first, strategy.name, None, note="halted")
            notify(f"{strategy.name} bot: still halted from a prior max-drawdown breach in the {asset.name} account. Needs manual review/clear_halt('{asset.name}').")
        return

    if not asset.is_open(trading_client):
        print("Market is closed -- nothing to do.")
        if not dry_run:
            executor.log_trade(None, first, strategy.name, None, note="market_closed")
            notify(f"{strategy.name} bot: ran while market was closed, nothing to do.")
        return

    if dry_run:
        # the real risk check can flatten positions, so a dry run only reports the numbers
        _, dd = rm.check_max_drawdown(trading_client, 1.0)
        moves = {s: rm.get_position_move_today(trading_client, asset.position_symbol(s)) for s in strategy.symbols}
        print(f"[dry run] risk check skipped (it can sell). drawdown={dd:.2%}, today's move per symbol={moves}")
    elif not check_risk_limits(trading_client, strategy):
        return

    ohlcv = load_ohlcv(strategy)
    last_weights = strategy.weights(ohlcv).iloc[-1].fillna(0.0)
    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    buying_power = asset.buying_power(account)

    # plan every symbol first, then trade sells before buys so a rotation frees cash first
    plan = []
    for sym in strategy.symbols:
        weight = float(last_weights.get(sym, 0.0))
        current = executor.get_current_qty(trading_client, asset, sym)
        if 0 < current and asset.dust_usd and current * asset.get_quote(sym)[0] < asset.dust_usd:
            current = 0.0  # fee leftovers from a previous sell, not a real position
        target = executor.get_target_qty(equity, asset, sym, weight, strategy.allocation_pct, current, buying_power)
        plan.append((sym, weight, current, target))
    plan.sort(key=lambda p: p[3] - p[2])

    for sym, weight, current, target in plan:
        signal = int(weight > 0)
        # a rebalance band: while staying long, ignore small drifts (e.g. 1-2 shares as equity
        # moves) -- opening or closing a position (either side zero) always trades
        within_band = current > 0 and target > 0 and abs(target - current) / target < REBALANCE_BAND_PCT
        if target == current or within_band:
            print(f"{sym}: target unchanged ({target:g}, {'long' if signal else 'flat'}) -- no trade needed.")
            if not dry_run:
                executor.log_trade(None, sym, strategy.name, signal, note="signal_unchanged")
                notify(f"{strategy.name} bot: check-in -- {sym} signal {'long' if signal else 'flat'}, holding {current:g}, no trade needed.")
            continue

        if dry_run:
            print(f"[dry run] {sym}: weight={weight:g} current={current:g} target={target:g} -> would "
                  f"{'BUY' if target > current else 'SELL'} {abs(target - current):g}")
            continue

        order = executor.submit_rebalance_order(
            trading_client, asset, sym, strategy.name, target, current, interval=strategy.interval
        )
        if order is not None:
            order = executor.reconcile_fill(trading_client, order.id)
            notify(
                f"{strategy.name} bot: {order.side.value.upper()} {order.qty} {sym}, status={order.status.value}, "  # type: ignore[reportAttributeAccessIssue]
                f"avg_price={order.filled_avg_price or order.limit_price}"  # type: ignore[reportAttributeAccessIssue]
            )
        executor.log_trade(order, sym, strategy.name, signal)
        print(f"{sym}: weight={weight:g}, current={current:g}, target={target:g}, order={'none' if order is None else order.status.value}")


def check(name: str) -> None:
    """Risk checks only: never computes a signal or opens a position."""
    strategy = get_strategy(name)
    trading_client = get_trading_client(strategy)

    if rm.is_halted(strategy.asset.name):
        print("Already halted -- nothing to check.")
        return
    if not strategy.asset.is_open(trading_client):
        print("Market is closed -- nothing to do.")
        return
    if check_risk_limits(trading_client, strategy):
        print("Risk limits OK.")
