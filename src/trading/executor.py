import csv
import time
import datetime as dt
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.models import Order

TRADE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "orders" / "trade_log.csv"
TRADE_LOG_FIELDS = [
    "timestamp", "symbol", "strategy", "signal", "side", "qty", "limit_price",
    "client_order_id", "status", "filled_qty", "filled_avg_price", "filled_at",
]


def get_latest_quote(data_client: StockHistoricalDataClient, symbol: str):
    quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]  # type: ignore[reportAttributeAccessIssue]

    # outside regular trading hours the "latest quote" snapshot can come back with one side
    # empty (e.g. ask_price=0.0 right after close, since no resting ask exists at that instant)
    # -- trading off a $0.00 price would produce a nonsensical order size or limit price, so
    # this fails loudly instead. In practice this should only fire if run_daily runs when
    # check_market_open() would already say the market is closed.
    if quote.bid_price <= 0 or quote.ask_price <= 0:  # type: ignore[reportAttributeAccessIssue]
        raise ValueError(
            f"Latest quote for {symbol} is missing a bid or ask (bid={quote.bid_price}, "  # type: ignore[reportAttributeAccessIssue]
            f"ask={quote.ask_price}) -- likely called outside regular trading hours."  # type: ignore[reportAttributeAccessIssue]
        )
    return quote


def get_target_shares(trading_client: TradingClient, data_client: StockHistoricalDataClient,
                       symbol: str, signal: int, allocation_pct: float, leverage_multiplier: float = 1.0) -> int:
    if signal == 0:
        return 0

    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    quote = get_latest_quote(data_client, symbol)

    # leverage_multiplier sizes off total equity times the leverage factor (e.g. 2.0 for 2x
    # overnight Reg T margin), not off account.buying_power/regt_buying_power directly --
    # those reflect *remaining* capacity after any existing position, and Alpaca's own
    # account.multiplier can read 4 even on a small paper account (it simulates a >$25k
    # pattern-day-trader account regardless of actual equity, which a real live account this
    # size would not get) -- so this computes the intended target explicitly instead of
    # trusting either field to already mean what we want
    target_dollar_exposure = equity * allocation_pct * leverage_multiplier

    # whole shares only -- fractional/notional orders are a simplification left for later,
    # since notional orders on Alpaca are restricted to market orders, not the limit orders used here
    return int(target_dollar_exposure // quote.ask_price)


def get_current_shares(trading_client: TradingClient, symbol: str) -> int:
    try:
        position = trading_client.get_open_position(symbol)
        return int(float(position.qty))  # type: ignore[reportAttributeAccessIssue]
    except APIError as e:
        # matched on the same stable numeric code risk_manager.flatten_position() uses --
        # GET and DELETE /positions/{symbol} return different message text for "no position"
        # ("position does not exist" vs "position not found: AAPL") but share this code
        if e.code == 40410000:
            return 0
        raise


def submit_rebalance_order(trading_client: TradingClient, data_client: StockHistoricalDataClient,
                            symbol: str, strategy: str, signal: int,
                            target_shares: int, current_shares: int) -> Order | None:
    delta = target_shares - current_shares
    if delta == 0:
        return None

    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    qty = abs(delta)

    quote = get_latest_quote(data_client, symbol)
    # marketable limit: through the market enough to fill almost immediately on a liquid name,
    # while still capping the worst-case execution price against a bad print at the open
    limit_price = round(quote.ask_price * 1.001, 2) if side == OrderSide.BUY else round(quote.bid_price * 0.999, 2)

    client_order_id = f"{symbol}-{strategy}-{dt.date.today().isoformat()}"
    request = LimitOrderRequest(
        symbol=symbol, qty=qty, side=side, type="limit",
        time_in_force=TimeInForce.DAY, limit_price=limit_price,
        client_order_id=client_order_id,
    )

    try:
        return trading_client.submit_order(request)  # type: ignore[reportReturnType]
    except APIError as e:
        if "client_order_id" in str(e).lower() or "already exists" in str(e).lower():
            print(f"Order for {client_order_id} already submitted today -- skipping duplicate.")
            return None
        raise


def reconcile_fill(trading_client: TradingClient, order_id, timeout_s: int = 60) -> Order:
    deadline = time.monotonic() + timeout_s
    terminal_statuses = {"filled", "canceled", "expired", "rejected", "done_for_day"}

    order = trading_client.get_order_by_id(order_id)
    while order.status.value not in terminal_statuses and time.monotonic() < deadline:  # type: ignore[reportAttributeAccessIssue]
        time.sleep(2)
        order = trading_client.get_order_by_id(order_id)

    return order  # type: ignore[reportReturnType]


def log_trade(order: Order | None, symbol: str, strategy: str, signal: int | None, note: str = "no_rebalance_needed") -> None:
    TRADE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not TRADE_LOG_PATH.exists()

    with open(TRADE_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
        if write_header:
            writer.writeheader()

        if order is None:
            writer.writerow({
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "symbol": symbol, "strategy": strategy, "signal": signal,
                "side": "", "qty": 0, "limit_price": "", "client_order_id": "",
                "status": note, "filled_qty": "", "filled_avg_price": "", "filled_at": "",
            })
            return

        writer.writerow({
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "symbol": symbol, "strategy": strategy, "signal": signal,
            "side": order.side.value, "qty": order.qty, "limit_price": order.limit_price, # type: ignore[reportAttributeAccessIssue]
            "client_order_id": order.client_order_id, "status": order.status.value, 
            "filled_qty": order.filled_qty, "filled_avg_price": order.filled_avg_price,
            "filled_at": order.filled_at.isoformat() if order.filled_at else "",
        })
