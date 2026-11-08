"""Per-strategy dashboard curves: fills in, value curve and stats out. No Alpaca needed."""
import datetime as dt
from types import SimpleNamespace

import pytest

from src.dashboard import build_dashboard as bd
from src.dashboard import performance as perf
from src.strategy.registry import get_strategy

D = dt.date


def order(symbol, side, qty, price, day, hour=15, status="filled"):
    return SimpleNamespace(
        symbol=symbol, side=SimpleNamespace(value=side), filled_qty=str(qty), filled_avg_price=str(price),
        filled_at=dt.datetime(2026, 11, day, hour, tzinfo=dt.timezone.utc) if status == "filled" else None,
        client_order_id=f"{symbol}-x-{day}",
    )


def closes(**by_symbol):
    return {s: {D(2026, 11, d): px for d, px in series.items()} for s, series in by_symbol.items()}


# --- attribution: orders belong to the strategy that owns the symbol ---

def test_orders_are_grouped_by_the_strategy_that_owns_the_symbol():
    orders = [order("AAPL", "buy", 10, 300, 2), order("BTC/USD", "buy", 0.01, 70000, 3), order("TSLA", "buy", 1, 400, 3)]
    fills = perf.fills_from_orders(orders, {"AAPL": "aapl_sma", "BTC/USD": "btc_sma"})
    assert set(fills) == {"aapl_sma", "btc_sma"}          # TSLA belongs to no strategy: ignored
    assert fills["btc_sma"][0]["qty"] == 0.01 and fills["aapl_sma"][0]["side"] == "buy"


def test_unfilled_and_zero_qty_orders_are_ignored():
    orders = [order("AAPL", "buy", 10, 300, 2, status="canceled"), order("AAPL", "buy", 0, 300, 2)]
    assert perf.fills_from_orders(orders, {"AAPL": "aapl_sma"}) == {}


def test_risk_liquidation_fills_are_included_so_there_is_no_ghost_position():
    # the strategy buys 10, then the daily-loss limit liquidates via close_position() -- that
    # order has a random client id and never reached the trade log, but Alpaca has it
    liquidation = order("AAPL", "sell", 10, 280, 4)
    liquidation.client_order_id = "3f1c9e0a-uuid-not-ours"
    fills = perf.fills_from_orders([order("AAPL", "buy", 10, 300, 2), liquidation], {"AAPL": "aapl_sma"})["aapl_sma"]
    days, values, _ = perf.strategy_curve(fills, closes(AAPL={2: 300, 3: 290, 4: 280, 5: 285}), 1000, D(2026, 11, 5))
    assert values[-1] == pytest.approx(1000 - 200)         # flat after the sale: -$200 realized, nothing held


def test_legacy_sma_name_maps_to_aapl_sma():
    assert perf.canonical_strategy("sma") == "aapl_sma" and perf.canonical_strategy("btc_sma") == "btc_sma"


# --- the curve ---

def test_curve_marks_an_open_position_to_the_daily_close():
    fills = [{"date": D(2026, 11, 2), "symbol": "X", "side": "buy", "qty": 10.0, "price": 100.0}]
    days, values, bench = perf.strategy_curve(fills, closes(X={2: 100, 3: 110, 4: 105}), 2000, D(2026, 11, 4))
    assert days == [D(2026, 11, d) for d in (2, 3, 4)]
    assert values == [2000, 2100, 2050]                    # capital + 10 shares x (close - 100)


def test_curve_realizes_profit_on_a_sale():
    fills = [{"date": D(2026, 11, 2), "symbol": "X", "side": "buy", "qty": 10.0, "price": 100.0},
             {"date": D(2026, 11, 3), "symbol": "X", "side": "sell", "qty": 10.0, "price": 120.0}]
    _, values, _ = perf.strategy_curve(fills, closes(X={2: 100, 3: 120, 4: 50}), 2000, D(2026, 11, 4))
    assert values[-1] == 2200                              # price falling after the sale doesn't matter


