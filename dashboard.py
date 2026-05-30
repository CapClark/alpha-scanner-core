"""
Dashboard Generator
Reads trade_log.csv + price cache, builds a self-contained HTML dashboard.
Called automatically by tracker.py after each daily update.

Usage:
    python3 dashboard.py          # generates datasets/dashboard.html
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

TRADE_LOG  = Path("datasets/trade_log.csv")
CACHE_DIR  = Path("datasets/cache")
OUTPUT     = Path("datasets/dashboard.html")


# ── Data helpers ───────────────────────────────────────────────────────────────

def load_trades() -> pd.DataFrame:
    if not TRADE_LOG.exists():
        return pd.DataFrame()
    df = pd.read_csv(TRADE_LOG, dtype=str)
    for col in ["entry_price", "exit_price", "pnl_usd", "pnl_pct", "qty", "robustness"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_current_price(ticker: str) -> float | None:
    path = CACHE_DIR / f"{ticker}_prices.csv"
    try:
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        return float(df["Close"].dropna().iloc[-1])
    except Exception:
        return None


def enrich_open_positions(df: pd.DataFrame) -> list[dict]:
    open_trades = df[df["status"] == "OPEN"].copy()
    rows = []
    for _, r in open_trades.iterrows():
        curr = get_current_price(r["ticker"])
        if curr and pd.notna(r["entry_price"]) and pd.notna(r["qty"]):
            unreal_usd = round((curr - r["entry_price"]) * r["qty"], 2)
            unreal_pct = round((curr - r["entry_price"]) / r["entry_price"] * 100, 2)
        else:
            unreal_usd = None
            unreal_pct = None
        rows.append({
            "ticker":      r["ticker"],
            "strategy":    r["strategy"],
            "entry_date":  r["entry_date"],
            "entry_price": r["entry_price"],
            "qty":         int(r["qty"]) if pd.notna(r["qty"]) else "—",
            "curr_price":  round(curr, 2) if curr else None,
            "unreal_usd":  unreal_usd,
            "unreal_pct":  unreal_pct,
            "cost_basis":  round(r["entry_price"] * r["qty"], 2) if pd.notna(r["entry_price"]) and pd.notna(r["qty"]) else None,
        })
    return rows


def build_stats(df: pd.DataFrame) -> dict:
    closed = df[df["status"] == "CLOSED"].copy()
    open_  = df[df["status"] == "OPEN"]

    if closed.empty:
        return {
            "total_pnl": 0, "win_rate": 0, "profit_factor": 0,
            "avg_win": 0, "avg_loss": 0, "total_trades": len(df),
            "closed_trades": 0, "open_trades": len(open_),
            "stop_losses": 0, "signal_exits": 0,
        }

    winners = closed[closed["pnl_usd"] > 0]
    losers  = closed[closed["pnl_usd"] <= 0]
    gross_win  = winners["pnl_usd"].sum() if not winners.empty else 0
    gross_loss = abs(losers["pnl_usd"].sum()) if not losers.empty else 0

    return {
        "total_pnl":     round(float(closed["pnl_usd"].sum()), 2),
        "win_rate":      round(len(winners) / len(closed) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_win":       round(float(winners["pnl_usd"].mean()), 2) if not winners.empty else 0,
        "avg_loss":      round(float(losers["pnl_usd"].mean()), 2) if not losers.empty else 0,
        "total_trades":  len(df),
        "closed_trades": len(closed),
        "open_trades":   len(open_),
        "stop_losses":   int((closed["exit_reason"] == "stop_loss").sum()),
        "signal_exits":  int((closed["exit_reason"] == "signal").sum()),
    }


def build_equity_curve(df: pd.DataFrame) -> list[dict]:
    closed = df[df["status"] == "CLOSED"].copy()
    if closed.empty:
        return []
    closed = closed.sort_values("exit_date")
    closed["cum_pnl"] = closed["pnl_usd"].cumsum()
    return [{"date": r["exit_date"], "pnl": round(float(r["cum_pnl"]), 2)}
            for _, r in closed.iterrows()]


def build_trade_bars(df: pd.DataFrame) -> list[dict]:
    closed = df[df["status"] == "CLOSED"].copy()
    if closed.empty:
        return []
    closed = closed.sort_values("exit_date")
    return [{"label": f"{r['ticker']} ({r['exit_date']})",
             "pnl": round(float(r["pnl_usd"]), 2),
             "win": float(r["pnl_usd"]) > 0}
            for _, r in closed.iterrows()]


def build_strategy_breakdown(df: pd.DataFrame) -> list[dict]:
    closed = df[df["status"] == "CLOSED"].copy()
    if closed.empty:
        return []
    grp = closed.groupby("strategy")["pnl_usd"].sum().round(2).sort_values()
    return [{"strategy": s, "pnl": float(p)} for s, p in grp.items()]


def build_closed_table(df: pd.DataFrame) -> list[dict]:
    closed = df[df["status"] == "CLOSED"].copy()
    if closed.empty:
        return []
    closed = closed.sort_values("exit_date", ascending=False)
    rows = []
    for _, r in closed.iterrows():
        rows.append({
            "ticker":      r["ticker"],
            "strategy":    r["strategy"],
            "entry_date":  r["entry_date"],
            "exit_date":   r["exit_date"],
            "entry_price": r["entry_price"],
            "exit_price":  r["exit_price"],
            "qty":         int(r["qty"]) if pd.notna(r["qty"]) else "—",
            "pnl_usd":     round(float(r["pnl_usd"]), 2),
            "pnl_pct":     round(float(r["pnl_pct"]), 2),
            "exit_reason": r["exit_reason"],
        })
    return rows


# ── HTML template ──────────────────────────────────────────────────────────────

def render_html(stats: dict, equity: list, bars: list, strat: list,
                closed_rows: list, open_rows: list, generated_at: str) -> str:

    def fmt_usd(v):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:,.2f}"

    def fmt_pct(v):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    pnl_class = "positive" if stats["total_pnl"] >= 0 else "negative"

    # Open positions rows
    open_html = ""
    for r in open_rows:
        u_class = "positive" if r["unreal_usd"] and r["unreal_usd"] >= 0 else "negative"
        open_html += f"""
        <tr>
          <td><span class="ticker-badge">{r['ticker']}</span></td>
          <td>{r['strategy']}</td>
          <td>{r['entry_date']}</td>
          <td>${r['entry_price']:,.2f}</td>
          <td>{r['qty']}</td>
          <td>${r['curr_price']:,.2f}</td>
          <td class="{u_class}">{fmt_usd(r['unreal_usd'])}</td>
          <td class="{u_class}">{fmt_pct(r['unreal_pct'])}</td>
        </tr>"""

    # Closed trades rows
    closed_html = ""
    for r in closed_rows:
        p_class = "positive" if r["pnl_usd"] >= 0 else "negative"
        reason_badge = f'<span class="badge-stop">stop loss</span>' if r["exit_reason"] == "stop_loss" else f'<span class="badge-signal">signal</span>'
        closed_html += f"""
        <tr>
          <td><span class="ticker-badge">{r['ticker']}</span></td>
          <td>{r['strategy']}</td>
          <td>{r['entry_date']}</td>
          <td>{r['exit_date']}</td>
          <td>${r['entry_price']:,.2f}</td>
          <td>${r['exit_price']:,.2f}</td>
          <td>{r['qty']}</td>
          <td class="{p_class}">{fmt_usd(r['pnl_usd'])}</td>
          <td class="{p_class}">{fmt_pct(r['pnl_pct'])}</td>
          <td>{reason_badge}</td>
        </tr>"""

    if not closed_html:
        closed_html = '<tr><td colspan="10" class="empty-state">No closed trades yet — check back once positions start exiting.</td></tr>'

    pf_display = f"{stats['profit_factor']}" if stats['profit_factor'] != float('inf') else "∞"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Alpha Scanner — Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg:       #0d0f1a;
      --card:     #161929;
      --border:   #252840;
      --accent:   #6c63ff;
      --green:    #00d4aa;
      --red:      #ff4d6d;
      --yellow:   #ffd166;
      --text:     #e2e8f0;
      --muted:    #8892a4;
      --radius:   12px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; }}
    a {{ color: var(--accent); }}

    /* Layout */
    .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }}
    header h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
    header h1 span {{ color: var(--accent); }}
    .updated {{ color: var(--muted); font-size: 12px; }}

    /* Stat cards */
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }}
    .stat-card .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }}
    .stat-card .value {{ font-size: 26px; font-weight: 700; line-height: 1; }}
    .stat-card .sub {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    .positive {{ color: var(--green) !important; }}
    .negative {{ color: var(--red) !important; }}
    .neutral  {{ color: var(--yellow) !important; }}

    /* Charts */
    .charts-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 28px; }}
    .chart-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; }}
    .chart-card h2 {{ font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 20px; }}
    .chart-wrap {{ position: relative; height: 220px; }}
    .charts-row {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 28px; }}

    /* Tables */
    .table-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 28px; overflow-x: auto; }}
    .table-card h2 {{ font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
    td {{ padding: 10px 12px; border-bottom: 1px solid rgba(37,40,64,0.6); font-size: 13px; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(108,99,255,0.04); }}
    .ticker-badge {{ background: rgba(108,99,255,0.15); color: var(--accent); padding: 2px 8px; border-radius: 6px; font-weight: 600; font-size: 12px; }}
    .badge-stop {{ background: rgba(255,77,109,0.15); color: var(--red); padding: 2px 8px; border-radius: 6px; font-size: 11px; }}
    .badge-signal {{ background: rgba(0,212,170,0.15); color: var(--green); padding: 2px 8px; border-radius: 6px; font-size: 11px; }}
    .empty-state {{ color: var(--muted); text-align: center; padding: 40px !important; font-style: italic; }}

    /* Section divider */
    .section-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 16px; padding-left: 4px; }}

    /* Footer */
    footer {{ color: var(--muted); font-size: 11px; text-align: center; padding: 20px 0; border-top: 1px solid var(--border); margin-top: 8px; }}

    @media (max-width: 900px) {{
      .charts-grid, .charts-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <header>
    <div>
      <h1>Alpha <span>Scanner</span></h1>
      <div class="updated">Systematic Swing Trading · Paper Portfolio</div>
    </div>
    <div class="updated">Last updated: {generated_at}</div>
  </header>

  <!-- Stat cards -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="label">Total P&amp;L</div>
      <div class="value {pnl_class}">{fmt_usd(stats['total_pnl'])}</div>
      <div class="sub">Closed trades only</div>
    </div>
    <div class="stat-card">
      <div class="label">Win Rate</div>
      <div class="value {'positive' if stats['win_rate'] >= 50 else 'negative'}">{stats['win_rate']}%</div>
      <div class="sub">Target ≥ 50%</div>
    </div>
    <div class="stat-card">
      <div class="label">Profit Factor</div>
      <div class="value {'positive' if stats['profit_factor'] >= 1.3 else 'negative'}">{pf_display}</div>
      <div class="sub">Target ≥ 1.3</div>
    </div>
    <div class="stat-card">
      <div class="label">Avg Win</div>
      <div class="value positive">{fmt_usd(stats['avg_win'])}</div>
      <div class="sub">Per closed trade</div>
    </div>
    <div class="stat-card">
      <div class="label">Avg Loss</div>
      <div class="value negative">{fmt_usd(stats['avg_loss'])}</div>
      <div class="sub">Per closed trade</div>
    </div>
    <div class="stat-card">
      <div class="label">Open Positions</div>
      <div class="value neutral">{stats['open_trades']}</div>
      <div class="sub">Max 10 allowed</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Trades</div>
      <div class="value">{stats['total_trades']}</div>
      <div class="sub">{stats['closed_trades']} closed · {stats['open_trades']} open</div>
    </div>
    <div class="stat-card">
      <div class="label">Exit Breakdown</div>
      <div class="value">{stats['signal_exits']} / {stats['stop_losses']}</div>
      <div class="sub">Signal exits / Stop losses</div>
    </div>
  </div>

  <!-- Charts row 1: equity + win/loss donut -->
  <div class="charts-grid">
    <div class="chart-card">
      <h2>Equity Curve — Cumulative P&amp;L</h2>
      <div class="chart-wrap"><canvas id="equityChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>Win / Loss Split</h2>
      <div class="chart-wrap"><canvas id="donutChart"></canvas></div>
    </div>
  </div>

  <!-- Charts row 2: per-trade bars + strategy breakdown -->
  <div class="charts-row">
    <div class="chart-card" style="grid-column: span 2">
      <h2>P&amp;L Per Trade</h2>
      <div class="chart-wrap"><canvas id="tradeChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>By Strategy</h2>
      <div class="chart-wrap"><canvas id="stratChart"></canvas></div>
    </div>
  </div>

  <!-- Open positions -->
  <div class="section-label">Open Positions ({stats['open_trades']})</div>
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Strategy</th><th>Entry Date</th>
          <th>Entry $</th><th>Qty</th><th>Current $</th>
          <th>Unrealized $</th><th>Unrealized %</th>
        </tr>
      </thead>
      <tbody>{open_html if open_html else '<tr><td colspan="8" class="empty-state">No open positions.</td></tr>'}</tbody>
    </table>
  </div>

  <!-- Closed trades -->
  <div class="section-label">Closed Trades ({stats['closed_trades']})</div>
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Strategy</th><th>Entry</th><th>Exit</th>
          <th>Entry $</th><th>Exit $</th><th>Qty</th>
          <th>P&amp;L $</th><th>P&amp;L %</th><th>Exit</th>
        </tr>
      </thead>
      <tbody>{closed_html}</tbody>
    </table>
  </div>

  <footer>Alpha Scanner · Paper trading since April 2026 · Built on Anthropic Claude</footer>
</div>

<script>
const ACCENT  = '#6c63ff';
const GREEN   = '#00d4aa';
const RED     = '#ff4d6d';
const MUTED   = '#8892a4';
const GRID    = 'rgba(37,40,64,0.8)';
const TEXT    = '#e2e8f0';

Chart.defaults.color = MUTED;
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

// ── Equity curve ──────────────────────────────────────────────────────────────
const equityData = {json.dumps(equity)};
new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{
    labels: equityData.map(d => d.date),
    datasets: [{{
      label: 'Cumulative P&L',
      data: equityData.map(d => d.pnl),
      borderColor: equityData.length && equityData[equityData.length-1].pnl >= 0 ? GREEN : RED,
      backgroundColor: equityData.length && equityData[equityData.length-1].pnl >= 0
        ? 'rgba(0,212,170,0.08)' : 'rgba(255,77,109,0.08)',
      borderWidth: 2.5,
      pointRadius: 4,
      pointBackgroundColor: equityData.length && equityData[equityData.length-1].pnl >= 0 ? GREEN : RED,
      fill: true,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
      label: ctx => ' $' + ctx.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}})
    }} }} }},
    scales: {{
      x: {{ grid: {{ color: GRID }}, ticks: {{ maxTicksLimit: 8 }} }},
      y: {{ grid: {{ color: GRID }}, ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
    }}
  }}
}});

// ── Win/Loss donut ────────────────────────────────────────────────────────────
const winRate   = {stats['win_rate']};
const lossRate  = Math.max(0, 100 - winRate);
new Chart(document.getElementById('donutChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Wins', 'Losses'],
    datasets: [{{ data: [winRate, lossRate], backgroundColor: [GREEN, RED],
      borderColor: '#161929', borderWidth: 3, hoverOffset: 6 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    cutout: '68%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ padding: 16, usePointStyle: true }} }},
      tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.label + ': ' + ctx.parsed.toFixed(1) + '%' }} }}
    }}
  }}
}});

// ── Per-trade bars ─────────────────────────────────────────────────────────────
const barData = {json.dumps(bars)};
new Chart(document.getElementById('tradeChart'), {{
  type: 'bar',
  data: {{
    labels: barData.map(d => d.label),
    datasets: [{{
      label: 'P&L',
      data: barData.map(d => d.pnl),
      backgroundColor: barData.map(d => d.win ? 'rgba(0,212,170,0.7)' : 'rgba(255,77,109,0.7)'),
      borderColor:     barData.map(d => d.win ? GREEN : RED),
      borderWidth: 1, borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
      label: ctx => ' $' + ctx.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}})
    }} }} }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
      y: {{ grid: {{ color: GRID }}, ticks: {{ callback: v => '$' + v }} }}
    }}
  }}
}});

// ── Strategy breakdown ────────────────────────────────────────────────────────
const stratData = {json.dumps(strat)};
new Chart(document.getElementById('stratChart'), {{
  type: 'bar',
  data: {{
    labels: stratData.map(d => d.strategy),
    datasets: [{{
      label: 'Total P&L',
      data: stratData.map(d => d.pnl),
      backgroundColor: stratData.map(d => d.pnl >= 0 ? 'rgba(0,212,170,0.7)' : 'rgba(255,77,109,0.7)'),
      borderColor:     stratData.map(d => d.pnl >= 0 ? GREEN : RED),
      borderWidth: 1, borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
      label: ctx => ' $' + ctx.parsed.x.toLocaleString('en-US', {{minimumFractionDigits:2}})
    }} }} }},
    scales: {{
      x: {{ grid: {{ color: GRID }}, ticks: {{ callback: v => '$' + v }} }},
      y: {{ grid: {{ display: false }} }}
    }}
  }}
}});
</script>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def generate() -> None:
    df = load_trades()
    stats       = build_stats(df)
    equity      = build_equity_curve(df)
    bars        = build_trade_bars(df)
    strat       = build_strategy_breakdown(df)
    closed_rows = build_closed_table(df)
    open_rows   = enrich_open_positions(df) if not df.empty else []
    generated   = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = render_html(stats, equity, bars, strat, closed_rows, open_rows, generated)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"  Dashboard updated → {OUTPUT}")


if __name__ == "__main__":
    generate()
