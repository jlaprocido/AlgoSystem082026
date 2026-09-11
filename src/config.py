import os

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

load_dotenv()  # reads the .env file into environment variables

STOCK_UNIVERSE = ["SPY", "AAPL", "GOOG"]

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_API_SECRET"]

# push notifications via ntfy.sh (free, no account) -- see src/notifications/notifier.py.
# Replaced email-to-SMS after two different carrier/gateway domains both silently failed to
# deliver -- email relay failures happen asynchronously (a bounce email arrives later), so a
# script can't detect them at send time at all. ntfy is a plain synchronous HTTPS POST instead.
#
# optional (unlike the Alpaca keys above): this file is imported by every research/backtest
# script via market_data.py, and none of those need notifications configured to run, so a
# missing value here is checked lazily inside send_notification() rather than crashing every import
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

# explicit and visible on purpose -- flipping this to False is the one line that turns on
# real order placement against real money, so it should never be buried in a default argument
ALPACA_PAPER = True


def get_alpaca_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_alpaca_trading_client() -> TradingClient:
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)