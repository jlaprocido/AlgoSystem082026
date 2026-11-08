"""Asset adapter: everything that differs between stocks and crypto lives here.

A strategy never knows which asset class it is trading. The engine asks the adapter for the
four things that differ:

                     stocks                          crypto
  data               Alpaca IEX / yfinance           Alpaca crypto bars
  quantity           whole shares                    fractional (floored to 6 decimals)
  time in force      DAY (orders expire at close)    GTC (the market never closes)
  trading hours      market clock                    always open
  position symbol    AAPL                            BTCUSD   (orders use "BTC/USD")
  Alpaca account     the stock account               its own crypto account (separate keys)

`asset_for(symbol)` picks the adapter: a "/" in the symbol ("BTC/USD") means crypto.
"""
import datetime as dt
import math

import pandas as pd
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest, StockLatestQuoteRequest
from alpaca.trading.enums import TimeInForce

from src.config import (get_alpaca_client, get_alpaca_crypto_client, get_alpaca_crypto_trading_client,
                        get_alpaca_trading_client)
from src.data.market_data import ALPACA_TIMEFRAMES, STANDARD_COLUMNS, get_bars

# bars per year, for annualizing Sharpe. Stocks trade 252 days x 6.5h; crypto trades every day.
STOCK_BARS_PER_YEAR = {"1d": 252, "1h": 252 * 7, "30m": 252 * 13, "15m": 252 * 26, "5m": 252 * 78}
CRYPTO_BARS_PER_YEAR = {"1d": 365, "1h": 365 * 24, "30m": 365 * 48, "15m": 365 * 96, "5m": 365 * 288}

# the engine treats a bar as stale if its newest bar is older than this many intervals
INTERVAL_SECONDS = {"1d": 86400, "1h": 3600, "30m": 1800, "15m": 900, "5m": 300}


def _valid_quote(symbol: str, bid: float, ask: float) -> tuple[float, float]:
    # a quote with an empty side (e.g. right after a stock close) would size an order off $0
    if bid <= 0 or ask <= 0:
        raise ValueError(f"Latest quote for {symbol} is missing a bid or ask (bid={bid}, ask={ask}).")
    return bid, ask


class StockAsset:
    name = "stock"
    dust_usd = 0.0  # whole shares: there is no fractional leftover
    time_in_force = TimeInForce.DAY
    bars_per_year = STOCK_BARS_PER_YEAR

    def get_bars(self, symbol: str, start: dt.date, end: dt.date, interval: str) -> pd.DataFrame:
        return get_bars(symbol, start, end, interval=interval)

    def trading_client(self):
        return get_alpaca_trading_client()

    def is_open(self, trading_client) -> bool:
        return trading_client.get_clock().is_open

    def get_quote(self, symbol: str) -> tuple[float, float]:
        quote = get_alpaca_client().get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]  # type: ignore[reportAttributeAccessIssue]
        return _valid_quote(symbol, quote.bid_price, quote.ask_price)

    def normalize_qty(self, qty: float) -> int:
        return int(qty)  # whole shares only

    def position_symbol(self, symbol: str) -> str:
        return symbol

    def round_price(self, price: float) -> float:
        return round(price, 2)

    def buying_power(self, account) -> float | None:
        return None  # margin accounts: Alpaca's own check is enough


class CryptoAsset:
    name = "crypto"
    # Alpaca takes the crypto fee out of the coins you receive, so a 0.000376 BTC buy leaves a
    # 0.00037506 position and a full sell leaves ~6e-8 BTC that can never be sold. Positions
    # worth less than this are treated as flat.
    dust_usd = 1.0
    time_in_force = TimeInForce.GTC
    bars_per_year = CRYPTO_BARS_PER_YEAR

    def get_bars(self, symbol: str, start: dt.date, end: dt.date, interval: str) -> pd.DataFrame:
        request = CryptoBarsRequest(
            symbol_or_symbols=symbol, timeframe=ALPACA_TIMEFRAMES[interval],  # type: ignore[reportArgumentType]
            start=start, end=end,  # type: ignore[reportArgumentType]
        )
        bars = get_alpaca_crypto_client().get_crypto_bars(request).df  # type: ignore[reportAttributeAccessIssue]
        if bars.empty:
            raise ValueError(f"Alpaca returned no crypto bars for {symbol} ({start} to {end}, interval={interval})")
        df = bars.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df[["timestamp", "symbol", *STANDARD_COLUMNS]]

    def trading_client(self):
        return get_alpaca_crypto_trading_client()  # raises a clear error if no crypto account is set up

    def is_open(self, trading_client) -> bool:
        return True  # 24/7

    def get_quote(self, symbol: str) -> tuple[float, float]:
        quote = get_alpaca_crypto_client().get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]  # type: ignore[reportAttributeAccessIssue]
        return _valid_quote(symbol, quote.bid_price, quote.ask_price)

    def normalize_qty(self, qty: float) -> float:
        return math.floor(qty * 1e6) / 1e6  # floor so we never ask for more than we can afford

    def position_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "")  # positions come back as BTCUSD, orders use BTC/USD

    def round_price(self, price: float) -> float:
        return round(price, 2) if price >= 1 else round(price, 6)

    def buying_power(self, account) -> float | None:
        # crypto cannot be bought on margin: it needs cash, so the engine caps buys at this
        # number (and a crypto account that spends its cash gets a smaller order, not a rejection)
        return float(account.non_marginable_buying_power)


STOCK = StockAsset()
CRYPTO = CryptoAsset()


def asset_for(symbol: str):
    return CRYPTO if "/" in symbol else STOCK
