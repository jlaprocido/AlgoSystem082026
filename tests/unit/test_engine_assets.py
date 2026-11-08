"""Registry rules, strategy contract, asset adapter, sizing and the crypto path through the engine."""
import dataclasses
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src import assets
from src.backtest import portfolio
from src.risk import risk_manager as rm
from src.strategy import library
from src.strategy.registry import REGISTRY, get_strategy
from src.trading import engine, executor


# --- registry rules the engine relies on ---

def test_one_strategy_per_symbol():
    symbols = [s for st in REGISTRY.values() if st.allocation_pct > 0 for s in st.symbols]  # research-only ones don't trade
    assert len(symbols) == len(set(symbols))


def test_each_strategy_is_one_asset_class():
    for st in REGISTRY.values():
        assert len({assets.asset_for(s).name for s in st.symbols}) == 1, st.name


def test_allocations_per_asset_class_do_not_exceed_equity():
    for cls in ("stock", "crypto"):
        total = sum(st.allocation_pct for st in REGISTRY.values() if st.asset.name == cls)
        assert total <= 1.0, cls


def test_unknown_strategy_lists_choices():
    with pytest.raises(KeyError, match="btc_sma"):
        get_strategy("nope")


def test_asset_class_detection():
    assert assets.asset_for("BTC/USD").name == "crypto"
    assert assets.asset_for("AAPL").name == "stock"


# --- the strategy contract: dict of OHLCV in, weights table out ---

@pytest.fixture
def ohlcv():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=300, freq="D", tz="UTC")
    def one(seed):
        close = pd.Series(100 + np.cumsum(np.random.default_rng(seed).normal(0.2, 2, 300)), index=idx)
        return pd.DataFrame({"open": close.shift(1).fillna(close), "high": close + 1, "low": close - 1,
                             "close": close, "volume": rng.uniform(1e3, 5e3, 300)}, index=idx)
    return {"AAA": one(1), "BBB": one(2), "CCC": one(3), "DDD": one(4)}


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_registered_strategy_returns_a_valid_weights_table(name, ohlcv):
    st = REGISTRY[name]
    syms = list(ohlcv)[: len(st.symbols)]
    w = st.weights({s: ohlcv[s] for s in syms})
    assert list(w.columns) == syms and w.index.equals(ohlcv[syms[0]].index)
    assert (w.fillna(0) >= 0).all().all()                          # long-only
    assert (w.fillna(0) <= st.leverage + 1e-9).all().all()         # never above its leverage


def test_sma_is_long_in_uptrend_and_flat_in_downtrend():
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    up = pd.DataFrame({"close": np.arange(60.0)}, index=idx)
    down = pd.DataFrame({"close": np.arange(60.0)[::-1]}, index=idx)
    assert library.sma({"X": up}).iloc[-1, 0] == 1.0
    assert library.sma({"X": down}).iloc[-1, 0] == 0.0


def test_shorts_are_clipped_and_leverage_applied(ohlcv):
    st = dataclasses.replace(get_strategy("aapl_sma"), fn=lambda o, **p: pd.DataFrame({"AAPL": [-1.0, 1.0]}), leverage=2.0)
    assert st.weights({}).iloc[:, 0].tolist() == [0.0, 2.0]


def test_dual_momentum_holds_only_the_strongest_rising_asset(ohlcv):
    w = library.dual_momentum({k: ohlcv[k] for k in ("AAA", "BBB")}, lookback=20)
    assert (w.sum(axis=1) <= 1.0 + 1e-9).all()


# --- asset adapter ---

def test_stock_quantities_are_whole_crypto_fractional():
    assert assets.STOCK.normalize_qty(12.9) == 12
    assert assets.CRYPTO.normalize_qty(0.123456789) == pytest.approx(0.123456)


def test_crypto_orders_are_gtc_and_always_open():
    assert assets.CRYPTO.time_in_force.value == "gtc" and assets.STOCK.time_in_force.value == "day"
    assert assets.CRYPTO.is_open(None) is True


def test_crypto_position_symbol_drops_the_slash():
    assert assets.CRYPTO.position_symbol("BTC/USD") == "BTCUSD"


def test_annualization_uses_365_for_crypto_252_for_stocks():
    assert assets.CRYPTO.bars_per_year["1d"] == 365 and assets.STOCK.bars_per_year["1d"] == 252
    assert assets.CRYPTO.bars_per_year["5m"] == 365 * 288


