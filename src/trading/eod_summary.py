from src.config import get_alpaca_trading_client
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading import executor
from src.trading.run_daily import notify

# separate entrypoint from run_daily.py -- meant to run once after market close, not at open


def run() -> None:
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

    message = (
        f"{symbol} EOD: equity = ${equity:,.2f} ({daily_pnl_pct:+.2%}, ${daily_pnl_dollars:+,.2f} today), "
        f"drawdown = {drawdown_pct:.2%} from peak, position = {current_shares} shares"
    )
    print(message)
    notify(message)


if __name__ == "__main__":
    run()