def test_benchmark_is_buy_and_hold_of_the_same_symbol_from_day_one():
    fills = [{"date": D(2026, 11, 2), "symbol": "X", "side": "buy", "qty": 1.0, "price": 100.0}]
    _, _, bench = perf.strategy_curve(fills, closes(X={2: 100, 3: 150}), 1000, D(2026, 11, 3))
    assert bench == [1000, 1500]


def test_leverage_shows_up_as_larger_swings_on_the_sleeve():
    # 2x: capital 1000 buys 2000 of stock; a 10% rise is +200 = +20% on the sleeve
    fills = [{"date": D(2026, 11, 2), "symbol": "X", "side": "buy", "qty": 20.0, "price": 100.0}]
    _, values, bench = perf.strategy_curve(fills, closes(X={2: 100, 3: 110}), 1000, D(2026, 11, 3))
    assert values[-1] / 1000 - 1 == pytest.approx(0.20) and bench[-1] / 1000 - 1 == pytest.approx(0.10)


def test_curve_falls_back_to_fill_price_when_price_data_is_missing():
    fills = [{"date": D(2026, 11, 2), "symbol": "X", "side": "buy", "qty": 1.0, "price": 100.0}]
    days, values, _ = perf.strategy_curve(fills, {}, 1000, D(2026, 11, 3))
    assert days == [D(2026, 11, 2)] and values == [1000]


def test_no_fills_means_no_curve():
    assert perf.strategy_curve([], {}, 1000, D(2026, 11, 3)) == ([], [], [])


def test_max_drawdown_and_sharpe():
    assert perf.max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)
    assert perf.sharpe([100], 252) is None
    assert perf.sharpe([100, 101, 102, 103.5, 104], 365, min_returns=2) > 0
    assert perf.sharpe([100, 101, 102, 103.5, 104], 365) is None        # 4 returns: too few to annualize


# --- the card ---

def card(st_name, fills, closes_, positions=None, latest=None, capital=1000.0):
    return bd.build_strategy_card(get_strategy(st_name), fills, closes_, capital, positions or {}, latest, D(2026, 11, 5))


def test_card_without_fills_says_waiting_and_shows_the_sleeve():
    html = card("btc_sma", [], {})
    assert "btc_sma" in html and "Waiting for its first trade" in html and "$1,000" in html and "Not run yet" in html


def test_crypto_card_shows_fractional_position_and_stats():
    fills = [{"date": D(2026, 11, 2), "symbol": "BTC/USD", "side": "buy", "qty": 0.01, "price": 70000.0}]
    pos = {"BTCUSD": SimpleNamespace(qty="0.0099", market_value="725.50")}
    latest = {"timestamp": "2026-11-05T10:00:00+00:00", "signal": "1", "status": "filled"}
    html = card("btc_sma", fills, closes(**{"BTC/USD": {2: 70000, 3: 72000, 4: 73000, 5: 74000}}), pos, latest, 700.0)
    for text in ("0.0099 BTC", "$725.50", "Return on sleeve", "+5.71%", "+$40.00", "signal Long", "Max drawdown", "crypto"):
        assert text in html, text


def test_stock_card_shows_whole_shares_and_leverage():
    fills = [{"date": D(2026, 11, 2), "symbol": "AAPL", "side": "buy", "qty": 60.0, "price": 300.0}]
    pos = {"AAPL": SimpleNamespace(qty="60", market_value="18000")}
    html = card("aapl_sma", fills, closes(AAPL={2: 300, 5: 330}), pos, capital=10000)
    assert "60 sh" in html and "2x" in html and "+18.00%" in html       # 60 x $30 = $1,800 on a $10k sleeve


def test_small_sleeve_chart_uses_cents_on_the_axis():
    svg = bd.build_chart_svg([D(2026, 11, 2), D(2026, 11, 3)], [1000.0, 1004.5], [1000.0, 1001.0])
    assert "$1,004.50" in svg or "$1,004.5" in svg
