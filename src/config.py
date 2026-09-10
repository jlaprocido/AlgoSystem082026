import os

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

load_dotenv()  # reads the .env file into environment variables

STOCK_UNIVERSE = ["SPY", "AAPL", "GOOG"]

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_API_SECRET"]

# email-to-SMS notifications (free, no app required) -- see src/notifications/notifier.py
# optional (unlike the Alpaca keys above): this file is imported by every research/backtest
# script via market_data.py, and none of those need notifications configured to run, so a
# missing value here is checked lazily inside send_sms() rather than crashing every import
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
NOTIFY_PHONE_NUMBER = os.environ.get("NOTIFY_PHONE_NUMBER")  # digits only, e.g. "5551234567"
NOTIFY_CARRIER = os.environ.get("NOTIFY_CARRIER", "att")

# explicit and visible on purpose -- flipping this to False is the one line that turns on
# real order placement against real money, so it should never be buried in a default argument
ALPACA_PAPER = True


def get_alpaca_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_alpaca_trading_client() -> TradingClient:
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)