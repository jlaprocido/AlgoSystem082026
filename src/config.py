import os

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient

load_dotenv()  # reads the .env file into environment variables

STOCK_UNIVERSE = ["SPY", "AAPL", "GOOG"]

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_API_SECRET"]

# client function
def get_alpaca_client() -> StockHistoricalDataClient:
    api_key = ALPACA_API_KEY
    secret_key = ALPACA_SECRET_KEY
    return StockHistoricalDataClient(api_key, secret_key)