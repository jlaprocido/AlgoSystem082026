import csv
import time
import datetime as dt
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.models import Order

from src.assets import asset_for

TRADE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "orders" / "trade_log.csv"
TRADE_LOG_FIELDS = [
    "timestamp", "symbol", "strategy", "signal", "side", "qty", "limit_price",
    "client_order_id", "status", "filled_qty", "filled_avg_price", "filled_at",
]


def find_strategy_start_date() -> dt.date | None:
    # the account can sit funded-but-flat for a while before the strategy's first real trade
    # (e.g. weeks of $10k doing nothing before the first BUY) -- callers that want to measure
    # the strategy's own performance (not the account's) should start from this date, not from
    # whenever the account happened to be funded. Shared by eod_summary.py and build_dashboard.py.
    if not TRADE_LOG_PATH.exists():
        return None

    with open(TRADE_LOG_PATH, newline="") as f:
        filled = [row for row in csv.DictReader(f) if row.get("status") == "filled"]
    if not filled:
        return None

    first = min(filled, key=lambda row: row["timestamp"])
    return dt.datetime.fromisoformat(first["timestamp"]).date()


def get_current_qty(trading_client: TradingClient, asset, symbol: str) -> float:
    """Open position size (shares or coins); 0 when flat. Works for stocks and crypto."""
    try:
        position = trading_client.get_open_position(asset.position_symbol(symbol))
        return float(position.qty)  # type: ignore[reportAttributeAccessIssue]
    except APIError as e:
        # matched on the same stable numeric code risk_manager.flatten_position() uses --
        # GET and DELETE /positions/{symbol} return different message text for "no position"
        # ("position does not exist" vs "position not found: AAPL") but share this code
        if e.code == 40410000:
            return 0.0
        raise


def get_current_shares(trading_client: TradingClient, symbol: str) -> int:
    # whole-share stock view, used by the AAPL-specific EOD summary and dashboard
    return int(get_current_qty(trading_client, asset_for(symbol), symbol))


def get_target_qty(equity: float, asset, symbol: str, weight: float, allocation_pct: float,
                   current_qty: float = 0.0, buying_power: float | None = None) -> float:
    """Quantity that makes the position `weight` x `allocation_pct` of account equity.

    weight is the strategy's target (0 = flat, 1 = 1x, 2 = 2x leverage). Sized off total equity,
    not account.buying_power: buying power reflects *remaining* capacity after any existing
    position, so it would shrink the target every time we already hold some.

    buying_power (crypto only) caps how much *more* we can buy: crypto cannot use margin, so a
    cash-poor account (e.g. fully levered in stocks) gets a smaller order instead of a rejection.
    """
    if weight <= 0:
        return 0
    _, ask = asset.get_quote(symbol)
    target = asset.normalize_qty(equity * allocation_pct * weight / ask)
    if buying_power is not None and target > current_qty:
        affordable = current_qty + asset.normalize_qty(buying_power * 0.98 / ask)  # 2% cushion for the limit offset
        target = min(target, affordable)
    return target


def order_id_bucket(interval: str, now: dt.datetime | None = None) -> str:
    # one order id per strategy per bar: a duplicate cron dispatch inside the same bar is skipped
    # as a duplicate, while the next bar (next hour, next day) may trade again
    now = now or dt.datetime.now(dt.timezone.utc)
    if interval == "1d":
        return now.date().isoformat()
    return now.strftime({"1h": "%Y%m%dT%H", "30m": "%Y%m%dT%H%M", "15m": "%Y%m%dT%H%M", "5m": "%Y%m%dT%H%M"}[interval])


def submit_rebalance_order(trading_client: TradingClient, asset, symbol: str, strategy: str,
                           target_qty: float, current_qty: float, id_suffix: str = "",
                           interval: str = "1d") -> Order | None:
    delta = target_qty - current_qty
    if delta == 0:
        return None

    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    qty = asset.normalize_qty(abs(delta))
    if qty <= 0:
        return None

    bid, ask = asset.get_quote(symbol)
    # marketable limit: through the market enough to fill almost immediately on a liquid name,
    # while still capping the worst-case execution price against a bad print
    limit_price = asset.round_price(ask * 1.001) if side == OrderSide.BUY else asset.round_price(bid * 0.999)

    # id_suffix lets a same-day risk cut coexist with the regular rebalance order, which
    # would otherwise collide on this id and be silently skipped as a "duplicate"
    client_order_id = f"{symbol.replace('/', '')}-{strategy}-{order_id_bucket(interval)}" + (f"-{id_suffix}" if id_suffix else "")
    request = LimitOrderRequest(
        symbol=symbol, qty=qty, side=side, type="limit",
        time_in_force=asset.time_in_force, limit_price=limit_price,
        client_order_id=client_order_id,
    )

    try:
        return trading_client.submit_order(request)  # type: ignore[reportReturnType]
    except APIError as e:
        if "client_order_id" in str(e).lower() or "already exists" in str(e).lower():
            print(f"Order for {client_order_id} already submitted for this bar -- skipping duplicate.")
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
