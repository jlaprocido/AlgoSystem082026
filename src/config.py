import os

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

load_dotenv()  # reads the .env file into environment variables

STOCK_UNIVERSE = ["SPY", "AAPL", "GOOG"]

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_API_SECRET"]

# explicit and visible on purpose -- flipping this to False is the one line that turns on
# real order placement against real money, so it should never be buried in a default argument
ALPACA_PAPER = True


def get_alpaca_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_alpaca_trading_client() -> TradingClient:
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)