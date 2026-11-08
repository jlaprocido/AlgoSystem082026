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

RISK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "risk"

# GLOBAL kill switch: one halt file for the whole account. A max-drawdown breach is measured on
# account equity, so it stops every strategy at once and needs a human to clear it.
HALT_STATE_PATH = RISK_DIR / "halt_state.json"


def daily_loss_path(strategy: str) -> Path:
    # PER-STRATEGY state: each strategy remembers its own "already cut/flattened today", so a bad
    # day in one strategy does not silence (or re-trigger) another
    return RISK_DIR / f"daily_loss_{strategy}.json"


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

    # the history's last point is a session old (it's stamped a day late), so a drop today
    # wouldn't register until tomorrow -- compare the live account equity against the peak instead
    current = float(trading_client.get_account().equity)  # type: ignore[reportAttributeAccessIssue]
    peak = max(max(equity), current)
    drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
    return drawdown_pct >= max_drawdown_pct, drawdown_pct


def get_real_equity_history(trading_client: TradingClient) -> tuple[list, list]:
    """Returns (dates, equity_values) with Alpaca's padding stripped out. get_portfolio_history
    pads every day before the account had any real activity with a literal 0.0 (not None) --
    e.g. 230 padding days out of 250 on a month-old account -- which would otherwise dominate
    any chart or calculation built from this with a meaningless flat "$0" stretch. Shared by
    eod_summary.py (total PnL) and build_dashboard.py (equity chart, Sharpe ratio)."""
    history = trading_client.get_portfolio_history(
        GetPortfolioHistoryRequest(period="1A", timeframe="1D")
    )
    # Alpaca stamps each daily point with the day AFTER its session (Mon's close comes back
    # stamped Tue, Fri's stamped Sat), so shift back one day to get the real trading date --
    # without this the curve lags a same-date price series (e.g. the buy-and-hold benchmark)
    # by one trading day. Checked against AAPL daily returns: corr 0.86 shifted vs. -0.11 not.
    real_points = [
        (dt.datetime.fromtimestamp(t, dt.timezone.utc).date() - dt.timedelta(days=1), e)
        for t, e in zip(history.timestamp, history.equity)  # type: ignore[reportAttributeAccessIssue]
        if e
    ]
    dates = [d for d, _ in real_points]
    equity = [e for _, e in real_points]
    return dates, equity


def get_position_move_today(trading_client: TradingClient, symbol: str) -> float:
    # the held position's % change since yesterday's close, i.e. the asset's own move
    # (unlevered) -- 0.0 when flat, since there is nothing at risk to react to.
    # `symbol` is the POSITION symbol (BTCUSD, not BTC/USD) -- see assets.position_symbol
    try:
        position = trading_client.get_open_position(symbol)
    except APIError as e:
        if e.code == NO_POSITION_ERROR_CODE:
            return 0.0
        raise
    return float(position.unrealized_intraday_plpc)  # type: ignore[reportAttributeAccessIssue]


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


def get_daily_loss_level(strategy: str) -> str | None:
    # daily-loss breaches self-clear the next trading day (unlike the drawdown halt), but
    # within the *same* day this needs its own memory: intraday_check.py can call
    # check_risk_limits() several times before the day rolls over, and without this a move
    # that's still breached on the next check would act and re-notify every single time.
    # Returns what was already done today ("reduced" or "flattened"), or None.
    path = daily_loss_path(strategy)
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    return state.get("level") if state.get("handled_date") == dt.date.today().isoformat() else None


def set_daily_loss_level(strategy: str, level: str) -> None:
    path = daily_loss_path(strategy)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"handled_date": dt.date.today().isoformat(), "level": level}))


def flatten_all(trading_client: TradingClient) -> None:
    # the global kill switch sells every position in the account, whichever strategy opened it
    trading_client.close_all_positions(cancel_orders=True)


def flatten_position(trading_client: TradingClient, symbol: str) -> None:
    try:
        trading_client.close_position(symbol)
    except APIError as e:
        # no open position is not an error worth raising over -- there's nothing to flatten
        if e.code != NO_POSITION_ERROR_CODE:
            raise
