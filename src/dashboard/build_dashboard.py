import csv
import datetime as dt
import html
import math
import statistics
from pathlib import Path

from alpaca.trading.requests import GetPortfolioHistoryRequest

from src.bar_config import BAR_CONFIG
from src.config import get_alpaca_client, get_alpaca_trading_client
from src.data.market_data import get_bars
from src.risk import risk_manager as rm
from src.strategy import aapl_sma
from src.trading import executor

# Static-site generator, not a server -- run once per workflow invocation (run_daily,
# eod_summary, intraday_check all call this as their last step) and the output is published to
# GitHub Pages via actions/upload-pages-artifact. Not committed to git: this writes to
# OUTPUT_DIR (gitignored), which only ever exists on the runner between generation and upload.
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "public"
TRADE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "orders" / "trade_log.csv"

STRATEGY_COLOR = "#58a6ff"
BENCHMARK_COLOR = "#d29922"

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
  .card h2 {{ font-size: 1rem; margin: 0 0 0.25rem 0; color: #8b949e; font-weight: 500; }}
  .card .subhead {{ font-size: 0.8rem; color: #6e7681; margin-bottom: 1rem; }}
  .legend {{ display: flex; gap: 1.5rem; font-size: 0.8rem; margin-top: 0.5rem; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
  .swatch {{ display: inline-block; width: 12px; height: 3px; border-radius: 2px; }}
  .axis-label {{ fill: #8b949e; font-size: 11px; font-family: inherit; }}
  .grid-line {{ stroke: #21262d; stroke-width: 1; }}
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
    <h2>Equity vs. {symbol} Buy &amp; Hold</h2>
    <div class="subhead">{chart_subhead}</div>
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
  <footer>
    Paper trading via Alpaca. Not investment advice.<br>
    This page reloads in your browser every 30 minutes, but the numbers only change when the bot
    actually runs (see "Last updated" above) -- roughly hourly during market hours, less often outside it.
  </footer>
</body>
</html>
"""


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    step = (hi - lo) / (count - 1)
    return [lo + step * i for i in range(count)]


def build_chart_svg(dates: list, equity_values: list[float], benchmark_values: list[float] | None,
                     width: int = 780, height: int = 240) -> str:
    if len(equity_values) < 2:
        return "<p style='color:#8b949e'>Not enough history yet.</p>"

    margin_left, margin_right, margin_top, margin_bottom = 65, 15, 15, 30
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    n = len(equity_values)

    all_values = list(equity_values) + (list(benchmark_values) if benchmark_values else [])
    lo, hi = min(all_values), max(all_values)
    span = (hi - lo) or 1.0

    def to_xy(i: int, v: float) -> tuple:
        x = margin_left + (i / (n - 1)) * plot_w
        y = margin_top + plot_h - ((v - lo) / span) * plot_h
        return x, y

    def path_for(values: list[float]) -> str:
        pts = [to_xy(i, v) for i, v in enumerate(values)]
        return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

    # y-axis: auto-scaled gridlines + $ labels from the actual combined data range
    y_ticks = _nice_ticks(lo, hi, 5)
    y_axis_svg = []
    for v in y_ticks:
        _, y = to_xy(0, v)
        y_axis_svg.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" class="grid-line"/>')
        y_axis_svg.append(f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" class="axis-label">${v:,.0f}</text>')

    # x-axis: 5 evenly spaced date labels, auto-scaled to the actual date range
    x_axis_svg = []
    n_x_ticks = min(5, n)
    for k in range(n_x_ticks):
        i = round(k * (n - 1) / (n_x_ticks - 1)) if n_x_ticks > 1 else 0
        x, _ = to_xy(i, equity_values[i])
        label = dates[i].strftime("%b %d") if dates else str(i)
        x_axis_svg.append(f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" class="axis-label">{label}</text>')

    strategy_path = f'<path d="{path_for(equity_values)}" fill="none" stroke="{STRATEGY_COLOR}" stroke-width="2"/>'
    benchmark_path = (
        f'<path d="{path_for(benchmark_values)}" fill="none" stroke="{BENCHMARK_COLOR}" '
        f'stroke-width="2" stroke-dasharray="5,4"/>' if benchmark_values else ""
    )

    legend = (
        '<div class="legend">'
        f'<span><span class="swatch" style="background:{STRATEGY_COLOR}"></span>Strategy</span>'
    )
    if benchmark_values:
        legend += f'<span><span class="swatch" style="background:{BENCHMARK_COLOR}"></span>Buy &amp; Hold</span>'
    legend += "</div>"

    svg = (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}">'
        + "".join(y_axis_svg) + "".join(x_axis_svg) + benchmark_path + strategy_path +
        "</svg>"
    )
    return svg + legend


def compute_sharpe_ratio(equity_values: list) -> float | None:
    # same (mean / std) * sqrt(bars_per_year) convention used throughout tests/ -- daily
    # portfolio history here plays the role a strategy's daily 'return' column plays there.
    # Returns None (rendered as "N/A") rather than 0 when there's not enough history yet or
    # zero variance, matching the NaN-on-degenerate-input guard used across the strategy files
    values = [e for e in equity_values if e]
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


def build_benchmark_series(symbol: str, dates: list) -> list[float] | None:
    # buy-and-hold comparison: what would the account's own starting dollar amount have been
    # worth just holding the symbol over the same window, pulled live from Alpaca each run
    # (get_bars routes this to Alpaca automatically -- these dates are always recent)
    if len(dates) < 2:
        return None

    try:
        df = get_bars(symbol, dates[0], dates[-1] + dt.timedelta(days=1), interval="1d")
    except Exception as e:
        print(f"Could not fetch benchmark data for {symbol}: {e}")
        return None

    closes_by_date = {row.timestamp.date(): row.close for row in df.itertuples()}

    last_close = None
    aligned_closes = []
    for d in dates:
        if d in closes_by_date:
            last_close = closes_by_date[d]
        aligned_closes.append(last_close)

    # nothing to align to before the first available close (e.g. symbol didn't trade yet)
    if aligned_closes[0] is None:
        first_valid = next((c for c in aligned_closes if c is not None), None)
        if first_valid is None:
            return None
        aligned_closes = [c if c is not None else first_valid for c in aligned_closes]

    base = aligned_closes[0]
    return [c / base for c in aligned_closes]


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
    data_client = get_alpaca_client()
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

    # Alpaca pads this series with literal 0.0 entries (not None) for every day before the
    # account had any real activity -- e.g. 230 padding days out of 250 on a month-old account.
    # Plotting those would show a long, meaningless flat "$0" line dominating the chart, which
    # is exactly the kind of uninformative axis-less chart this was meant to fix
    real_points = [
        (dt.datetime.fromtimestamp(t, dt.timezone.utc).date(), e)
        for t, e in zip(history.timestamp, history.equity)  # type: ignore[reportAttributeAccessIssue]
        if e
    ]

    if len(real_points) >= 2:
        dates = [d for d, _ in real_points]
        equity_series = [e for _, e in real_points]
        benchmark_ratios = build_benchmark_series(symbol, dates)
        benchmark_series = [equity_series[0] * r for r in benchmark_ratios] if benchmark_ratios else None

        chart_subhead = f"Since {dates[0].strftime('%b %d, %Y')}"
        if benchmark_ratios:
            strategy_return = equity_series[-1] / equity_series[0] - 1
            benchmark_return = benchmark_ratios[-1] - 1
            chart_subhead += f" -- Strategy {strategy_return:+.2%} vs. Buy & Hold {benchmark_return:+.2%}"
    else:
        dates, equity_series, benchmark_series = [], [], None
        chart_subhead = "Not enough history yet"

    equity_svg = build_chart_svg(dates, equity_series, benchmark_series)
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
        chart_subhead=chart_subhead,
        equity_svg=equity_svg,
        trade_rows=build_trade_rows_html(trades),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_out)
    print(f"Dashboard written to {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    run()
