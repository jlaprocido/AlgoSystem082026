import csv
import datetime as dt
import html
import math
import statistics
from pathlib import Path
from zoneinfo import ZoneInfo

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from src.bar_config import BAR_CONFIG
from src.config import get_alpaca_trading_client
from src.dashboard import performance
from src.data.market_data import get_bars
from src.risk import risk_manager as rm
from src.strategy.registry import REGISTRY, Strategy
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
<title>Algo Portfolio | James Laprocido</title>
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

  h2.section {{ font: 500 1.6rem/1.2 var(--serif); margin: 8px 0 16px; letter-spacing: -0.01em; }}
  .strategy-head {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }}
  .tag {{ display: inline-block; font: 600 .7rem var(--sans); letter-spacing: 0.1em; text-transform: uppercase;
          background: var(--soft); color: var(--ink); border-radius: 3px; padding: 2px 8px; margin-left: 6px; }}
  .tag.crypto {{ background: #fdf1d8; }}
  .mini-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 12px 0 16px; }}
  .mini .label {{ color: var(--muted); font: 600 .7rem var(--sans); letter-spacing: 0.1em; text-transform: uppercase; }}
  .mini .value {{ font: 500 1.3rem/1.3 var(--serif); }}
  .status-line {{ font-size: 0.85rem; color: var(--muted); margin-top: 10px; }}

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
    .mini-stats {{ grid-template-columns: repeat(2, 1fr); }}
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
      <h1>Algo Portfolio</h1>
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
        <div class="stat"><div class="label">Open Positions</div><div class="value">{open_positions}</div></div>
      </div>
      <div class="card">
        <h2>Portfolio Equity vs. SPY Buy &amp; Hold</h2>
        <div class="subhead">{chart_subhead}</div>
        {equity_svg}
      </div>
      <h2 class="section">Strategies</h2>
      {strategy_cards}
      <div class="card">
        <h2>Recent Activity</h2>
        <div class="subhead">{trade_count} entries, newest first. Scroll for the full log.</div>
        <div class="table-wrap">
        <table>
          <thead><tr><th>Date &amp; Time (UTC)</th><th>Strategy</th><th>Symbol</th><th>Signal</th><th>Side</th><th class="num">Qty</th><th class="num">Price</th><th>Status</th></tr></thead>
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
      Each strategy's curve is rebuilt from its own filled orders at daily closes, with its sleeve of the account
      as starting capital (so a 2x strategy's swings show up at 2x). It ignores crypto fees that Alpaca takes in coins.
      The page reloads every 30 minutes, but numbers only change when a bot runs (see "Last updated").
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
                     width: int = 780, height: int = 240, strategy_label: str = "Strategy") -> str:
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
    money = "${:,.0f}" if span >= 50 else "${:,.2f}"  # small sleeves (a few hundred dollars) need cents
    y_axis_svg = []
    for v in y_ticks:
        _, y = to_xy(0, v)
        y_axis_svg.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" class="grid-line"/>')
        y_axis_svg.append(f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" class="axis-label">{money.format(v)}</text>')

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
        f'<span><span class="swatch" style="background:{STRATEGY_COLOR}"></span>{strategy_label}</span>'
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

    closes_by_date = {row.timestamp.date(): row.close for row in df.itertuples()}  # type: ignore[reportAttributeAccessIssue]

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
        return '<tr><td colspan="8" class="muted">No activity logged yet.</td></tr>'

    signal_names = {"1": "Long", "0": "Flat"}
    rows = []
    for t in trades:
        side = (t.get("side") or "").lower()
        side_class = "side-buy" if side == "buy" else ("side-sell" if side == "sell" else "muted")
        raw_price = t.get("filled_avg_price") or t.get("limit_price") or ""
        price = f"${float(raw_price):,.2f}" if raw_price else "&mdash;"
        strategy = html.escape(performance.canonical_strategy(t.get("strategy", "")))
        symbol = html.escape(t.get("symbol", ""))
        qty = t.get("qty") or ""
        qty_display = html.escape(qty) if qty and qty != "0" else "&mdash;"
        signal = signal_names.get(t.get("signal", ""), "&mdash;")
        status = t.get("status", "")
        status_class = "status-ok" if status == "filled" else ("status-bad" if "breach" in status or status == "halted" else "")
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_timestamp(t.get('timestamp', '')))}</td>"
            f"<td>{strategy}</td>"
            f"<td>{symbol}</td>"
            f"<td>{signal}</td>"
            f"<td class='{side_class}'>{html.escape(side.capitalize()) if side else '&mdash;'}</td>"
            f"<td class='num'>{qty_display}</td>"
            f"<td class='num'>{price}</td>"
            f"<td class='{status_class}'>{html.escape(format_status(status))}</td>"
            "</tr>"
        )
    return "\n".join(rows)




def _signed(value: float, pct: bool = True) -> tuple[str, str]:
    """(text, css class) for a number that is good when positive."""
    text = f"{value:+.2%}" if pct else f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"
    return text, "positive" if value >= 0 else "negative"


