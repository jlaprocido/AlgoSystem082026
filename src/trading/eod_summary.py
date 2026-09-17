import datetime as dt
import json
from pathlib import Path

from src.config import get_alpaca_trading_client
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading import executor
from src.trading.run_daily import notify
from src.utils.scheduling import in_time_window

# separate entrypoint from run_daily.py -- meant to run once after market close, not at open

RUN_HOUR, RUN_MINUTE = 16, 0  # America/Chicago -- see src/utils/scheduling.py

STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "risk" / "eod_summary_state.json"


def _already_sent_today() -> bool:
    if not STATE_PATH.exists():
        return False
    return json.loads(STATE_PATH.read_text()).get("last_sent_date") == dt.date.today().isoformat()


def _mark_sent_today() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"last_sent_date": dt.date.today().isoformat()}))


def run() -> None:
    if not in_time_window(RUN_HOUR, RUN_MINUTE):
        print(f"Outside the scheduled run window ({RUN_HOUR}:{RUN_MINUTE:02d} America/Chicago) -- skipping.")
        return

    # a manual workflow_dispatch on top of the real scheduled run is still possible, so this
    # same-day dedup guard stays as a safety net even with a single daily cron entry
    if _already_sent_today():
        print("EOD summary already sent today -- skipping.")
        return

    trading_client = get_alpaca_trading_client()
    symbol = aapl_sma.SYMBOL

    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    last_equity = float(account.last_equity)  # type: ignore[reportAttributeAccessIssue]
    daily_pnl_pct = (equity - last_equity) / last_equity if last_equity > 0 else 0.0
    daily_pnl_dollars = equity - last_equity

    # max_drawdown_pct=1.0 means this can never actually "breach" -- reusing check_max_drawdown
    # purely for the current drawdown-from-peak number it already computes, read-only
    _, drawdown_pct = rm.check_max_drawdown(trading_client, max_drawdown_pct=1.0)
    current_shares = executor.get_current_shares(trading_client, symbol)

    # total PnL since the strategy's own first trade, not since the account was funded --
    # the account can sit flat for a while before the first real BUY, and that idle stretch
    # isn't the strategy "performing," so it shouldn't be counted as part of its return
    strategy_start = executor.find_strategy_start_date()
    total_pnl_pct = total_pnl_dollars = None
    if strategy_start:
        dates, equity_history = rm.get_real_equity_history(trading_client)
        start_equity = next((e for d, e in zip(dates, equity_history) if d >= strategy_start), None)
        if start_equity:
            total_pnl_dollars = equity - start_equity
            total_pnl_pct = equity / start_equity - 1

    message = (
        f"{symbol} EOD: equity = ${equity:,.2f} ({daily_pnl_pct:+.2%}, ${daily_pnl_dollars:+,.2f} today), "
        f"drawdown = {drawdown_pct:.2%} from peak, position = {current_shares} shares"
    )
    if total_pnl_pct is not None:
        message += f", total PnL since {strategy_start} = {total_pnl_pct:+.2%} (${total_pnl_dollars:+,.2f})"

    print(message)
    notify(message)
    _mark_sent_today()


if __name__ == "__main__":
    run()
