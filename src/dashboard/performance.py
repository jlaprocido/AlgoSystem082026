"""Per-strategy performance, rebuilt from Alpaca's filled orders.

Alpaca's equity curve is the whole account; it does not say which strategy earned what. But every
filled order has a symbol, quantity and fill price, and each symbol belongs to exactly one
trading strategy (a registry rule), so each strategy's curve is rebuilt from its own fills:

    pnl(day)   = cash flow from its fills so far + (shares held x that day's close)
    value(day) = capital + pnl(day)          capital = the sleeve the strategy is allowed to use
    benchmark  = capital x (buy-and-hold of the same symbols since the strategy's first day)

Why Alpaca's orders and not data/orders/trade_log.csv: risk liquidations (daily-loss flatten,
max-drawdown kill switch) close positions through close_position(), and the trade log only gets a
note row for those, never the fill. Rebuilding from the log left a "ghost" position (147 AAPL
shares held in the log, flat in the account). Alpaca's order history has every fill.

Approximations worth knowing: prices are daily closes (so intraday swings aren't seen), and
crypto fees that Alpaca takes in coins (~0.25%) are not modeled, so a crypto curve reads a touch
better than the account really did. Pure functions here, so tests need no Alpaca.
"""
import datetime as dt
import math
import statistics

# the AAPL bot logged itself as "sma" before it became the registered "aapl_sma" strategy
STRATEGY_ALIASES = {"sma": "aapl_sma"}


def canonical_strategy(name: str) -> str:
    return STRATEGY_ALIASES.get(name, name)


def fills_from_orders(orders: list, symbol_to_strategy: dict[str, str]) -> dict[str, list[dict]]:
    """Filled Alpaca orders per strategy, oldest first: {strategy: [{date, symbol, side, qty, price}]}.

    `orders` are alpaca Order objects (or anything with the same attributes). Orders for symbols
    no trading strategy owns are ignored, as are unfilled and cancelled ones.
    """
    out: dict[str, list[dict]] = {}
    for o in sorted(orders, key=lambda o: o.filled_at or dt.datetime.max.replace(tzinfo=dt.timezone.utc)):
        strategy = symbol_to_strategy.get(o.symbol)
        qty = float(o.filled_qty or 0)
        if strategy is None or o.filled_at is None or qty <= 0 or not o.filled_avg_price:
            continue
        out.setdefault(strategy, []).append({
            "date": o.filled_at.astimezone(dt.timezone.utc).date(), "symbol": o.symbol,
            "side": o.side.value.lower(), "qty": qty, "price": float(o.filled_avg_price),
        })
    return out


def _price_on(series: dict[dt.date, float], day: dt.date) -> float | None:
    """Latest close on or before `day`."""
    earlier = [d for d in series if d <= day]
    return series[max(earlier)] if earlier else None


def strategy_curve(fills: list[dict], closes: dict[str, dict[dt.date, float]], capital: float,
                   end: dt.date) -> tuple[list[dt.date], list[float], list[float]]:
    """(dates, strategy value, buy-and-hold value), both in dollars starting from `capital`."""
    if not fills:
        return [], [], []
    start = fills[0]["date"]
    symbols = sorted({f["symbol"] for f in fills} | set(closes))
    days = sorted({d for s in closes.values() for d in s if start <= d <= end} | {f["date"] for f in fills})

    cash, held, i = 0.0, {s: 0.0 for s in symbols}, 0
    last_fill_price = {}
    values, bench = [], []
    base = {}
    for day in days:
        while i < len(fills) and fills[i]["date"] <= day:
            f = fills[i]
            sign = 1 if f["side"] == "buy" else -1
            cash -= sign * f["qty"] * f["price"]
            held[f["symbol"]] += sign * f["qty"]
            last_fill_price[f["symbol"]] = f["price"]
            i += 1

        marks = {}
        for s in symbols:
            px = _price_on(closes.get(s, {}), day) or last_fill_price.get(s)
            marks[s] = px
            if s not in base and px:
                base[s] = px  # buy-and-hold enters at the first price we can see

        values.append(capital + cash + sum(held[s] * (marks[s] or 0.0) for s in symbols))
        ratios = [marks[s] / base[s] for s in symbols if marks[s] and s in base]
        bench.append(capital * (sum(ratios) / len(ratios)) if ratios else capital)
    return days, values, bench


def sharpe(values: list[float], periods_per_year: int, min_returns: int = 10) -> float | None:
    """Annualized Sharpe of a value curve, or None until there are `min_returns` daily returns:
    a handful of days annualizes into a huge, meaningless number."""
    returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0 and values[i] > 0]
    if len(returns) < max(2, min_returns):
        return None
    std = statistics.stdev(returns)
    return statistics.mean(returns) / std * math.sqrt(periods_per_year) if std > 0 else None


def max_drawdown(values: list[float]) -> float:
    peak, worst = float("-inf"), 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1) if peak > 0 else worst
    return worst
