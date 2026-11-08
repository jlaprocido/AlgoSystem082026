"""src/trading/run_strategy.py: the CLI cron-job.org / GitHub Actions call for any registered strategy."""
import pytest

from src.trading import engine, run_strategy


def run_cli(monkeypatch, *argv):
    calls = []
    monkeypatch.setattr(engine, "run", lambda name, dry_run=False: calls.append(("run", name, dry_run)))
    monkeypatch.setattr(engine, "check", lambda name: calls.append(("check", name)))
    monkeypatch.setattr("sys.argv", ["run_strategy", *argv])
    run_strategy.main()
    return calls


def test_plain_run_trades(monkeypatch):
    assert run_cli(monkeypatch, "btc_sma") == [("run", "btc_sma", False)]


def test_dry_run_flag_is_passed_through(monkeypatch):
    assert run_cli(monkeypatch, "eth_donchian", "--dry-run") == [("run", "eth_donchian", True)]


def test_check_only_never_runs_the_strategy(monkeypatch):
    assert run_cli(monkeypatch, "btc_sma", "--check-only") == [("check", "btc_sma")]


def test_unknown_strategy_is_rejected(monkeypatch):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "not_a_strategy")
