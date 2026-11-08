from src.trading import engine
from src.trading.engine import notify  # noqa: F401  (eod_summary.py imports it from here)

# The AAPL SMA bot is now just one registered strategy ("aapl_sma" in src/strategy/registry.py)
# run by the generic engine. This module stays as the entrypoint run_daily.yml calls, once per
# trading day near the open.
STRATEGY_NAME = "aapl_sma"


def run() -> None:
    engine.run(STRATEGY_NAME)


if __name__ == "__main__":
    run()