def _fmt_qty(st: Strategy, symbol: str, qty: float) -> str:
    if st.asset.name == "stock":
        return f"{int(qty)} sh"
    return f"{qty:.6f}".rstrip("0").rstrip(".") + " " + symbol.split("/")[0]


def _mini(label: str, value: str, css: str = "") -> str:
    return f'<div class="mini"><div class="label">{label}</div><div class="value {css}">{value}</div></div>'


def equity_on(dates: list, equity: list[float], day: dt.date, fallback: float) -> float:
    """Account equity at the close of `day` (or the nearest earlier point)."""
    earlier = [e for d, e in zip(dates, equity) if d <= day]
    return earlier[-1] if earlier else (equity[0] if equity else fallback)


def build_strategy_card(st: Strategy, fills: list[dict], closes: dict[str, dict], capital: float,
                        positions: dict, latest: dict | None, end: dt.date) -> str:
    asset = st.asset
    lev = f" &middot; {st.leverage:g}x" if st.leverage != 1 else ""
    subhead = (f"{html.escape(', '.join(st.symbols))} &middot; {st.interval} bars &middot; "
               f"sleeve {st.allocation_pct:.0%} of equity{lev}")

    held = [(s, positions.get(asset.position_symbol(s))) for s in st.symbols]
    held = [(s, p) for s, p in held if p is not None and float(p.qty) != 0]  # type: ignore[reportAttributeAccessIssue]
    if held:
        position = "<br>".join(_fmt_qty(st, s, float(p.qty)) for s, p in held)  # type: ignore[reportAttributeAccessIssue]
        position_value = sum(float(p.market_value) for _, p in held)  # type: ignore[reportAttributeAccessIssue]
        position += f' <span class="muted" style="font-size:.8rem">(${position_value:,.2f})</span>'
    else:
        position = "Flat"

    if latest:
        signal = {"1": "Long", "0": "Flat"}.get(latest.get("signal", ""), "&mdash;")
        status_line = (f"Last run: {html.escape(format_timestamp(latest.get('timestamp', '')))} UTC &middot; "
                       f"signal {signal} &middot; {html.escape(format_status(latest.get('status', '')))}")
    else:
        status_line = "Not run yet &mdash; waiting for the first scheduled run."

    if not fills:
        minis = _mini("Position", position) + _mini("Trades", "0") + _mini("Return", "N/A") + _mini("Sleeve", f"${capital:,.0f}")
        chart = "<p class='muted'>No filled trades yet, so there is no curve to draw. It appears after the first fill.</p>"
        body_sub = "Waiting for its first trade"
    else:
        dates, values, bench = performance.strategy_curve(fills, closes, capital, end)
        ret = values[-1] / capital - 1
        bench_ret = bench[-1] / capital - 1
        ppy = asset.bars_per_year["1d"]
        sharpe = performance.sharpe(values, ppy)
        ret_txt, ret_css = _signed(ret)
        pnl_txt, pnl_css = _signed(values[-1] - capital, pct=False)
        edge_txt, edge_css = _signed(ret - bench_ret)
        minis = (
            _mini("Return on sleeve", ret_txt, ret_css)
            + _mini("vs. Buy &amp; Hold", edge_txt, edge_css)
            + _mini("PnL", pnl_txt, pnl_css)
            + _mini("Position", position)
            + _mini("Sharpe", f"{sharpe:.2f}" if sharpe is not None else "N/A")
            + _mini("Max drawdown", f"{performance.max_drawdown(values):.2%}")
            + _mini("Trades", str(len(fills)))
            + _mini("Buy &amp; Hold", f"{bench_ret:+.2%}")
        )
        chart = build_chart_svg(dates, values, bench, height=190, strategy_label=html.escape(st.name))
        body_sub = f"Since {dates[0].strftime('%b %d, %Y')} (first fill)"

    return (
        '<div class="card">'
        f'<div class="strategy-head"><h2>{html.escape(st.name)}<span class="tag {asset.name}">{asset.name}</span></h2>'
        f'<div class="subhead">{subhead}</div></div>'
        f'<div class="subhead">{body_sub}</div>'
        f'<div class="mini-stats">{minis}</div>{chart}'
        f'<div class="status-line">{status_line}</div>'
        '</div>'
    )


def fetch_fills(trading_client) -> dict[str, list[dict]]:
    """Every filled order, grouped by the strategy that owns the symbol. Read from Alpaca rather
    than the trade log, which never records the fills of risk liquidations (see performance.py)."""
    owner = {sym: st.name for st in REGISTRY.values() if st.allocation_pct > 0 for sym in st.symbols}
    # Alpaca names crypto positions BTCUSD but its orders keep BTC/USD, so orders match registry symbols
    orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500))  # type: ignore[reportAttributeAccessIssue]
    if len(orders) >= 500:
        print("Warning: hit Alpaca's 500-order page limit -- older fills are missing from the strategy cards.")
    return performance.fills_from_orders(orders, owner)  # type: ignore[reportArgumentType]


