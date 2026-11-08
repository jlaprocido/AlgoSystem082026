from types import SimpleNamespace

import pytest

from src.risk import risk_manager as rm
from src.strategy.registry import get_strategy
from src.trading import engine

STRATEGY = get_strategy("aapl_sma")


class FakeTradingClient:
    """Just enough of Alpaca's TradingClient for the risk checks; records what got called."""

    def __init__(self, equity=10_000.0, history=(10_000.0,), move=0.0, shares=0):
        self.equity = equity
        self.history = list(history)
        self.move = move
        self.shares = shares
        self.closed = []

    def get_account(self):
        return SimpleNamespace(equity=str(self.equity), non_marginable_buying_power=str(self.equity))

    def get_clock(self):
        return SimpleNamespace(is_open=True)

    def close_all_positions(self, cancel_orders=False):
        self.closed.append("ALL")
        self.shares = 0

    def get_portfolio_history(self, _request):
        return SimpleNamespace(equity=self.history, timestamp=list(range(len(self.history))))

    def get_open_position(self, _symbol):
        if self.shares == 0:
            raise rm.APIError(f'{{"code": {rm.NO_POSITION_ERROR_CODE}, "message": "position does not exist"}}')
        return SimpleNamespace(qty=str(self.shares), unrealized_intraday_plpc=str(self.move))

    def close_position(self, symbol):
        self.closed.append(symbol)
        self.shares = 0


@pytest.fixture
def risk_env(tmp_path, monkeypatch):
    """Point the state files at a temp dir and capture notifications, trade-log rows and orders."""
    monkeypatch.setattr(rm, "RISK_DIR", tmp_path)
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt.json")
    env = SimpleNamespace(notes=[], logged=[], orders=[])
    monkeypatch.setattr(engine, "notify", env.notes.append)
    monkeypatch.setattr(engine.executor, "log_trade", lambda order, sym, strat, sig, note="": env.logged.append(note))
    monkeypatch.setattr(engine.executor, "get_target_qty", lambda *a, **k: 30)  # the 1x target
    monkeypatch.setattr(engine.executor, "submit_rebalance_order",
                        lambda *a, **k: env.orders.append((a[4], a[5], k.get("id_suffix"))))
    return env


# --- drawdown uses live equity, not the stale history point ---

def test_drawdown_uses_live_equity_not_last_history_point():
    # history still says 12k (yesterday); the account is already at 10k live -> 16.7% drawdown
    client = FakeTradingClient(equity=10_000, history=[10_000, 12_000])
    breached, dd = rm.check_max_drawdown(client, 0.15)  # type: ignore[reportArgumentType]
    assert breached and dd == pytest.approx(1 / 6)


def test_drawdown_not_breached_when_live_equity_recovered():
    client = FakeTradingClient(equity=11_900, history=[10_000, 12_000, 10_000])
    breached, _ = rm.check_max_drawdown(client, 0.15)  # type: ignore[reportArgumentType]
    assert not breached


def test_drawdown_peak_includes_live_equity():
    # a new live high is the peak, so there is no drawdown
    client = FakeTradingClient(equity=13_000, history=[10_000, 12_000])
    assert rm.check_max_drawdown(client, 0.15) == (False, 0.0)  # type: ignore[reportArgumentType]


# --- tiered daily move limits ---

def test_small_move_passes(risk_env):
    client = FakeTradingClient(move=-0.02, shares=60)
    assert engine.check_risk_limits(client, STRATEGY) is True
    assert client.closed == [] and risk_env.orders == []


