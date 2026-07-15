"""Public dashboard builder -> public/index.html for strategygrade.io.

A REDACTED, self-contained page. It shows only ratio/percentage metrics
(win rate, profit factor, average win/loss %, expectancy, a normalized
trajectory) and deliberately omits EVERY absolute dollar figure - account
equity, dollar P&L, position size, share count - so publishing it never
reveals account size. Stock prices are public information; the redaction is
purely about account/position magnitude.

Self-contained (inline CSS + inline SVG chart, no external assets), so it drops
straight onto any static host. Run after the daily tracker:

  python3 publish.py            # writes public/index.html
"""
from datetime import datetime
from pathlib import Path

import pandas as pd

from dashboard import load_trades, build_closed_table, enrich_open_positions

OUT = Path("public/index.html")
SITE = "strategygrade.io"


def public_stats(df: pd.DataFrame) -> dict | None:
    closed = df[df["status"] == "CLOSED"].copy()
    closed["pnl_pct"] = pd.to_numeric(closed.get("pnl_pct"), errors="coerce")
    closed = closed.dropna(subset=["pnl_pct"]).sort_values("exit_date")
    if closed.empty:
        return None
    wins = closed[closed["pnl_pct"] > 0]
    losses = closed[closed["pnl_pct"] <= 0]
    gross_win = float(wins["pnl_pct"].sum())
    gross_loss = abs(float(losses["pnl_pct"].sum()))
    cum = closed["pnl_pct"].cumsum().round(2).tolist()
    return {
        "n": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_win": round(float(wins["pnl_pct"].mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses["pnl_pct"].mean()), 2) if len(losses) else 0.0,
        "expectancy": round(float(closed["pnl_pct"].mean()), 2),
        "curve": cum,
        "dates": closed["exit_date"].astype(str).tolist(),
    }


def svg_curve(curve: list[float], w: int = 720, h: int = 220, pad: int = 12) -> str:
    """Inline SVG line of the cumulative per-trade % trajectory (no dollars)."""
    if len(curve) < 2:
        return '<p class="muted">Not enough closed trades yet to chart.</p>'
    lo, hi = min(curve + [0.0]), max(curve + [0.0])
    rng = (hi - lo) or 1.0
    n = len(curve)
    pts = []
    for i, v in enumerate(curve):
        x = pad + (w - 2 * pad) * i / (n - 1)
        y = pad + (h - 2 * pad) * (1 - (v - lo) / rng)
        pts.append(f"{x:.1f},{y:.1f}")
    zero_y = pad + (h - 2 * pad) * (1 - (0 - lo) / rng)
    last = curve[-1]
    color = "#3fb950" if last >= 0 else "#f85149"
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none" role="img" '
        f'aria-label="cumulative return trajectory">'
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-pad}" y2="{zero_y:.1f}" '
        f'stroke="#30363d" stroke-dasharray="4 4"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{" ".join(pts)}"/>'
        f'</svg>'
    )


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:+.2f}%"


def render(stats: dict | None, open_rows: list[dict], closed_rows: list[dict]) -> str:
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not stats:
        cards = '<p class="muted">No closed trades yet.</p>'
        chart = ""
    else:
        pf = "∞" if stats["profit_factor"] == float("inf") else f'{stats["profit_factor"]:.2f}'
        cards = "".join(
            f'<div class="card"><div class="k">{k}</div><div class="v {cls}">{v}</div></div>'
            for k, v, cls in [
                ("Win rate", f'{stats["win_rate"]:.1f}%', ""),
                ("Profit factor", pf, ""),
                ("Avg win", fmt_pct(stats["avg_win"]), "pos"),
                ("Avg loss", fmt_pct(stats["avg_loss"]), "neg"),
                ("Expectancy / trade", fmt_pct(stats["expectancy"]),
                 "pos" if stats["expectancy"] >= 0 else "neg"),
                ("Closed trades", str(stats["n"]), ""),
            ]
        )
        chart = f'<section class="panel"><h2>Cumulative return trajectory</h2>{svg_curve(stats["curve"])}' \
                '<p class="muted">Sum of per-trade percentage returns over time. Shape, not scale.</p></section>'

    open_html = "".join(
        f'<tr><td>{r["ticker"]}</td><td>{r["strategy"]}</td><td>{r["entry_date"]}</td>'
        f'<td class="{"pos" if (r.get("unreal_pct") or 0) >= 0 else "neg"}">{fmt_pct(r.get("unreal_pct"))}</td></tr>'
        for r in open_rows
    ) or '<tr><td colspan="4" class="muted">No open positions.</td></tr>'

    closed_sorted = sorted(closed_rows, key=lambda r: str(r.get("exit_date", "")), reverse=True)[:25]
    closed_html = "".join(
        f'<tr><td>{r["ticker"]}</td><td>{r["strategy"]}</td><td>{r.get("exit_date","")}</td>'
        f'<td class="{"pos" if (r.get("pnl_pct") or 0) >= 0 else "neg"}">{fmt_pct(r.get("pnl_pct"))}</td>'
        f'<td class="muted">{r.get("exit_reason","")}</td></tr>'
        for r in closed_sorted
    ) or '<tr><td colspan="5" class="muted">No closed trades yet.</td></tr>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Grade — systematic swing trading</title>
<meta name="description" content="Live, survivorship-bias-free results of a systematic swing-trading system. Percentage metrics only.">
<style>
  :root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--txt:#e6edf3;--muted:#8b949e;--pos:#3fb950;--neg:#f85149;--accent:#58a6ff}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--txt);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
  .wrap{{max-width:860px;margin:0 auto;padding:32px 20px 64px}}
  header h1{{margin:0;font-size:26px;letter-spacing:-.5px}}
  header p{{margin:6px 0 0;color:var(--muted)}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:28px 0}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}
  .card .k{{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.4px}}
  .card .v{{font-size:26px;font-weight:600;margin-top:6px}}
  .panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin:22px 0}}
  .panel h2{{margin:0 0 14px;font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}
  th{{color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase}}
  .pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .muted{{color:var(--muted)}}
  footer{{margin-top:36px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:18px}}
  .tag{{display:inline-block;background:#1f6feb22;color:var(--accent);border:1px solid #1f6feb44;border-radius:20px;padding:2px 10px;font-size:12px;margin-top:10px}}
</style></head><body><div class="wrap">
<header>
  <h1>Strategy&nbsp;Grade</h1>
  <p>Systematic swing trading · survivorship-bias-free validation on 25 years of CRSP data.</p>
  <span class="tag">Percentage metrics only — account size not disclosed</span>
</header>
<div class="grid">{cards}</div>
{chart}
<section class="panel"><h2>Open positions</h2>
  <table><tr><th>Ticker</th><th>Strategy</th><th>Entered</th><th>Unrealized</th></tr>{open_html}</table>
</section>
<section class="panel"><h2>Recent closed trades</h2>
  <table><tr><th>Ticker</th><th>Strategy</th><th>Exited</th><th>Return</th><th>Reason</th></tr>{closed_html}</table>
</section>
<footer>
  Paper-traded results, updated {updated}. Percentage returns only; dollar amounts, position sizes,
  and account equity are intentionally omitted. This is not investment advice and not an offer of any service.
  · {SITE}
</footer>
</div></body></html>"""


def main() -> None:
    df = load_trades()
    stats = public_stats(df)
    open_rows = enrich_open_positions(df)
    closed_rows = build_closed_table(df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".html.tmp")
    tmp.write_text(render(stats, open_rows, closed_rows), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Public page written -> {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