def fetch_closes(st: Strategy, start: dt.date, end: dt.date) -> dict[str, dict]:
    """Daily closes per symbol; a data failure leaves that symbol out (the card falls back to fill prices)."""
    out = {}
    for sym in st.symbols:
        try:
            df = st.asset.get_bars(sym, start, end + dt.timedelta(days=1), "1d")
            out[sym] = {row.timestamp.date(): row.close for row in df.itertuples()}  # type: ignore[reportAttributeAccessIssue]
        except Exception as e:
            print(f"Could not fetch prices for {sym}: {e}")
    return out


def run() -> None:
    trading_client = get_alpaca_trading_client()

    account = trading_client.get_account()
    equity = float(account.equity)  # type: ignore[reportAttributeAccessIssue]
    last_equity = float(account.last_equity)  # type: ignore[reportAttributeAccessIssue]
    daily_pnl_pct = (equity - last_equity) / last_equity if last_equity > 0 else 0.0
    positions = {p.symbol: p for p in trading_client.get_all_positions()}  # type: ignore[reportAttributeAccessIssue]

    # max_drawdown_pct=1.0 means this can never "breach" -- reusing check_max_drawdown purely
    # for the current drawdown-from-peak number it already computes, read-only, same pattern
    # eod_summary.py uses
    _, drawdown_pct = rm.check_max_drawdown(trading_client, max_drawdown_pct=1.0)
    halted = rm.is_halted()

    # dates/equity here already has Alpaca's pre-funding 0.0 padding stripped (see
    # get_real_equity_history's docstring) -- but the account can still sit funded-and-flat
    # for a while before the first real trade, so this trims further to start exactly where
    # trading started, not just where the account started. Both the chart and every metric
    # derived from it (Sharpe, Total PnL below) use this same window.
    all_dates, all_equity = rm.get_real_equity_history(trading_client)

    # the history only has completed sessions -- add today's live equity as the last point so
    # the chart ends on the same number as the Equity tile. Skipped on weekends unless crypto is
    # held, because crypto is the only thing that moves the account then.
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()  # session date, not UTC date
    crypto_open = any(s.asset.name == "crypto" and s.asset.position_symbol(s.symbols[0]) in positions
                      for s in REGISTRY.values())
    if (today.weekday() < 5 or crypto_open) and (not all_dates or all_dates[-1] < today):
        all_dates, all_equity = all_dates + [today], all_equity + [equity]

    strategy_start = executor.find_strategy_start_date()
    if strategy_start:
        trimmed = [(d, e) for d, e in zip(all_dates, all_equity) if d >= strategy_start]
        dates = [d for d, _ in trimmed]
        equity_series = [e for _, e in trimmed]
    else:
        dates, equity_series = all_dates, all_equity

    total_pnl_pct = None
    if len(equity_series) >= 1:
        total_pnl_pct = equity / equity_series[0] - 1

    if len(dates) >= 2:
        # the whole portfolio is compared with SPY (the stock benchmark in claude.md); each
        # strategy card below compares against buy-and-hold of its own symbols instead
        benchmark_ratios = build_benchmark_series("SPY", dates)
        benchmark_series = [equity_series[0] * r for r in benchmark_ratios] if benchmark_ratios else None

        since_label = "first trade" if strategy_start else "account funded, no trades yet"
        chart_subhead = f"Since {dates[0].strftime('%b %d, %Y')} ({since_label})"
        if benchmark_ratios:
            benchmark_return = benchmark_ratios[-1] - 1
            chart_subhead += f" -- Portfolio {total_pnl_pct:+.2%} vs. SPY Buy & Hold {benchmark_return:+.2%}"
    else:
        dates, equity_series, benchmark_series = [], [], None
        chart_subhead = "Not enough history yet -- no trades placed"

    equity_svg = build_chart_svg(dates, equity_series, benchmark_series, strategy_label="Portfolio")
    sharpe_ratio = compute_sharpe_ratio(equity_series)

    trades = read_all_trades()  # newest first
    fills = fetch_fills(trading_client)
    latest = {}
    for t in trades:  # first hit per strategy = its newest row
        latest.setdefault(performance.canonical_strategy(t.get("strategy", "")), t)

    cards = []
    for st in REGISTRY.values():
        if st.allocation_pct <= 0:
            continue  # research-only: backtest with src.backtest.lab, no live card
        mine = fills.get(st.name, [])
        start = mine[0]["date"] if mine else today
        # capital = this strategy's sleeve of the account as it stood when the strategy started
        capital = st.allocation_pct * equity_on(all_dates, all_equity, start, equity)
        closes = fetch_closes(st, start, today) if mine else {}
        cards.append(build_strategy_card(st, mine, closes, capital, positions, latest.get(st.name), today))
    research = [s.name for s in REGISTRY.values() if s.allocation_pct <= 0]
    if research:
        cards.append(f'<p class="muted">Research-only (backtest, not trading): {html.escape(", ".join(research))}</p>')

    html_out = PAGE_TEMPLATE.format(
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
        open_positions=len(positions),
        chart_subhead=chart_subhead,
        equity_svg=equity_svg,
        strategy_cards="\n".join(cards),
        trade_count=len(trades),
        trade_rows=build_trade_rows_html(trades),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_out, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    run()
