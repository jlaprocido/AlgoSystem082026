"""src/trading/run_daily.py is now a thin wrapper: the AAPL bot is the registered 'aapl_sma' strategy."""
from src.trading import engine, run_daily


def test_run_daily_runs_the_aapl_strategy_through_the_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "run", lambda name, dry_run=False: calls.append((name, dry_run)))
    run_daily.run()
    assert calls == [("aapl_sma", False)]


def test_notify_is_still_importable_from_run_daily_for_eod_summary():
    assert run_daily.notify is engine.notify
