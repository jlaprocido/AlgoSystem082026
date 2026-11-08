"""Run any registered strategy once. This is the entrypoint cron-job.org / GitHub Actions call.

    python -m src.trading.run_strategy btc_sma              # trade (paper unless config says otherwise)
    python -m src.trading.run_strategy btc_sma --dry-run    # print what it would do, place nothing
    python -m src.trading.run_strategy btc_sma --check-only # risk checks only (fast circuit breaker)
"""
import argparse

from src.strategy.registry import REGISTRY
from src.trading import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("strategy", choices=sorted(REGISTRY))
    parser.add_argument("--dry-run", action="store_true", help="show the plan, place no orders, write nothing")
    parser.add_argument("--check-only", action="store_true", help="risk checks only, never opens a position")
    args = parser.parse_args()

    if args.check_only:
        engine.check(args.strategy)
    else:
        engine.run(args.strategy, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
