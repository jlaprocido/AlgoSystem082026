import os

from dotenv import load_dotenv
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.client import TradingClient

load_dotenv()  # reads the .env file into environment variables

STOCK_UNIVERSE = ["SPY", "AAPL", "GOOG"]

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_API_SECRET"]

# Crypto trades in its OWN Alpaca account (a second paper account with its own key pair). Crypto
# can only be bought with cash, while the AAPL bot borrows to hold 2x, so sharing one account made
# them fight over buying power. Optional: unset means "no crypto account yet" -- the stock bot,
# the lab and the dashboard still work, and a crypto strategy refuses to run (no silent fallback
# to the stock account, which would bring the conflict back). Empty strings count as unset,
# because GitHub passes an unset secret as "".
ALPACA_CRYPTO_API_KEY = os.environ.get("ALPACA_CRYPTO_API_KEY") or None
ALPACA_CRYPTO_SECRET_KEY = os.environ.get("ALPACA_CRYPTO_API_SECRET") or None

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


def get_alpaca_crypto_client() -> CryptoHistoricalDataClient:
    # crypto market data is 24/7; the same API keys work, and crypto data needs no separate feed
    return CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def crypto_account_configured() -> bool:
    return bool(ALPACA_CRYPTO_API_KEY and ALPACA_CRYPTO_SECRET_KEY)


def get_alpaca_crypto_trading_client() -> TradingClient:
    if not crypto_account_configured():
        raise RuntimeError(
            "No crypto account configured. Create a second Alpaca paper account and set "
            "ALPACA_CRYPTO_API_KEY and ALPACA_CRYPTO_API_SECRET (in .env locally, and as repo "
            "secrets for GitHub Actions). Crypto deliberately does not fall back to the stock account."
        )
    return TradingClient(ALPACA_CRYPTO_API_KEY, ALPACA_CRYPTO_SECRET_KEY, paper=ALPACA_PAPER)
