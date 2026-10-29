import csv
import datetime as dt
import html
import math
import statistics
from pathlib import Path
from zoneinfo import ZoneInfo

from src.bar_config import BAR_CONFIG
from src.config import get_alpaca_trading_client
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

PORTFOLIO_URL = "https://jameslaprocido.com/"
REPO_URL = "https://github.com/jlaprocido/AlgoSystem082026"

# same palette as the portfolio site (jameslaprocido.com) -- keep these in sync with its :root
STRATEGY_COLOR = "#006747"
BENCHMARK_COLOR = "#418fde"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>{symbol} SMA Bot | James Laprocido</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #0f2e24; --paper: #f2f7fa; --panel: #fff; --rule: #cddbe3; --muted: #4b5e66;
    --accent: #006747; --soft: #dcecf9; --hero: #00432e; --sky: #71c5e8; --blue: #418fde;
    --neg: #b3261e;
    --serif: "Newsreader", Georgia, "Times New Roman", serif;
    --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
    color-scheme: light;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--paper); color: var(--ink);
    font: 400 17px/1.65 var(--sans); -webkit-font-smoothing: antialiased;
    min-height: 100vh; display: flex; flex-direction: column;
  }}
  a {{ color: var(--accent); text-underline-offset: 3px; }}
  .wrap {{ width: 100%; max-width: 960px; margin: 0 auto; padding: 0 20px; }}

  .site-header {{ background: var(--hero); color: #fff; }}
  .site-header .wrap {{ display: flex; justify-content: space-between; align-items: center; height: 52px; }}
  .brand {{ font: 600 1.15rem var(--serif); color: #fff; text-decoration: none; }}
  .site-header nav {{ display: flex; gap: 28px; }}
  .site-header nav a {{ color: #fff; text-decoration: none; font: 500 0.95rem var(--sans); }}
  .site-header nav a:hover {{ color: var(--sky); }}

  .hero {{ background: var(--hero); color: #fff; padding: 40px 0 44px; border-bottom: 6px solid var(--sky); }}
  .eyebrow {{ font: 600 .8rem var(--sans); letter-spacing: 0.12em; text-transform: uppercase; color: var(--sky); margin: 0 0 8px; }}
  h1 {{ font: 700 clamp(2.2rem, 5vw, 3.2rem)/1.1 var(--serif); margin: 0 0 12px; letter-spacing: -0.01em; }}
  .updated {{ color: #cfe3da; font-size: 0.9rem; margin: 20px 0 0; }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 20px; }}
  .btn {{
    display: inline-flex; align-items: center; justify-content: center; min-height: 48px; min-width: 150px;
    padding: 12px 24px; border-radius: 4px; text-decoration: none; font: 500 1rem var(--sans);
    background: #fff; color: var(--hero); border: 1px solid #fff; cursor: pointer;
  }}
  .btn:hover {{ opacity: 0.88; color: var(--hero); }}
  .btn--line {{ background: none; color: #fff; border-color: rgba(255,255,255,.7); }}
  .btn--line:hover {{ background: rgba(255,255,255,.12); color: #fff; opacity: 1; }}

  main {{ padding: 32px 0 8px; flex: 1; }}
  .halted-banner {{
    background: #fde8e6; border: 1px solid var(--neg); color: var(--neg);
    padding: 12px 16px; border-radius: 4px; margin-bottom: 24px; font-weight: 600;
  }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 32px; }}
  .stat {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 4px; padding: 16px 20px; }}
  .stat .label {{ color: var(--muted); font: 600 .75rem var(--sans); letter-spacing: 0.12em; text-transform: uppercase; }}
  .stat .value {{ font: 500 1.9rem/1.2 var(--serif); margin-top: 4px; }}
  .positive {{ color: var(--accent); }}
  .negative {{ color: var(--neg); }}

  .card {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 4px; padding: 20px; margin-bottom: 32px; }}
  .card h2 {{ font: 500 1.6rem/1.2 var(--serif); margin: 0 0 4px; letter-spacing: -0.01em; }}
  .card .subhead {{ font-size: 0.9rem; color: var(--muted); margin-bottom: 16px; }}
  .legend {{ display: flex; gap: 24px; font-size: 0.85rem; margin-top: 8px; color: var(--muted); }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
  .swatch {{ display: inline-block; width: 14px; height: 3px; border-radius: 2px; }}
  .axis-label {{ fill: var(--muted); font-size: 11px; font-family: var(--sans); }}
  .grid-line {{ stroke: var(--rule); stroke-width: 1; }}

  .table-wrap {{ max-height: 420px; overflow: auto; border: 1px solid var(--rule); border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--rule); white-space: nowrap; }}
  th {{
    position: sticky; top: 0; background: var(--soft); color: var(--ink);
    font: 600 .75rem var(--sans); letter-spacing: 0.1em; text-transform: uppercase;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .side-buy {{ color: var(--accent); font-weight: 600; }}
  .side-sell {{ color: var(--neg); font-weight: 600; }}
  .muted {{ color: var(--muted); }}
  .status-ok {{ color: var(--accent); font-weight: 600; }}
  .status-bad {{ color: var(--neg); font-weight: 600; }}

  footer {{ background: var(--hero); color: #cfe3da; border-top: 6px solid var(--sky); margin-top: 24px; padding: 24px 0; font-size: 0.85rem; }}

  @media (max-width: 640px) {{
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
    .btn {{ flex: 1 1 100%; }}
  }}
</style>
</head>
<body>
  <header class="site-header">
    <div class="wrap">
      <a class="brand" href="{portfolio_url}">James Laprocido</a>
      <nav><a href="{portfolio_url}">Portfolio</a><a href="{repo_url}">GitHub</a></nav>
    </div>
  </header>
  <section class="hero">
    <div class="wrap">
      <p class="eyebrow">Live paper trading</p>
      <h1>{symbol} SMA Bot</h1>
      <div class="actions">
        <a class="btn" href="{portfolio_url}">&larr; Portfolio</a>
        <a class="btn btn--line" href="{repo_url}">View code</a>
      </div>
      <p class="updated">Last updated: {updated_at} UTC</p>
    </div>
  </section>
  <main>
    <div class="wrap">
      {halted_banner}
      <div class="stats">
        <div class="stat"><div class="label">Equity</div><div class="value">${equity:,.2f}</div></div>
        <div class="stat"><div class="label">Today's PnL</div><div class="value {pnl_class}">{daily_pnl_pct:+.2%}</div></div>
        <div class="stat"><div class="label">Total PnL</div><div class="value {total_pnl_class}">{total_pnl_display}</div></div>
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
        <div class="subhead">{trade_count} entries, newest first. Scroll for the full log.</div>
        <div class="table-wrap">
        <table>
          <thead><tr><th>Date &amp; Time (UTC)</th><th>Signal</th><th>Side</th><th class="num">Qty</th><th class="num">Price</th><th>Status</th></tr></thead>
          <tbody>
            {trade_rows}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  </main>
  <footer>
    <div class="wrap">
      Paper trading via Alpaca. Not investment advice.<br>
      This page reloads in your browser every 30 minutes, but the numbers only change when the bot
      actually runs (see "Last updated" above) -- roughly hourly during market hours, less often outside it.
    </div>
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
        return "<p class='muted'>Not enough history yet.</p>"

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


def read_all_trades() -> list[dict]:
    # newest first; the table scrolls, so no row limit
    if not TRADE_LOG_PATH.exists():
        return []
    with open(TRADE_LOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))


def format_timestamp(raw: str) -> str:
    # trade log stores ISO-8601 UTC, e.g. 2026-09-11T13:33:07.596362+00:00 -> 09-11-2026 13:33:07
    try:
        return dt.datetime.fromisoformat(raw).astimezone(dt.timezone.utc).strftime("%m-%d-%Y %H:%M:%S")
    except ValueError:
        return raw


def format_status(raw: str) -> str:
    # "max_drawdown_breach_18.00%" -> "Max Drawdown Breach 18.00%"
    return raw.replace("_", " ").title()


def build_trade_rows_html(trades: list[dict]) -> str:
    if not trades:
        return '<tr><td colspan="6" class="muted">No activity logged yet.</td></tr>'

    signal_names = {"1": "Long", "0": "Flat"}
    rows = []
    for t in trades:
        side = (t.get("side") or "").lower()
        side_class = "side-buy" if side == "buy" else ("side-sell" if side == "sell" else "muted")
        raw_price = t.get("filled_avg_price") or t.get("limit_price") or ""
        price = f"${float(raw_price):,.2f}" if raw_price else "&mdash;"
        qty = t.get("qty") or ""
        qty_display = html.escape(qty) if qty and qty != "0" else "&mdash;"
        signal = signal_names.get(t.get("signal", ""), "&mdash;")
        status = t.get("status", "")
        status_class = "status-ok" if status == "filled" else ("status-bad" if "breach" in status or status == "halted" else "")
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_timestamp(t.get('timestamp', '')))}</td>"
            f"<td>{signal}</td>"
            f"<td class='{side_class}'>{html.escape(side.capitalize()) if side else '&mdash;'}</td>"
            f"<td class='num'>{qty_display}</td>"
            f"<td class='num'>{price}</td>"
            f"<td class='{status_class}'>{html.escape(format_status(status))}</td>"
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

    # dates/equity here already has Alpaca's pre-funding 0.0 padding stripped (see
    # get_real_equity_history's docstring) -- but the account can still sit funded-and-flat
    # for a while before the strategy's first real trade, so this trims further to start
    # exactly where the strategy itself started, not just where the account started. Both the
    # chart and every metric derived from it (Sharpe, Total PnL below) use this same window,
    # so "how has the strategy done" never gets diluted by weeks of doing nothing first.
    all_dates, all_equity = rm.get_real_equity_history(trading_client)

    # the history only has completed sessions -- add today's live equity as the last point so
    # the chart ends on the same number as the Equity tile (skipped on weekends: no session)
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()  # session date, not UTC date
    if today.weekday() < 5 and (not all_dates or all_dates[-1] < today):
        all_dates, all_equity = all_dates + [today], all_equity + [equity]

    strategy_start = executor.find_strategy_start_date()
    if strategy_start:
        trimmed = [(d, e) for d, e in zip(all_dates, all_equity) if d >= strategy_start]
        dates = [d for d, _ in trimmed]
        equity_series = [e for _, e in trimmed]
    else:
        dates, equity_series = all_dates, all_equity

    total_pnl_pct = total_pnl_dollars = None
    if len(equity_series) >= 1:
        total_pnl_dollars = equity - equity_series[0]
        total_pnl_pct = equity / equity_series[0] - 1

    if len(dates) >= 2:
        benchmark_ratios = build_benchmark_series(symbol, dates)
        benchmark_series = [equity_series[0] * r for r in benchmark_ratios] if benchmark_ratios else None

        since_label = "first trade" if strategy_start else "account funded, no trades yet"
        chart_subhead = f"Since {dates[0].strftime('%b %d, %Y')} ({since_label})"
        if benchmark_ratios:
            benchmark_return = benchmark_ratios[-1] - 1
            chart_subhead += f" -- Strategy {total_pnl_pct:+.2%} vs. Buy & Hold {benchmark_return:+.2%}"
    else:
        dates, equity_series, benchmark_series = [], [], None
        chart_subhead = "Not enough history yet -- no trades placed"

    equity_svg = build_chart_svg(dates, equity_series, benchmark_series)
    sharpe_ratio = compute_sharpe_ratio(equity_series)

    trades = read_all_trades()

    html_out = PAGE_TEMPLATE.format(
        symbol=symbol,
        portfolio_url=PORTFOLIO_URL,
        repo_url=REPO_URL,
        updated_at=dt.datetime.now(dt.timezone.utc).strftime("%m-%d-%Y %H:%M:%S"),
        halted_banner=(
            '<div class="halted-banner">HALTED -- max drawdown previously breached, '
            "awaiting manual review</div>" if halted else ""
        ),
        equity=equity,
        daily_pnl_pct=daily_pnl_pct,
        pnl_class="positive" if daily_pnl_pct >= 0 else "negative",
        total_pnl_display=f"{total_pnl_pct:+.2%}" if total_pnl_pct is not None else "N/A",
        total_pnl_class=("positive" if total_pnl_pct >= 0 else "negative") if total_pnl_pct is not None else "",
        drawdown_pct=drawdown_pct,
        sharpe_display=f"{sharpe_ratio:.2f}" if sharpe_ratio is not None else "N/A",
        current_shares=current_shares,
        chart_subhead=chart_subhead,
        equity_svg=equity_svg,
        trade_count=len(trades),
        trade_rows=build_trade_rows_html(trades),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_out, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    run()
