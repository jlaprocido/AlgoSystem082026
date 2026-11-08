"""src/trading/intraday_check.py: the hourly circuit breaker is engine.check on the AAPL strategy."""
from src.trading import engine, intraday_check


def test_intraday_check_only_runs_the_risk_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "check", lambda name: calls.append(name))
    monkeypatch.setattr(engine, "run", lambda *a, **k: calls.append("RUN-SHOULD-NOT-HAPPEN"))
    intraday_check.run()
    assert calls == ["aapl_sma"]
