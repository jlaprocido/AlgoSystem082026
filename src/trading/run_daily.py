import datetime as dt

from src.config import get_alpaca_client, get_alpaca_trading_client
from src.data.market_data import get_bars
from src.notifications import notifier
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading import executor
from src.utils.scheduling import in_time_window

RUN_HOUR, RUN_MINUTE = 9, 45  # America/Chicago -- see src/utils/scheduling.py

MAX_DRAWDOWN_PCT = 0.15  # from peak account equity -- breach requires manual risk_manager.clear_halt()
MAX_DAILY_LOSS_PCT = 0.05  # from yesterday's close -- self-clears the next trading day
STRATEGY_NAME = "sma"


def notify(message: str) -> None:
    # a notification failure (missing config, network hiccup, etc.) must never take down or
    # interrupt the actual trading/risk logic -- this is always the last, best-effort step
    try:
        notifier.send_notification(message)
    except Exception as e:
        print(f"Notification failed (non-fatal): {e}")


def check_risk_limits(trading_client, symbol: str) -> bool:
    """Returns True if trading should proceed. On a breach, flattens the position (and, for a
    drawdown breach, sets the persistent halt), logs it, notifies, and returns False.

    Shared between run_daily.py (once a day, at open) and intraday_check.py (every 1-2 hours
    during market hours) -- the latter exists specifically because this cadence is the one
    thing standing between a leveraged position and an Alpaca-forced margin-call liquidation
    that our once-a-day check would never see in time to react to.
    """
    dd_breached, drawdown_pct = rm.check_max_drawdown(trading_client, MAX_DRAWDOWN_PCT)
    if dd_breached:
        print(f"Max drawdown breached ({drawdown_pct:.2%} >= {MAX_DRAWDOWN_PCT:.2%}) -- flattening and halting.")
        rm.flatten_position(trading_client, symbol)
        rm.set_halted(f"Max drawdown {drawdown_pct:.2%} breached limit {MAX_DRAWDOWN_PCT:.2%}")
        executor.log_trade(None, symbol, STRATEGY_NAME, None, note=f"max_drawdown_breach_{drawdown_pct:.2%}")
        notify(f"{symbol} bot: MAX DRAWDOWN BREACH ({drawdown_pct:.2%}) -- position flattened, bot halted until manually cleared.")
        return False

    loss_breached, daily_pnl_pct = rm.check_daily_loss(trading_client, MAX_DAILY_LOSS_PCT)
    if loss_breached:
        if rm.is_daily_loss_handled_today():
            print(f"Daily loss limit still breached ({daily_pnl_pct:.2%}) -- already flattened/notified today, staying quiet.")
            return False

        print(f"Daily loss limit breached ({daily_pnl_pct:.2%} <= -{MAX_DAILY_LOSS_PCT:.2%}) -- flattening for today only.")
        rm.flatten_position(trading_client, symbol)
        rm.mark_daily_loss_handled_today()
        executor.log_trade(None, symbol, STRATEGY_NAME, None, note=f"daily_loss_breach_{daily_pnl_pct:.2%}")
        notify(f"{symbol} bot: daily loss limit breached ({daily_pnl_pct:.2%}) -- position flattened for today, resumes next trading day.")
        return False

    return True


def run() -> None:
    if not in_time_window(RUN_HOUR, RUN_MINUTE):
        print(f"Outside the scheduled run window ({RUN_HOUR}:{RUN_MINUTE:02d} America/Chicago) -- skipping.")
        return

    trading_client = get_alpaca_trading_client()
    data_client = get_alpaca_client()
    symbol = aapl_sma.SYMBOL

    if rm.is_halted():
        print("Halted (max drawdown previously breached) -- run risk_manager.clear_halt() after review.")
        executor.log_trade(None, symbol, STRATEGY_NAME, None, note="halted")
        notify(f"{symbol} bot: still halted from a prior max-drawdown breach. Needs manual review/clear_halt().")
        return

    if not rm.check_market_open(trading_client):
        print("Market is closed -- nothing to do.")
        executor.log_trade(None, symbol, STRATEGY_NAME, None, note="market_closed")
        notify(f"{symbol} bot: ran while market was closed, nothing to do.")
        return

    if not check_risk_limits(trading_client, symbol):
        return

    df = get_bars(symbol, dt.date.today() - dt.timedelta(days=365), dt.date.today() + dt.timedelta(days=1), interval="1d")

    # yfinance can hand back a placeholder row for the current day (volume present, OHLC all
    # NaN) before the day's data has actually posted -- silently computing a signal on that
    # would default to a flat/wrong position without any indication anything was off
    df = df.dropna(subset=["close"])
    latest_bar_age_days = (dt.date.today() - df['timestamp'].iloc[-1].date()).days
    if latest_bar_age_days > 4:  # a long weekend/holiday is the normal worst case
        raise ValueError(
            f"Latest usable {symbol} bar is from {df['timestamp'].iloc[-1].date()}, "
            f"{latest_bar_age_days} days old -- data looks stale, refusing to trade on it."
        )

    signal = aapl_sma.compute_signal(df)
    current_shares = executor.get_current_shares(trading_client, symbol)

    # only trade when the signal actually implies a different position than the one we're
    # already holding -- recomputing and re-truing-up a target every day (even while flat-to-flat
    # or long-to-long) would generate small, pointless trades purely from price/equity drift,
    # which the backtest's slippage model never accounts for (it only charges cost on signal.diff())
    if bool(signal) == (current_shares > 0):
        print(f"Signal unchanged ({'long' if signal else 'flat'}) -- holding {current_shares} shares, no trade needed.")
        executor.log_trade(None, symbol, STRATEGY_NAME, signal, note="signal_unchanged")
        notify(f"{symbol} bot: daily check-in -- signal {'long' if signal else 'flat'}, holding {current_shares} shares, no trade needed.")
        return

    target_shares = executor.get_target_shares(
        trading_client, data_client, symbol, signal, aapl_sma.TARGET_ALLOCATION_PCT, aapl_sma.LEVERAGE_MULTIPLIER
    )

    order = executor.submit_rebalance_order(
        trading_client, data_client, symbol, STRATEGY_NAME, signal, target_shares, current_shares
    )

    if order is not None:
        order = executor.reconcile_fill(trading_client, order.id)
        side = order.side.value.upper()  # type: ignore[reportAttributeAccessIssue]
        notify(
            f"{symbol} bot: {side} {order.qty} shares, status={order.status.value}, "  # type: ignore[reportAttributeAccessIssue]
            f"avg_price={order.filled_avg_price or order.limit_price}"  # type: ignore[reportAttributeAccessIssue]
        )

    executor.log_trade(order, symbol, STRATEGY_NAME, signal)
    print(f"Signal={signal}, current={current_shares}, target={target_shares}, order={'none' if order is None else order.status.value}")


if __name__ == "__main__":
    run()
