"""src/backtest/lab.py: backtest a registered strategy next to buy-and-hold, any asset class."""
import numpy as np
import pandas as pd

from src.backtest import lab


def fake_load(symbols, start, end, interval):
    idx = pd.date_range("2025-01-01", periods=400, freq="D", tz="UTC")
    out = {}
    for i, s in enumerate(symbols):
        close = pd.Series(100 + np.arange(400) * 0.5 + np.sin(np.arange(400) / 5) * 3 + i, index=idx)
        out[s] = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e3}, index=idx)
    return out


def test_backtest_reports_strategy_and_buy_and_hold(monkeypatch):
    monkeypatch.setattr(lab, "load_ohlcv", fake_load)
    rows = lab.backtest("btc_sma")
    assert "btc_sma @ 25bps" in rows and "buy&hold BTC/USD" in rows       # crypto default cost
    assert set(rows["btc_sma @ 25bps"]) == {"total_return", "cagr", "sharpe", "max_drawdown"}
    assert rows["_window"]["bars"] > 100


def test_stock_default_cost_is_5_bps_and_symbols_can_be_swapped(monkeypatch):
    monkeypatch.setattr(lab, "load_ohlcv", fake_load)
    rows = lab.backtest("aapl_sma", symbols=["SPY"])
    assert "aapl_sma @ 5bps" in rows and "buy&hold SPY" in rows


def test_explicit_cost_overrides_the_default(monkeypatch):
    monkeypatch.setattr(lab, "load_ohlcv", fake_load)
    assert "btc_sma @ 50bps" in lab.backtest("btc_sma", bps=50)


def test_higher_costs_never_improve_the_result(monkeypatch):
    monkeypatch.setattr(lab, "load_ohlcv", fake_load)
    cheap = lab.backtest("btc_sma", bps=5)["btc_sma @ 5bps"]["total_return"]
    dear = lab.backtest("btc_sma", bps=100)["btc_sma @ 100bps"]["total_return"]
    assert dear <= cheap


def test_show_prints_a_table(monkeypatch, capsys):
    monkeypatch.setattr(lab, "load_ohlcv", fake_load)
    lab.show("btc_sma", lab.backtest("btc_sma"))
    assert "total %" in capsys.readouterr().out