def test_summary_annualizes_with_the_given_periods_per_year():
    r = pd.Series([0.01, -0.005] * 50)
    assert portfolio.summary(r, 365)["sharpe"] == pytest.approx(portfolio.summary(r, 252)["sharpe"] * np.sqrt(365 / 252))


def test_portfolio_returns_charge_cost_on_leveraged_turnover():
    idx = pd.date_range("2024-01-01", periods=4)
    close = pd.DataFrame({"X": [100.0, 100.0, 100.0, 100.0]}, index=idx)
    w = pd.DataFrame({"X": [0.0, 2.0, 2.0, 0.0]}, index=idx)         # 2x row, flat prices
    r = portfolio.portfolio_returns(w, close, slippage_pct=0.001)
    assert r.sum() == pytest.approx(-0.001 * (2 + 2))                 # turnover 2 in + 2 out


def test_backtest_refuses_to_mix_stocks_and_crypto():
    with pytest.raises(ValueError, match="crypto weekend"):
        portfolio.load_ohlcv(["AAPL", "BTC/USD"], dt.date(2024, 1, 1), dt.date(2024, 2, 1))


# --- sizing ---

class FixedQuoteAsset:
    """Stand-in adapter with a known ask."""
    def __init__(self, base, ask): self.base, self.ask = base, ask
    def get_quote(self, symbol): return self.ask - 1, self.ask
    def normalize_qty(self, q): return self.base.normalize_qty(q)


def test_target_qty_is_equity_times_allocation_times_weight_over_ask():
    a = FixedQuoteAsset(assets.STOCK, 300.0)
    assert executor.get_target_qty(10_000, a, "AAPL", 2.0, 1.0) == 66          # 20k / 300, whole shares
    assert executor.get_target_qty(10_000, a, "AAPL", 0.0, 1.0) == 0


def test_crypto_buy_is_capped_by_cash_not_rejected():
    a = FixedQuoteAsset(assets.CRYPTO, 50_000.0)
    full = executor.get_target_qty(10_000, a, "BTC/USD", 1.0, 0.5)             # wants $5,000
    capped = executor.get_target_qty(10_000, a, "BTC/USD", 1.0, 0.5, 0.0, 1_000.0)
    assert full == pytest.approx(0.1) and capped == pytest.approx(0.0196)       # $1,000 * 0.98 / 50k


def test_cash_cap_never_blocks_selling_down():
    a = FixedQuoteAsset(assets.CRYPTO, 50_000.0)
    assert executor.get_target_qty(10_000, a, "BTC/USD", 1.0, 0.1, 0.5, 0.0) == pytest.approx(0.02)


def test_order_id_is_one_per_bar():
    t = dt.datetime(2026, 11, 7, 15, 42, tzinfo=dt.timezone.utc)
    assert executor.order_id_bucket("1d", t) == "2026-11-07"
    assert executor.order_id_bucket("1h", t) == "20261107T15"
    assert executor.order_id_bucket("5m", t) == "20261107T1542"


# --- the crypto path through the engine ---

def test_crypto_strategy_trades_fractional_gtc_with_no_market_hours(monkeypatch, tmp_path):
    submitted = []
    bars = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                        index=[pd.Timestamp.now(tz="UTC")])
    st = get_strategy("btc_sma")
    st = dataclasses.replace(st, fn=lambda o, **p: pd.DataFrame({"BTC/USD": [1.0]}, index=bars.index))
    account = SimpleNamespace(equity="10000", non_marginable_buying_power="10000")
    client = SimpleNamespace(get_account=lambda: account, get_clock=lambda: (_ for _ in ()).throw(AssertionError("crypto must not check the stock clock")))
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt.json")
    monkeypatch.setattr(engine, "get_strategy", lambda n: st)
    monkeypatch.setattr(engine, "get_trading_client", lambda s: client)
    monkeypatch.setattr(engine, "load_ohlcv", lambda s: {"BTC/USD": bars})
    monkeypatch.setattr(engine, "check_risk_limits", lambda *a: True)
    monkeypatch.setattr(engine, "notify", lambda m: None)
    monkeypatch.setattr(engine.executor, "get_current_qty", lambda *a: 0.0)
    monkeypatch.setattr(assets.CRYPTO, "get_quote", lambda s: (49_990.0, 50_000.0))
    monkeypatch.setattr(engine.executor, "submit_rebalance_order",
                        lambda tc, asset, sym, name, target, current, **k: submitted.append((asset.name, sym, target, current)))
    monkeypatch.setattr(engine.executor, "log_trade", lambda *a, **k: None)
    engine.run("btc_sma")
    assert submitted == [("crypto", "BTC/USD", pytest.approx(0.02), 0.0)]       # 10,000 * 10% / 50,000


