import json
import datetime as dt
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetPortfolioHistoryRequest

NO_POSITION_ERROR_CODE = 40410000  # shared by GET and DELETE /positions/{symbol} despite
                                    # returning different message text ("position does not
                                    # exist" vs "position not found: AAPL") -- match on the
                                    # stable numeric code instead of fragile message wording

HALT_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "risk" / "halt_state.json"


def check_market_open(trading_client: TradingClient) -> bool:
    return trading_client.get_clock().is_open  # type: ignore[reportAttributeAccessIssue]


def check_max_drawdown(trading_client: TradingClient, max_drawdown_pct: float) -> tuple[bool, float]:
    # pulls the account's own equity curve rather than tracking peak equity locally --
    # Alpaca is the single source of truth here, so there's no local state to drift out of sync
    history = trading_client.get_portfolio_history(
        GetPortfolioHistoryRequest(period="1A", timeframe="1D")
    )
    equity = [e for e in history.equity if e is not None]  # type: ignore[reportAttributeAccessIssue]
    if not equity:
        return False, 0.0

    peak = max(equity)
    current = equity[-1]
    drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
    return drawdown_pct >= max_drawdown_pct, drawdown_pct


def check_daily_loss(trading_client: TradingClient, max_daily_loss_pct: float) -> tuple[bool, float]:
    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    last_equity = float(account.last_equity)  # type: ignore[reportAttributeAccessIssue]
    if last_equity <= 0:
        return False, 0.0

    pnl_pct = (equity - last_equity) / last_equity
    return pnl_pct <= -max_daily_loss_pct, pnl_pct


def is_halted() -> bool:
    if not HALT_STATE_PATH.exists():
        return False
    return json.loads(HALT_STATE_PATH.read_text()).get("halted", False)


def set_halted(reason: str) -> None:
    HALT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HALT_STATE_PATH.write_text(json.dumps({
        "halted": True,
        "reason": reason,
        "halted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, indent=2))


def clear_halt() -> None:
    if HALT_STATE_PATH.exists():
        HALT_STATE_PATH.unlink()


def flatten_position(trading_client: TradingClient, symbol: str) -> None:
    try:
        trading_client.close_position(symbol)
    except APIError as e:
        # no open position is not an error worth raising over -- there's nothing to flatten
        if e.code != NO_POSITION_ERROR_CODE:
            raise
