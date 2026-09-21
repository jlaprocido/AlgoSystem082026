from src.config import get_alpaca_trading_client
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading.run_daily import check_risk_limits

# Separate entrypoint from run_daily.py -- meant to run every 1-2 hours during market hours,
# not once a day. Exists specifically because a leveraged position (see aapl_sma.LEVERAGE_MULTIPLIER)
# can move fast enough intraday to trigger an Alpaca-forced margin-call liquidation long before
# run_daily's next scheduled check would ever see it. This never opens a new position or changes
# the strategy's target -- it only ever checks the existing risk limits and flattens if breached.


def run() -> None:
    trading_client = get_alpaca_trading_client()
    symbol = aapl_sma.SYMBOL

    if rm.is_halted():
        print("Already halted -- nothing to check.")
        return

    if not rm.check_market_open(trading_client):
        print("Market is closed -- nothing to do.")
        return

    if check_risk_limits(trading_client, symbol):
        print("Risk limits OK.")


if __name__ == "__main__":
    run()