def test_move_at_reduce_limit_cuts_to_1x_only(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    assert engine.check_risk_limits(client, STRATEGY) is False
    assert risk_env.orders == [(30, 60, "reduce")]  # sells 60 -> 30, own order id
    assert client.closed == []
    assert rm.get_daily_loss_level("aapl_sma") == "reduced"


def test_reduce_never_buys_when_already_below_1x(risk_env):
    client = FakeTradingClient(move=-0.03, shares=20)  # 1x target is 30, already under it
    engine.check_risk_limits(client, STRATEGY)
    assert risk_env.orders == []
    assert rm.get_daily_loss_level("aapl_sma") == "reduced"


def test_move_at_flatten_limit_flattens(risk_env):
    client = FakeTradingClient(move=-0.06, shares=60)
    assert engine.check_risk_limits(client, STRATEGY) is False
    assert client.closed == ["AAPL"]
    assert rm.get_daily_loss_level("aapl_sma") == "flattened"


def test_reduced_then_worse_move_escalates_to_flatten(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    engine.check_risk_limits(client, STRATEGY)
    client.move = -0.055
    engine.check_risk_limits(client, STRATEGY)
    assert client.closed == ["AAPL"] and rm.get_daily_loss_level("aapl_sma") == "flattened"


def test_same_day_repeat_checks_stay_quiet(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    engine.check_risk_limits(client, STRATEGY)
    notes_after_first = len(risk_env.notes)
    assert engine.check_risk_limits(client, STRATEGY) is False  # hourly check: no re-cut
    assert len(risk_env.notes) == notes_after_first and len(risk_env.orders) == 1


def test_flattened_day_blocks_rebuy_until_next_day(risk_env):
    client = FakeTradingClient(move=-0.06, shares=60)
    engine.check_risk_limits(client, STRATEGY)
    assert engine.check_risk_limits(client, STRATEGY) is False  # now flat, still blocked today


def test_flat_account_has_no_move(risk_env):
    client = FakeTradingClient(shares=0)
    assert rm.get_position_move_today(client, "AAPL") == 0.0  # type: ignore[reportArgumentType]
    assert engine.check_risk_limits(client, STRATEGY) is True


def test_drawdown_breach_flattens_and_halts(risk_env):
    client = FakeTradingClient(equity=8_000, history=[10_000], shares=60)
    assert engine.check_risk_limits(client, STRATEGY) is False
    assert client.closed == ["ALL"] and rm.is_halted()  # global kill switch: sells the whole account


# --- rebalance band ---

@pytest.fixture
def run_env(monkeypatch, tmp_path):
    """Run engine.run() with everything external stubbed; `env.orders` records submitted deltas."""
    import dataclasses
    import pandas as pd

    env = SimpleNamespace(signal=1.0, current=0, target=0, orders=[], logged=[])
    bars = pd.DataFrame({"open": [300.0], "high": [300.0], "low": [300.0], "close": [300.0], "volume": [1.0]},
                        index=[pd.Timestamp.now(tz="UTC")])
    # the real aapl_sma strategy (2x leverage, long-only) with a signal we control
    strategy = dataclasses.replace(STRATEGY, fn=lambda ohlcv, **p: pd.DataFrame({"AAPL": [env.signal]}, index=bars.index))
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt.json")
    monkeypatch.setattr(engine, "get_strategy", lambda name: strategy)
    monkeypatch.setattr(engine, "get_trading_client", lambda s: FakeTradingClient())
    monkeypatch.setattr(engine, "load_ohlcv", lambda s: {"AAPL": bars})
    monkeypatch.setattr(engine, "notify", lambda msg: None)
    monkeypatch.setattr(engine, "check_risk_limits", lambda *a: True)
    monkeypatch.setattr(engine.executor, "get_current_qty", lambda *a: env.current)
    monkeypatch.setattr(engine.executor, "get_target_qty", lambda *a, **k: env.target)
    monkeypatch.setattr(engine.executor, "log_trade", lambda order, sym, strat, sig, note="": env.logged.append(note))
    monkeypatch.setattr(engine.executor, "submit_rebalance_order",
                        lambda *a, **k: env.orders.append((a[4], a[5])))
    return env


def test_band_skips_tiny_drift_while_long(run_env):
    run_env.current, run_env.target = 57, 58  # 1.7% off target
    engine.run("aapl_sma")
    assert run_env.orders == [] and run_env.logged == ["signal_unchanged"]


def test_band_trades_when_drift_exceeds_band(run_env):
    run_env.current, run_env.target = 30, 60  # re-levering after a 1x cut
    engine.run("aapl_sma")
    assert run_env.orders == [(60, 30)]


def test_band_never_blocks_opening_a_position(run_env):
    run_env.current, run_env.target = 0, 1
    engine.run("aapl_sma")
    assert run_env.orders == [(1, 0)]


def test_band_never_blocks_closing_a_position(run_env):
    run_env.signal, run_env.current, run_env.target = 0.0, 1, 0
    engine.run("aapl_sma")
    assert run_env.orders == [(0, 1)]
