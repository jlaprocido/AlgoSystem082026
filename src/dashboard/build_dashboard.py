import csv
import datetime as dt
import html
import math
import statistics
from pathlib import Path

from alpaca.trading.requests import GetPortfolioHistoryRequest

from src.bar_config import BAR_CONFIG
from src.config import get_alpaca_trading_client
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading import executor

# Static-site generator, not a server -- run once per workflow invocation (run_daily,
# eod_summary, intraday_check all call this as their last step) and the output is published to
# GitHub Pages via actions/upload-pages-artifact. Not committed to git: this writes to
# OUTPUT_DIR (gitignored), which only ever exists on the runner between generation and upload.
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "public"
TRADE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "orders" / "trade_log.csv"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>{symbol} SMA Bot Dashboard</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    background: #0d1117; color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 900px; margin: 0 auto; padding: 2rem 1rem;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  .updated {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .halted-banner {{
    background: #3d1418; border: 1px solid #f85149; color: #ffa198;
    padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; font-weight: 600;
  }}
  .stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem; margin-bottom: 2rem;
  }}
  .stat {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1rem; }}
  .stat .label {{ color: #8b949e; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  .stat .value {{ font-size: 1.5rem; font-weight: 600; margin-top: 0.25rem; }}
  .positive {{ color: #3fb950; }}
  .negative {{ color: #f85149; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1rem; margin-bottom: 2rem; }}
  .card h2 {{ font-size: 1rem; margin: 0 0 1rem 0; color: #8b949e; font-weight: 500; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid #30363d; white-space: nowrap; }}
  th {{ color: #8b949e; font-weight: 500; }}
  .side-buy {{ color: #3fb950; }}
  .side-sell {{ color: #f85149; }}
  .table-wrap {{ overflow-x: auto; }}
  footer {{ color: #6e7681; font-size: 0.8rem; text-align: center; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>{symbol} SMA Bot</h1>
  <div class="updated">Last updated: {updated_at} UTC</div>
  {halted_banner}
  <div class="stats">
    <div class="stat"><div class="label">Equity</div><div class="value">${equity:,.2f}</div></div>
    <div class="stat"><div class="label">Today's PnL</div><div class="value {pnl_class}">{daily_pnl_pct:+.2%}</div></div>
    <div class="stat"><div class="label">Drawdown from Peak</div><div class="value">{drawdown_pct:.2%}</div></div>
    <div class="stat"><div class="label">Sharpe Ratio</div><div class="value">{sharpe_display}</div></div>
    <div class="stat"><div class="label">Position</div><div class="value">{current_shares} sh</div></div>
  </div>
  <div class="card">
    <h2>Equity -- past year</h2>
    {equity_svg}
  </div>
  <div class="card">
    <h2>Recent Activity</h2>
    <div class="table-wrap">
    <table>
      <thead><tr><th>Time (UTC)</th><th>Signal</th><th>Side</th><th>Qty</th><th>Price</th><th>Status</th></tr></thead>
      <tbody>
        {trade_rows}
      </tbody>
    </table>
    </div>
  </div>
  <footer>Paper trading via Alpaca. Not investment advice. Auto-refreshes every 30 minutes.</footer>
</body>
</html>
"""


def build_equity_svg(equity_values: list, width: int = 760, height: int = 180) -> str:
    values = [e for e in equity_values if e is not None]
    if len(values) < 2:
        return "<p style='color:#8b949e'>Not enough history yet.</p>"

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * (width - 20) + 10
        y = height - 10 - ((v - lo) / span) * (height - 20)
        points.append(f"{x:.1f},{y:.1f}")

    path = "M " + " L ".join(points)
    color = "#3fb950" if values[-1] >= values[0] else "#f85149"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none"><path d="{path}" fill="none" stroke="{color}" stroke-width="2"/></svg>'
    )


def compute_sharpe_ratio(equity_values: list) -> float | None:
    # same (mean / std) * sqrt(bars_per_year) convention used throughout tests/ -- daily
    # portfolio history here plays the role a strategy's daily 'return' column plays there.
    # Returns None (rendered as "N/A") rather than 0 when there's not enough history yet or
    # zero variance, matching the NaN-on-degenerate-input guard used across the strategy files
    values = [e for e in equity_values if e is not None]
    if len(values) < 2:
        return None

    returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0]
    if len(returns) < 2:
        return None

    std_r = statistics.stdev(returns)
    if std_r == 0:
        return None

    bars_per_year = BAR_CONFIG["1d"]["bars_per_year"]
    return (statistics.mean(returns) / std_r) * math.sqrt(bars_per_year)


def read_recent_trades(limit: int = 20) -> list[dict]:
    if not TRADE_LOG_PATH.exists():
        return []
    with open(TRADE_LOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]


def build_trade_rows_html(trades: list[dict]) -> str:
    if not trades:
        return '<tr><td colspan="6" style="color:#8b949e">No activity logged yet.</td></tr>'

    rows = []
    for t in trades:
        side = (t.get("side") or "").lower()
        side_class = "side-buy" if side == "buy" else ("side-sell" if side == "sell" else "")
        price = t.get("filled_avg_price") or t.get("limit_price") or ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(t.get('timestamp', ''))}</td>"
            f"<td>{html.escape(t.get('signal', ''))}</td>"
            f"<td class='{side_class}'>{html.escape(side.upper())}</td>"
            f"<td>{html.escape(str(t.get('qty', '')))}</td>"
            f"<td>{html.escape(str(price))}</td>"
            f"<td>{html.escape(t.get('status', ''))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def run() -> None:
    trading_client = get_alpaca_trading_client()
    symbol = aapl_sma.SYMBOL

    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    last_equity = float(account.last_equity)  # type: ignore[reportAttributeAccessIssue]
    daily_pnl_pct = (equity - last_equity) / last_equity if last_equity > 0 else 0.0

    # max_drawdown_pct=1.0 means this can never "breach" -- reusing check_max_drawdown purely
    # for the current drawdown-from-peak number it already computes, read-only, same pattern
    # eod_summary.py uses
    _, drawdown_pct = rm.check_max_drawdown(trading_client, max_drawdown_pct=1.0)
    current_shares = executor.get_current_shares(trading_client, symbol)
    halted = rm.is_halted()

    history = trading_client.get_portfolio_history(
        GetPortfolioHistoryRequest(period="1A", timeframe="1D")
    )
    equity_svg = build_equity_svg(history.equity)  # type: ignore[reportAttributeAccessIssue]
    sharpe_ratio = compute_sharpe_ratio(history.equity)  # type: ignore[reportAttributeAccessIssue]

    trades = read_recent_trades()

    html_out = PAGE_TEMPLATE.format(
        symbol=symbol,
        updated_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        halted_banner=(
            '<div class="halted-banner">HALTED -- max drawdown previously breached, '
            "awaiting manual review</div>" if halted else ""
        ),
        equity=equity,
        daily_pnl_pct=daily_pnl_pct,
        pnl_class="positive" if daily_pnl_pct >= 0 else "negative",
        drawdown_pct=drawdown_pct,
        sharpe_display=f"{sharpe_ratio:.2f}" if sharpe_ratio is not None else "N/A",
        current_shares=current_shares,
        equity_svg=equity_svg,
        trade_rows=build_trade_rows_html(trades),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_out)
    print(f"Dashboard written to {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    run()
