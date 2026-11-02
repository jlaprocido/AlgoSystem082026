from types import SimpleNamespace

import pytest

from src.risk import risk_manager as rm
from src.trading import run_daily


class FakeTradingClient:
    """Just enough of Alpaca's TradingClient for the risk checks; records what got called."""

    def __init__(self, equity=10_000.0, history=(10_000.0,), move=0.0, shares=0):
        self.equity = equity
        self.history = list(history)
        self.move = move
        self.shares = shares
        self.closed = []

    def get_account(self):
        return SimpleNamespace(equity=str(self.equity))

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
    monkeypatch.setattr(rm, "HALT_STATE_PATH", tmp_path / "halt.json")
    monkeypatch.setattr(rm, "DAILY_LOSS_STATE_PATH", tmp_path / "daily_loss.json")
    env = SimpleNamespace(notes=[], logged=[], orders=[])
    monkeypatch.setattr(run_daily, "notify", env.notes.append)
    monkeypatch.setattr(run_daily.executor, "log_trade", lambda order, sym, strat, sig, note="": env.logged.append(note))
    monkeypatch.setattr(run_daily, "get_alpaca_client", lambda: None)
    monkeypatch.setattr(run_daily.executor, "get_target_shares", lambda *a, **k: 30)  # the 1x target
    monkeypatch.setattr(run_daily.executor, "submit_rebalance_order",
                        lambda *a, **k: env.orders.append((a[5], a[6], k.get("id_suffix"))))
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
    assert run_daily.check_risk_limits(client, "AAPL") is True
    assert client.closed == [] and risk_env.orders == []


def test_move_at_reduce_limit_cuts_to_1x_only(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    assert run_daily.check_risk_limits(client, "AAPL") is False
    assert risk_env.orders == [(30, 60, "reduce")]  # sells 60 -> 30, own order id
    assert client.closed == []
    assert rm.get_daily_loss_level() == "reduced"


def test_reduce_never_buys_when_already_below_1x(risk_env):
    client = FakeTradingClient(move=-0.03, shares=20)  # 1x target is 30, already under it
    run_daily.check_risk_limits(client, "AAPL")
    assert risk_env.orders == []
    assert rm.get_daily_loss_level() == "reduced"


def test_move_at_flatten_limit_flattens(risk_env):
    client = FakeTradingClient(move=-0.06, shares=60)
    assert run_daily.check_risk_limits(client, "AAPL") is False
    assert client.closed == ["AAPL"]
    assert rm.get_daily_loss_level() == "flattened"


def test_reduced_then_worse_move_escalates_to_flatten(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    run_daily.check_risk_limits(client, "AAPL")
    client.move = -0.055
    run_daily.check_risk_limits(client, "AAPL")
    assert client.closed == ["AAPL"] and rm.get_daily_loss_level() == "flattened"


def test_same_day_repeat_checks_stay_quiet(risk_env):
    client = FakeTradingClient(move=-0.03, shares=60)
    run_daily.check_risk_limits(client, "AAPL")
    notes_after_first = len(risk_env.notes)
    assert run_daily.check_risk_limits(client, "AAPL") is False  # hourly check: no re-cut
    assert len(risk_env.notes) == notes_after_first and len(risk_env.orders) == 1


def test_flattened_day_blocks_rebuy_until_next_day(risk_env):
    client = FakeTradingClient(move=-0.06, shares=60)
    run_daily.check_risk_limits(client, "AAPL")
    assert run_daily.check_risk_limits(client, "AAPL") is False  # now flat, still blocked today


def test_flat_account_has_no_move(risk_env):
    client = FakeTradingClient(shares=0)
    assert rm.get_position_move_today(client, "AAPL") == 0.0  # type: ignore[reportArgumentType]
    assert run_daily.check_risk_limits(client, "AAPL") is True


def test_drawdown_breach_flattens_and_halts(risk_env):
    client = FakeTradingClient(equity=8_000, history=[10_000], shares=60)
    assert run_daily.check_risk_limits(client, "AAPL") is False
    assert client.closed == ["AAPL"] and rm.is_halted()


# --- rebalance band ---

@pytest.fixture
def run_env(monkeypatch):
    """Run run_daily.run() with everything external stubbed; `env.orders` records submitted deltas."""
    import datetime as dt
    import pandas as pd

    env = SimpleNamespace(signal=1, current=0, target=0, orders=[], logged=[])
    bars = pd.DataFrame({"timestamp": [pd.Timestamp(dt.date.today())], "close": [300.0]})
    monkeypatch.setattr(run_daily, "get_alpaca_trading_client", lambda: None)
    monkeypatch.setattr(run_daily, "get_alpaca_client", lambda: None)
    monkeypatch.setattr(run_daily, "get_bars", lambda *a, **k: bars)
    monkeypatch.setattr(run_daily, "notify", lambda msg: None)
    monkeypatch.setattr(run_daily, "check_risk_limits", lambda *a: True)
    monkeypatch.setattr(run_daily.rm, "is_halted", lambda: False)
    monkeypatch.setattr(run_daily.rm, "check_market_open", lambda c: True)
    monkeypatch.setattr(run_daily.aapl_sma, "compute_signal", lambda df: env.signal)
    monkeypatch.setattr(run_daily.executor, "get_current_shares", lambda *a: env.current)
    monkeypatch.setattr(run_daily.executor, "get_target_shares", lambda *a, **k: env.target)
    monkeypatch.setattr(run_daily.executor, "log_trade", lambda order, sym, strat, sig, note="": env.logged.append(note))
    monkeypatch.setattr(run_daily.executor, "submit_rebalance_order",
                        lambda *a, **k: env.orders.append((a[5], a[6])))
    return env


def test_band_skips_tiny_drift_while_long(run_env):
    run_env.current, run_env.target = 57, 58  # 1.7% off target
    run_daily.run()
    assert run_env.orders == [] and run_env.logged == ["signal_unchanged"]


def test_band_trades_when_drift_exceeds_band(run_env):
    run_env.current, run_env.target = 30, 60  # re-levering after a 1x cut
    run_daily.run()
    assert run_env.orders == [(60, 30)]


def test_band_never_blocks_opening_a_position(run_env):
    run_env.current, run_env.target = 0, 1
    run_daily.run()
    assert run_env.orders == [(1, 0)]


def test_band_never_blocks_closing_a_position(run_env):
    run_env.signal, run_env.current, run_env.target = 0, 1, 0
    run_daily.run()
    assert run_env.orders == [(0, 1)]