def test_research_only_strategy_is_refused_by_the_live_engine(monkeypatch, capsys):
    monkeypatch.setattr(engine, "get_trading_client", lambda s: (_ for _ in ()).throw(AssertionError("must not connect")))
    engine.run("dual_momentum")
    assert "research-only" in capsys.readouterr().out


def test_daily_loss_state_is_per_strategy(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "RISK_DIR", tmp_path)
    rm.set_daily_loss_level("aapl_sma", "flattened")
    assert rm.get_daily_loss_level("aapl_sma") == "flattened"
    assert rm.get_daily_loss_level("btc_sma") is None


def test_fee_dust_counts_as_flat_so_a_flat_signal_does_not_chase_it(monkeypatch, tmp_path):
    calls = []
    bars = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                        index=[pd.Timestamp.now(tz="UTC")])
    st = dataclasses.replace(get_strategy("btc_sma"), fn=lambda o, **p: pd.DataFrame({"BTC/USD": [0.0]}, index=bars.index))
    client = SimpleNamespace(get_account=lambda: SimpleNamespace(equity="10000", non_marginable_buying_power="10000"))
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt.json")
    monkeypatch.setattr(engine, "get_strategy", lambda n: st)
    monkeypatch.setattr(engine, "get_trading_client", lambda s: client)
    monkeypatch.setattr(engine, "load_ohlcv", lambda s: {"BTC/USD": bars})
    monkeypatch.setattr(engine, "check_risk_limits", lambda *a: True)
    monkeypatch.setattr(engine, "notify", lambda m: None)
    monkeypatch.setattr(engine.executor, "get_current_qty", lambda *a: 6e-8)          # $0.005 of BTC
    monkeypatch.setattr(assets.CRYPTO, "get_quote", lambda s: (75_000.0, 75_010.0))
    monkeypatch.setattr(engine.executor, "submit_rebalance_order", lambda *a, **k: calls.append("order"))
    monkeypatch.setattr(engine.executor, "log_trade", lambda order, sym, strat, sig, note="": calls.append(note))
    engine.run("btc_sma")
    assert calls == ["signal_unchanged"]


# --- two Alpaca accounts: stocks and crypto never share cash, halts or keys ---

def test_each_asset_class_trades_in_its_own_account(monkeypatch):
    monkeypatch.setattr(assets, "get_alpaca_trading_client", lambda: "STOCK-ACCOUNT")
    monkeypatch.setattr(assets, "get_alpaca_crypto_trading_client", lambda: "CRYPTO-ACCOUNT")
    assert engine.get_trading_client(get_strategy("aapl_sma")) == "STOCK-ACCOUNT"
    assert engine.get_trading_client(get_strategy("btc_sma")) == "CRYPTO-ACCOUNT"


def test_crypto_without_its_own_keys_refuses_instead_of_using_the_stock_account(monkeypatch):
    from src import config
    monkeypatch.setattr(config, "ALPACA_CRYPTO_API_KEY", None)
    monkeypatch.setattr(config, "ALPACA_CRYPTO_SECRET_KEY", None)
    assert config.crypto_account_configured() is False
    with pytest.raises(RuntimeError, match="ALPACA_CRYPTO_API_KEY"):
        config.get_alpaca_crypto_trading_client()


def test_halting_one_account_does_not_halt_the_other(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "RISK_DIR", tmp_path)
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt_state.json")
    rm.set_halted("test", "crypto")
    assert rm.is_halted("crypto") and not rm.is_halted("stock") and not rm.is_halted()
    rm.clear_halt("crypto")
    assert not rm.is_halted("crypto")


def test_crypto_drawdown_breach_flattens_and_halts_only_the_crypto_account(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "RISK_DIR", tmp_path)
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt_state.json")
    closed = []
    client = SimpleNamespace(
        get_account=lambda: SimpleNamespace(equity="8000"),
        get_portfolio_history=lambda req: SimpleNamespace(equity=[10_000.0], timestamp=[0]),
        close_all_positions=lambda cancel_orders=False: closed.append("ALL"),
    )
    monkeypatch.setattr(engine, "notify", lambda m: None)
    monkeypatch.setattr(engine.executor, "log_trade", lambda *a, **k: None)
    assert engine.check_risk_limits(client, get_strategy("btc_sma")) is False
    assert closed == ["ALL"] and rm.is_halted("crypto") and not rm.is_halted("stock")
