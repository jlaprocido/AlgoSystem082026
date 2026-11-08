from src.trading import engine

# Separate entrypoint from run_daily.py -- meant to run every 1-2 hours during market hours,
# not once a day. Exists specifically because a leveraged position (see aapl_sma.LEVERAGE_MULTIPLIER)
# can move fast enough intraday to trigger an Alpaca-forced margin-call liquidation long before
# run_daily's next scheduled check would ever see it. This never opens a new position or changes
# the strategy's target -- it only ever checks the existing risk limits and flattens if breached.
STRATEGY_NAME = "aapl_sma"


def run() -> None:
    engine.check(STRATEGY_NAME)


if __name__ == "__main__":
    run()
