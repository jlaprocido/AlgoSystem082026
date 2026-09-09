import datetime as dt
import pandas as pd
import yfinance as yf

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ALPACA_TIMEFRAMES = {
    "1d": TimeFrame.Day,
    "1m": TimeFrame.Minute,
    "1h": TimeFrame.Hour,
    "5m": TimeFrame(5, TimeFrameUnit.Minute), # type: ignore[reportArgumentType]
    "15m": TimeFrame(15, TimeFrameUnit.Minute), # type: ignore[reportArgumentType]
    "30m": TimeFrame(30, TimeFrameUnit.Minute), # type: ignore[reportArgumentType]
    "1wk": TimeFrame.Week,
    "1mo": TimeFrame.Month
}


from src.config import get_alpaca_client

STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]

# yfinance only serves a few days/months of intraday history, so anything intraday goes to
# Alpaca instead, which has years of intraday coverage -- just not before its IEX feed starts.
INTRADAY_INTERVALS = {"1m", "5m", "15m", "30m", "1h"}
ALPACA_IEX_START = dt.date(2020, 7, 27)


def get_yfinance_bars(symbol: str, start: dt.date, end: dt.date, interval: str = "1d") -> pd.DataFrame:
    raw = yf.download(symbol, start=start, end=end, interval=interval, auto_adjust=True)
    assert raw is not None, "yfinance returned no data"

    # yfinance gives MultiIndex columns when you pass multiple tickers,
    # and Title-Case single-level columns otherwise — normalize both cases
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(columns=str.lower)

    df = raw[STANDARD_COLUMNS].copy()
    df[PRICE_COLS] = df[PRICE_COLS].round(3)
    df.index.name = "timestamp"
    df.index = pd.to_datetime(df.index, utc=True)
    df["symbol"] = symbol
    return df.reset_index()[["timestamp", "symbol", *STANDARD_COLUMNS]]


def get_alpaca_bars(client: StockHistoricalDataClient, symbol: str,
                     start: dt.date, end: dt.date, interval: str = "1d") -> pd.DataFrame:
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=ALPACA_TIMEFRAMES[interval],  # type: ignore[reportArgumentType]
        start=start,                            # type: ignore[reportArgumentType]
        end=end,                                # type: ignore[reportArgumentType]
        adjustment='all',                       # type: ignore[reportArgumentType]
        feed='iex'                              # type: ignore[reportArgumentType]
    )
    bars = client.get_stock_bars(request).df  # MultiIndex: (symbol, timestamp) # type: ignore[reportAttributeAccessIssue]
    if bars.empty:
        raise ValueError(f"Alpaca returned no bars for {symbol} ({start} to {end}, interval={interval})")

    df = bars.reset_index()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    return df[["timestamp", "symbol", *STANDARD_COLUMNS]]


def get_bars(symbol: str, start: dt.date, end: dt.date, interval: str = "1d") -> pd.DataFrame:
    # source is derived from interval, not chosen by the caller -- see the "Data Sources"
    # section of the root README for why intraday and daily+ data need different sources
    if interval not in INTRADAY_INTERVALS:
        return get_yfinance_bars(symbol, start, end, interval)

    if start < ALPACA_IEX_START:
        raise ValueError(
            f"Alpaca's IEX feed (used for intraday data) has no history before {ALPACA_IEX_START}, "
            f"but start={start} was requested for interval={interval}. Without this check, Alpaca "
            f"would silently return bars only from {ALPACA_IEX_START} onward instead of your full "
            f"requested range. Either move start on/after {ALPACA_IEX_START}, or use a daily+ "
            f"interval (e.g. '1d') to pull deeper history from yfinance instead."
        )

    client = get_alpaca_client()
    return get_alpaca_bars(client, symbol, start, end, interval)


if __name__ == "__main__":
    df = get_bars("AAPL", dt.date(2026, 8, 10), dt.date.today()+dt.timedelta(days=1), interval="1d")
    print(df)
    df = get_bars("AAPL", dt.date(2020, 8, 1), dt.date.today()+dt.timedelta(days=1), interval="1m")
    print(df)

    # requesting intraday data from before Alpaca's IEX horizon now fails loudly instead of
    # silently coming back truncated to start at 2020-07-27
    try:
        get_bars("AAPL", dt.date(2018, 1, 1), dt.date.today()+dt.timedelta(days=1), interval="1m")
    except ValueError as e:
        print(f"Expected failure: {e}")