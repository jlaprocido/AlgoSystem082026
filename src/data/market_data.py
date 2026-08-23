import datetime as dt
import pandas as pd
import yfinance as yf

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.config import get_alpaca_client

STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]
ALPACA_TIMEFRAMES = {"1d": TimeFrame.Day, "1m": TimeFrame.Minute, "1h": TimeFrame.Hour, "1wk": TimeFrame.Week, "1mo": TimeFrame.Month
}



def get_yfinance_bars(symbol: str, start: dt.date, end: dt.date, interval: str = "1d") -> pd.DataFrame:
    raw = yf.download(symbol, start=start, end=end, interval=interval, auto_adjust=False)
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


def get_bars(symbol: str, start: dt.date, end: dt.date, source: str="yfinance", interval: str = "1d") -> pd.DataFrame:
    if source == "yfinance":
        return get_yfinance_bars(symbol, start, end, interval)
    elif source == "alpaca":
        client = get_alpaca_client()
        return get_alpaca_bars(client, symbol, start, end, interval)
    else:
        raise ValueError(f"Unknown source: {source}")


if __name__ == "__main__":
    df = get_bars("AAPL", dt.date(2026, 8, 10), dt.date.today()+dt.timedelta(days=1), source="yfinance", interval="1d") 
    print(df)
    df = get_bars("AAPL", dt.date(2020, 1, 1), dt.date.today()+dt.timedelta(days=1), source="alpaca", interval="1m") 
    print(df)

    # yfinance restricts intrraday data to the last 30 days, so we use Alpaca for intraday data
    # Alpaca data only goes back to 2020-03-01, so we use yfinance for daily data before that date