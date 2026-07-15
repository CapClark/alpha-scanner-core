"""Public dashboard builder -> public/index.html for strategygrade.io.

A REDACTED, self-contained page styled as a quantitative trading terminal. It
shows ratio/percentage metrics (win rate, profit factor, average win/loss %,
expectancy, a normalized trajectory) plus entry/exit PRICES (public market data),
and deliberately omits every position-magnitude figure — share count, dollar P&L,
cost basis, account equity — so publishing it never reveals account size.

Self-contained apart from a Google Fonts link; inline CSS + an inline JS chart,
no build step. Run after the daily tracker:

  python3 publish.py            # writes public/index.html
"""
import json
import math
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from dashboard import load_trades, build_closed_table, enrich_open_positions

OUT = Path("public/index.html")
SITE = "strategygrade.io"
REPO_URL = "https://github.com/CapClark/alpha-scanner-core"

# Manual footnotes on individual closed trades, keyed by (ticker, exit_date).
# For outliers the raw log can't explain on its own — e.g. a machine failure.
TRADE_NOTES = {
    ("INTU", "2026-06-26"):
        "Machine failure, not strategy. The protective stop had expired (the June 2026 "
        "stop-expiry bug, since fixed), so the position was never cut — it ran to the "
        "indicator exit at -13% instead of stopping out near -5%. Had the stop fired as "
        "designed, this loss would have been roughly a third as large.",
}

# Counterfactual: what a trade's return WOULD have been absent a known machine
# failure. Keyed (ticker, exit_date) -> intended pnl_pct. Drives ONLY the clearly
# labeled scenario module — the realized numbers are never overwritten.
TRADE_COUNTERFACTUAL = {
    ("INTU", "2026-06-26"): -5.00,   # intended disaster stop at entry-5%, vs -13.09% realized naked
}


def apply_counterfactual(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the trade log with known machine-failure losses replaced by
    the return the position was designed to take. Used for the scenario module only."""
    d = df.copy()
    for (tk, ed), pnl in TRADE_COUNTERFACTUAL.items():
        m = (d["ticker"] == tk) & (d["exit_date"].astype(str) == ed) & (d["status"] == "CLOSED")
        d.loc[m, "pnl_pct"] = pnl
    return d


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
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_win": round(float(wins["pnl_pct"].mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses["pnl_pct"].mean()), 2) if len(losses) else 0.0,
        "expectancy": round(float(closed["pnl_pct"].mean()), 2),
        "curve": cum,
        "dates": closed["exit_date"].astype(str).tolist(),
    }


# ── small computed helpers ───────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion, as percentages. Honest small-n bound."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, center - half) * 100, 1), round(min(1.0, center + half) * 100, 1))


def max_drawdown(curve: list[float]) -> dict:
    """Max drawdown of the cumulative per-trade curve, in percentage points."""
    if len(curve) < 2:
        return {"val": 0.0, "idx": 0}
    peak, worst, worst_i = curve[0], 0.0, 0
    for i, v in enumerate(curve):
        peak = max(peak, v)
        dd = v - peak
        if dd < worst:
            worst, worst_i = dd, i
    return {"val": round(worst, 2), "idx": worst_i}


def hold_days(entry: str, exit_: str) -> str:
    try:
        d0 = date.fromisoformat(str(entry)[:10])
        d1 = date.fromisoformat(str(exit_)[:10])
        return f"{(d1 - d0).days}d"
    except Exception:
        return "—"


def trade_meta(df: pd.DataFrame) -> list[dict]:
    """Per-closed-trade metadata aligned to public_stats()['curve'] (exit-date order)."""
    closed = df[df["status"] == "CLOSED"].copy()
    closed["pnl_pct"] = pd.to_numeric(closed.get("pnl_pct"), errors="coerce")
    closed = closed.dropna(subset=["pnl_pct"]).sort_values("exit_date")
    out = []
    for i, (_, r) in enumerate(closed.iterrows(), 1):
        out.append({
            "n": i, "ticker": r["ticker"], "date": str(r["exit_date"])[:10],
            "ret": round(float(r["pnl_pct"]), 2), "reason": r.get("exit_reason", ""),
        })
    return out


def benchmark_curve(first_entry, dates: list[str]) -> list[float] | None:
    """SPY buy-and-hold % return from the first entry date, sampled at each exit date.
    A fair 'what the market did over the same span' overlay. Returns None if offline."""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period="3y", auto_adjust=True)["Close"].dropna()
        spy.index = spy.index.tz_localize(None)
        base_ts = pd.Timestamp(str(first_entry)[:10])
        base_slice = spy[spy.index <= base_ts]
        base = float(base_slice.iloc[-1]) if not base_slice.empty else float(spy.iloc[0])
        out = []
        for d in dates:
            sub = spy[spy.index <= pd.Timestamp(str(d)[:10])]
            if sub.empty:
                return None
            out.append(round((float(sub.iloc[-1]) / base - 1) * 100, 2))
        return out
    except Exception:
        return None


# ── formatting ───────────────────────────────────────────────────────────────

def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:+.2f}%"


def fmt_pp(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:+.2f} pp"


def fmt_px(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "—"


def cls_sign(v) -> str:
    try:
        return "pos" if float(v) >= 0 else "neg"
    except Exception:
        return "mut"


# ── style / script (plain strings — no f-string brace escaping) ───────────────

STYLE = """
:root{
  --bg:#090C10; --p1:#0E1319; --p2:#111820; --elev:#151C24;
  --bd:rgba(145,158,171,.16); --bd2:rgba(145,158,171,.28);
  --tx:#E7ECF2; --tx2:#8995A3; --mut:#5F6B78;
  --pos:#52D273; --neg:#FF625F; --negm:rgba(255,98,95,.5);
  --acc:#579DFF; --amb:#E8AD55;
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --sans:"Inter",-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  position:relative; min-height:100vh;
  background:var(--bg);
  color:var(--tx); font-family:var(--sans); font-size:14px; line-height:1.5;
  -webkit-font-smoothing:antialiased; letter-spacing:.1px;
}
/* Top vignette only — a cheap gradient painted once into a non-fixed layer. No SVG
   filter layer (feTurbulence over a full-page surface stalls the compositor). */
body::before{
  content:""; position:absolute; top:0; left:0; right:0; height:820px; pointer-events:none; z-index:0;
  background:radial-gradient(ellipse 120% 100% at 50% -12%,#11171f 0%,rgba(9,12,16,0) 68%);
}
.mono{font-family:var(--mono);font-feature-settings:"tnum" 1,"zero" 1;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)} .neg{color:var(--neg)} .mut{color:var(--mut)} .amb{color:var(--amb)} .acc{color:var(--acc)}
.wrap{position:relative; z-index:1; max-width:1240px; margin:0 auto; padding:0 22px 80px}

/* header */
header{display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding:18px 0 16px; border-bottom:1px solid var(--bd); position:sticky; top:0;
  background:linear-gradient(180deg,var(--bg) 70%,rgba(9,12,16,.86)); backdrop-filter:blur(6px); z-index:5}
.brand{display:flex; flex-direction:column; gap:4px}
.brand .name{font-size:15px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  display:flex; align-items:center; gap:9px}
.brand .sub{font-family:var(--mono); font-size:11px; color:var(--tx2); letter-spacing:.05em}
.dot{width:7px; height:7px; border-radius:50%; background:var(--pos); box-shadow:0 0 0 0 rgba(82,210,115,.5); animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(82,210,115,.45)}70%{box-shadow:0 0 0 6px rgba(82,210,115,0)}100%{box-shadow:0 0 0 0 rgba(82,210,115,0)}}
.hactions{display:flex; align-items:center; gap:12px}
.stamp{font-family:var(--mono); font-size:11px; color:var(--mut); text-align:right; line-height:1.35}
.badge{font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; text-transform:uppercase;
  padding:3px 9px; border-radius:20px; border:1px solid var(--bd2); color:var(--amb)}
.iconbtn{font-family:var(--mono); font-size:11px; letter-spacing:.1em; text-transform:uppercase;
  background:var(--p2); border:1px solid var(--bd2); color:var(--tx2); padding:6px 11px; border-radius:6px;
  cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; line-height:1}
.iconbtn:hover{color:var(--tx); border-color:var(--bd2); background:var(--elev)}

/* instrument strip */
.strip{display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--bd); border-radius:8px;
  background:linear-gradient(180deg,var(--p2),var(--p1)); margin:16px 0 26px; overflow:hidden}
.strip .cell{flex:1 1 auto; min-width:130px; padding:11px 16px; border-right:1px solid var(--bd)}
.strip .cell:last-child{border-right:0}
.strip .k{font-size:9.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--mut)}
.strip .v{font-family:var(--mono); font-size:13.5px; margin-top:4px; color:var(--tx); display:flex; align-items:center; gap:7px}

/* section scaffolding */
.sec{margin:30px 0 0}
.sechd{display:flex; align-items:baseline; gap:12px; margin:0 0 14px}
.sechd .idx{font-family:var(--mono); font-size:11px; color:var(--acc); letter-spacing:.1em}
.sechd h2{margin:0; font-size:12px; font-weight:600; letter-spacing:.18em; text-transform:uppercase; color:var(--tx2)}
.sechd .rule{flex:1; height:1px; background:var(--bd)}
.sechd .hint{font-family:var(--mono); font-size:10.5px; color:var(--mut)}
kbd{font-family:var(--mono); font-size:10px; background:var(--elev); border:1px solid var(--bd2);
  border-bottom-width:2px; border-radius:4px; padding:1px 5px; color:var(--tx2)}

/* metrics panel */
.metrics{display:flex; border:1px solid var(--bd); border-radius:8px; background:var(--p1); overflow:hidden}
.metrics .m{flex:1; padding:16px 18px; border-right:1px solid var(--bd); min-width:0}
.metrics .m:last-child{border-right:0}
.metrics .m.lead{flex:1.35; background:linear-gradient(180deg,var(--p2),var(--p1))}
.m .lab{font-size:9.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--mut)}
.m .val{font-family:var(--mono); font-size:26px; font-weight:500; margin-top:8px; letter-spacing:-.5px}
.m.lead .val{font-size:32px}
.m .ctx{font-family:var(--mono); font-size:10.5px; color:var(--mut); margin-top:6px}
.spark{margin-top:9px; height:3px; border-radius:2px; background:var(--elev); overflow:hidden}
.spark > i{display:block; height:100%}
.warnpill{display:inline-flex; align-items:center; gap:6px; font-family:var(--mono); font-size:10px;
  letter-spacing:.08em; color:var(--amb); border:1px solid rgba(232,173,85,.4); background:rgba(232,173,85,.07);
  border-radius:5px; padding:2px 7px; margin-top:8px}

/* chart + rail */
.chartgrid{display:grid; grid-template-columns:minmax(0,7fr) minmax(230px,3fr); gap:18px}
.panel{border:1px solid var(--bd); border-radius:8px; background:var(--p1)}
.chartcard{padding:16px 16px 12px; position:relative}
.chart-top{display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:6px}
.seg{display:inline-flex; border:1px solid var(--bd2); border-radius:6px; overflow:hidden}
.seg button{font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
  background:transparent; color:var(--tx2); border:0; border-right:1px solid var(--bd); padding:6px 11px; cursor:pointer}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--elev); color:var(--tx)}
.seg button:disabled{color:var(--mut); cursor:not-allowed}
.chartwrap{position:relative; width:100%}
#chart{display:block; width:100%; height:auto}
.tip{position:absolute; pointer-events:none; z-index:4; background:var(--elev); border:1px solid var(--bd2);
  border-radius:6px; padding:8px 10px; font-family:var(--mono); font-size:11px; color:var(--tx);
  opacity:0; transition:opacity .08s; min-width:120px; box-shadow:0 8px 26px rgba(0,0,0,.5)}
.tip .tk{color:var(--tx2); font-size:10px; letter-spacing:.05em}
.chart-foot{display:flex; flex-wrap:wrap; gap:6px 16px; margin-top:8px; padding-top:9px; border-top:1px solid var(--bd);
  font-family:var(--mono); font-size:10.5px; color:var(--mut)}

.rail{display:flex; flex-direction:column; gap:14px}
.rcard{border:1px solid var(--bd); border-radius:8px; background:var(--p1); padding:14px 15px}
.rcard h3{margin:0 0 11px; font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--mut)}
.rbig{font-family:var(--mono); font-size:28px; line-height:1; margin-bottom:2px}
.rrow{display:flex; justify-content:space-between; gap:10px; padding:5px 0; border-top:1px solid var(--bd)}
.rrow:first-of-type{border-top:0}
.rrow .k{font-size:11px; color:var(--tx2)}
.rrow .v{font-family:var(--mono); font-size:12px; color:var(--tx)}

/* scenario */
.scenario{border:1px solid var(--bd); border-left:2px solid var(--amb); border-radius:8px;
  background:linear-gradient(180deg,rgba(232,173,85,.045),rgba(232,173,85,0) 40%),var(--p2); padding:18px 20px}
.schd{display:flex; align-items:center; gap:12px; margin-bottom:14px}
.schd h2{margin:0; font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:var(--tx2)}
.scbadge{font-family:var(--mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--amb); border:1px solid rgba(232,173,85,.45); border-radius:20px; padding:2px 9px}
.sccols{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.15fr); gap:22px}
.scfacts .frow{display:flex; gap:12px; padding:7px 0; border-top:1px solid var(--bd)}
.scfacts .frow:first-child{border-top:0}
.scfacts .fk{font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--mut); width:120px; flex:0 0 120px; padding-top:2px}
.scfacts .fv{font-size:12.5px; color:var(--tx2)}
table.cmp{width:100%; border-collapse:collapse; font-family:var(--mono)}
table.cmp th,table.cmp td{padding:7px 8px; border-bottom:1px solid var(--bd); font-size:12px; text-align:right}
table.cmp th{font-size:9.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--mut); font-weight:500}
table.cmp td:first-child,table.cmp th:first-child{text-align:left; color:var(--tx2)}
table.cmp .adj{color:var(--acc)}

/* ledger */
.ledwrap{border:1px solid var(--bd); border-radius:8px; overflow:hidden}
.ledscroll{overflow-x:auto}
table.led{width:100%; border-collapse:collapse; min-width:760px}
table.led thead th{position:sticky; top:0; background:var(--p2); z-index:2; font-size:9.5px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--mut); font-weight:500; text-align:right; padding:10px 12px; border-bottom:1px solid var(--bd2)}
table.led thead th:nth-child(-n+4){text-align:left}
table.led td{font-family:var(--mono); font-size:12px; padding:8px 12px; border-bottom:1px solid var(--bd); text-align:right; white-space:nowrap}
table.led td:nth-child(-n+4){text-align:left}
table.led tbody tr{cursor:pointer}
table.led tbody tr:nth-child(even){background:rgba(145,158,171,.028)}
table.led tbody tr:hover{background:rgba(87,157,255,.07)}
.tkbadge{font-family:var(--mono); font-size:11px; color:var(--tx); border:1px solid var(--bd2); border-radius:4px; padding:1px 6px}
.side{font-size:10px; letter-spacing:.06em; color:var(--tx2)}
.stat{font-family:var(--mono); font-size:9.5px; letter-spacing:.08em; text-transform:uppercase; padding:2px 7px; border-radius:20px; border:1px solid var(--bd2)}
.stat.open{color:var(--acc); border-color:rgba(87,157,255,.4)}
.stat.closed{color:var(--tx2)}
.reason{color:var(--mut); font-size:11px}
.fmk{color:var(--amb)}

/* drawer */
.scrim{position:fixed; inset:0; background:rgba(4,6,9,.55); opacity:0; pointer-events:none; transition:opacity .18s; z-index:20}
.scrim.on{opacity:1; pointer-events:auto}
.drawer{position:fixed; top:0; right:0; height:100%; width:min(420px,92vw); background:var(--p1);
  border-left:1px solid var(--bd2); transform:translateX(100%); transition:transform .22s cubic-bezier(.2,.7,.2,1);
  z-index:21; padding:22px 22px 28px; overflow-y:auto}
.drawer.on{transform:translateX(0)}
.drawer .dhd{display:flex; align-items:center; justify-content:space-between; margin-bottom:18px}
.drawer .dtk{font-family:var(--mono); font-size:20px; letter-spacing:.02em}
.drawer .close{background:var(--elev); border:1px solid var(--bd2); color:var(--tx2); border-radius:6px; cursor:pointer; padding:5px 9px; font-family:var(--mono); font-size:11px}
.drawer .drow{display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-top:1px solid var(--bd)}
.drawer .drow .k{font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--mut)}
.drawer .drow .v{font-family:var(--mono); font-size:13px}
.drawer .dnote{margin-top:16px; padding:12px 13px; border:1px solid rgba(232,173,85,.35); background:rgba(232,173,85,.06);
  border-radius:6px; font-size:12px; line-height:1.55; color:var(--tx2)}
.drawer .dnote b{color:var(--amb); font-weight:600}

footer{margin-top:34px; padding-top:16px; border-top:1px solid var(--bd); color:var(--mut);
  font-family:var(--mono); font-size:10.5px; line-height:1.7; display:flex; flex-wrap:wrap; gap:4px 18px}
footer span{flex:1 1 240px; min-width:0}

@media(max-width:860px){
  .chartgrid{grid-template-columns:1fr}
  .metrics{overflow-x:auto} .metrics .m{min-width:130px}
  .strip{flex-wrap:nowrap; overflow-x:auto} .strip .cell{min-width:150px}
  .sccols{grid-template-columns:1fr}
  header{flex-direction:column; align-items:flex-start; gap:10px; position:static}
}
"""

CHART_JS = """
(function(){
  var D = window.__SG;
  if(!D || !D.realized || D.realized.length<2){ return; }
  var svg=document.getElementById('chart'), NS='http://www.w3.org/2000/svg';
  var W=1000,H=360,pl=52,pr=70,pt=20,pb=30;
  var wrap=document.getElementById('chartwrap'), tip=document.getElementById('tip');
  var state={series:'realized'};
  function el(t,a){var e=document.createElementNS(NS,t);for(var k in a)e.setAttribute(k,a[k]);return e;}
  function fmt(v){return (v>=0?'+':'')+v.toFixed(2)+'%';}
  function activeArr(){ if(state.series==='hypo')return D.hypo; if(state.series==='benchmark')return D.benchmark; return D.realized; }
  var X=[],Ymin,Ymax;
  function draw(){
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    var A=activeArr(); if(!A){A=D.realized; state.series='realized';}
    var n=D.realized.length;
    var all=A.concat(D.realized,[0]);
    var lo=Math.min.apply(null,all), hi=Math.max.apply(null,all);
    var pad=(hi-lo)*0.12||1; lo-=pad; hi+=pad; Ymin=lo; Ymax=hi;
    var xw=W-pl-pr, yh=H-pt-pb;
    function x(i){return pl + xw*(n<2?0:i/(n-1));}
    function y(v){return pt + yh*(1-(v-lo)/(hi-lo));}
    X=[]; for(var i=0;i<n;i++)X.push(x(i));
    // gridlines: lo, 0, hi
    var ticks=[]; [hi,0,lo].forEach(function(t){ if(t>=lo&&t<=hi)ticks.push(t); });
    ticks.forEach(function(t){
      var yy=y(t), zero=Math.abs(t)<1e-9;
      svg.appendChild(el('line',{x1:pl,y1:yy,x2:W-pr,y2:yy,stroke:zero?'rgba(145,158,171,.34)':'rgba(145,158,171,.1)','stroke-dasharray':zero?'':'2 4'}));
      var lb=el('text',{x:pl-8,y:yy+3,'text-anchor':'end',fill:'#5F6B78','font-size':'11','font-family':'var(--mono)'});
      lb.textContent=(t>=0?'+':'')+t.toFixed(1)+'%'; svg.appendChild(lb);
    });
    // ghost realized when viewing another series
    if(state.series!=='realized'){
      var gp=D.realized.map(function(v,i){return X[i]+','+y(v);}).join(' ');
      svg.appendChild(el('polyline',{points:gp,fill:'none',stroke:'rgba(145,158,171,.22)','stroke-width':1.2,'stroke-dasharray':'3 3'}));
    }
    // area fill under active
    var col = state.series==='benchmark' ? '#579DFF' : (A[A.length-1]>=0?'#52D273':'#FF625F');
    var areaPts=A.map(function(v,i){return X[i]+','+y(v);}).join(' ');
    var area=el('polygon',{points:pl+','+y(Math.max(lo,Math.min(hi,0)))+' '+areaPts+' '+(W-pr)+','+y(Math.max(lo,Math.min(hi,0))),fill:col,'fill-opacity':.06,stroke:'none'});
    svg.appendChild(area);
    // main line — drawdown-aware coloring for realized/hypo; solid for benchmark
    if(state.series==='benchmark'){
      svg.appendChild(el('polyline',{points:areaPts,fill:'none',stroke:'#579DFF','stroke-width':1.6}));
    } else {
      var peak=-1e9;
      for(var s=0;s<A.length-1;s++){
        peak=Math.max(peak,A[s]);
        var below=A[s+1]<peak-1e-9;
        svg.appendChild(el('line',{x1:X[s],y1:y(A[s]),x2:X[s+1],y2:y(A[s+1]),stroke:below?'rgba(255,98,95,.5)':'#52D273','stroke-width':1.8,'stroke-linecap':'round'}));
      }
    }
    // markers
    A.forEach(function(v,i){ svg.appendChild(el('circle',{cx:X[i],cy:y(v),r:2.6,fill:'#0E1319',stroke:col,'stroke-width':1.3})); });
    // max drawdown annotation (realized only)
    if(state.series==='realized' && D.dd && D.dd.val<0){
      var di=D.dd.idx;
      svg.appendChild(el('circle',{cx:X[di],cy:y(D.realized[di]),r:3.4,fill:'#FF625F','fill-opacity':.9}));
      var dl=el('text',{x:X[di],y:y(D.realized[di])+18,'text-anchor':'middle',fill:'#FF625F','font-size':'10','font-family':'var(--mono)'});
      dl.textContent='MAX DD '+D.dd.val.toFixed(2)+'pp'; svg.appendChild(dl);
    }
    // latest value annotation, right
    var lv=A[A.length-1];
    svg.appendChild(el('line',{x1:W-pr,y1:y(lv),x2:W-pr+8,y2:y(lv),stroke:col,'stroke-width':1.4}));
    var lt=el('text',{x:W-pr+12,y:y(lv)+3,fill:col,'font-size':'12','font-family':'var(--mono)','font-weight':'600'});
    lt.textContent=(lv>=0?'+':'')+lv.toFixed(2)+'%'; svg.appendChild(lt);
    // crosshair + hover targets
    var cross=el('line',{id:'cross',x1:0,y1:pt,x2:0,y2:H-pb,stroke:'rgba(145,158,171,.4)','stroke-dasharray':'2 3',opacity:0}); svg.appendChild(cross);
    var hov=el('circle',{id:'hov',r:4,fill:col,opacity:0}); svg.appendChild(hov);
    svg._y=y; svg._col=col; svg._A=A;
  }
  function nearest(clientX){
    var r=svg.getBoundingClientRect(), sx=(clientX-r.left)/r.width*W;
    var best=0,bd=1e9; for(var i=0;i<X.length;i++){var d=Math.abs(X[i]-sx); if(d<bd){bd=d;best=i;}} return best;
  }
  svg.addEventListener('mousemove',function(e){
    if(!X.length)return; var i=nearest(e.clientX);
    var cross=document.getElementById('cross'), hov=document.getElementById('hov');
    var yv=svg._y(svg._A[i]);
    cross.setAttribute('x1',X[i]);cross.setAttribute('x2',X[i]);cross.setAttribute('opacity',1);
    hov.setAttribute('cx',X[i]);hov.setAttribute('cy',yv);hov.setAttribute('opacity',1);
    var m=D.meta[i]; var lbl = state.series==='benchmark' ? 'SPY' : (m?m.ticker:'');
    var val=svg._A[i], pertrade = (state.series==='benchmark')? null : (m?m.ret:null);
    var r=svg.getBoundingClientRect();
    tip.innerHTML='<div class="tk">#'+(i+1)+' · '+(m?m.date:'')+'</div>'+
      lbl+' <span class="'+(val>=0?'pos':'neg')+'">'+fmt(val)+'</span>'+
      (pertrade!==null?'<div class="tk">trade '+(pertrade>=0?'+':'')+pertrade.toFixed(2)+'%</div>':'');
    tip.style.opacity=1;
    var px=X[i]/W*r.width, py=yv/H*r.height;
    tip.style.left=Math.min(r.width-tip.offsetWidth-6,Math.max(6,px+12))+'px';
    tip.style.top=Math.max(4,py-10)+'px';
  });
  svg.addEventListener('mouseleave',function(){
    tip.style.opacity=0; var c=document.getElementById('cross'),h=document.getElementById('hov');
    if(c)c.setAttribute('opacity',0); if(h)h.setAttribute('opacity',0);
  });
  function setSeries(s){
    if(s==='benchmark' && !D.benchmark) return;
    state.series=s;
    document.querySelectorAll('.seg button').forEach(function(b){b.classList.toggle('on',b.dataset.s===s);});
    draw();
  }
  document.querySelectorAll('.seg button').forEach(function(b){
    b.addEventListener('click',function(){setSeries(b.dataset.s);});
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='r'||e.key==='R')setSeries('realized');
    if(e.key==='h'||e.key==='H')setSeries('hypo');
    if(e.key==='b'||e.key==='B')setSeries('benchmark');
    if(e.key==='Escape')closeDrawer();
  });
  svg.setAttribute('viewBox','0 0 '+W+' '+H);
  draw();

  // drawer
  var scrim=document.getElementById('scrim'), drawer=document.getElementById('drawer');
  window.closeDrawer=function(){scrim.classList.remove('on');drawer.classList.remove('on');};
  scrim.addEventListener('click',closeDrawer);
  document.getElementById('dclose').addEventListener('click',closeDrawer);
  document.querySelectorAll('tr[data-trade]').forEach(function(tr){
    tr.addEventListener('click',function(){
      var d=JSON.parse(tr.getAttribute('data-trade'));
      document.getElementById('dtk').textContent=d.ticker;
      var rows=[['Strategy',d.strategy],['Side',d.side],['Status',d.status],['Entry date',d.entry_date],
        ['Exit date',d.exit_date||'—'],['Entry',d.entry],['Exit',d.exit],['Return',d.ret],
        ['Holding period',d.hold],['Exit reason',d.reason||'—']];
      document.getElementById('dbody').innerHTML=rows.map(function(r){
        var cls=''; if(r[0]==='Return')cls=(d.retpos?'pos':'neg');
        return '<div class="drow"><span class="k">'+r[0]+'</span><span class="v '+cls+'">'+r[1]+'</span></div>';
      }).join('');
      document.getElementById('dnote').innerHTML = d.note ? ('<b>NOTE</b> '+d.note) : '';
      document.getElementById('dnote').style.display = d.note?'block':'none';
      scrim.classList.add('on'); drawer.classList.add('on');
    });
  });
})();
"""


def render(stats, cf, meta, bench, open_rows, closed_rows) -> str:
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    # health-strip / rail computed values
    dd = max_drawdown(stats["curve"]) if stats else {"val": 0.0, "idx": 0}
    n_open = len(open_rows)
    all_dates = [str(r.get("exit_date", ""))[:10] for r in closed_rows if r.get("exit_date")]
    all_dates += [str(r.get("entry_date", ""))[:10] for r in open_rows]
    last_signal = max(all_dates) if all_dates else "—"
    data_fresh = last_signal
    ci_lo, ci_hi = wilson_ci(stats["wins"], stats["n"]) if stats else (0.0, 0.0)

    # ── metrics panel ──
    if stats:
        pf = "∞" if stats["profit_factor"] == float("inf") else f'{stats["profit_factor"]:.2f}'
        exp_cls = cls_sign(stats["expectancy"])
        pf_cls = "pos" if (stats["profit_factor"] == float("inf") or stats["profit_factor"] >= 1) else "neg"
        cum = stats["curve"][-1]
        wr = stats["win_rate"]
        wr_w = max(0, min(100, wr))
        metrics = f"""
<div class="metrics">
  <div class="m lead"><div class="lab">Expectancy / trade</div>
    <div class="val mono {exp_cls}">{fmt_pct(stats['expectancy'])}</div>
    <div class="ctx">mean return across {stats['n']} closed</div></div>
  <div class="m lead"><div class="lab">Profit factor</div>
    <div class="val mono {pf_cls}">{pf}</div>
    <div class="ctx">gross win ÷ gross loss</div></div>
  <div class="m"><div class="lab">Win rate</div>
    <div class="val mono">{wr:.1f}%</div>
    <div class="spark"><i style="width:{wr_w:.0f}%;background:var(--pos)"></i></div>
    <div class="ctx">{stats['wins']} / {stats['n']} wins</div></div>
  <div class="m"><div class="lab">Cumulative</div>
    <div class="val mono {cls_sign(cum)}">{fmt_pct(cum)}</div>
    <div class="ctx">summed per-trade %</div></div>
  <div class="m"><div class="lab">Avg win / loss</div>
    <div class="val mono"><span class="pos">{stats['avg_win']:+.2f}</span> <span class="mut">/</span> <span class="neg">{stats['avg_loss']:+.2f}</span></div>
    <div class="ctx">percent per trade</div></div>
  <div class="m"><div class="lab">Sample</div>
    <div class="val mono">{stats['n']}</div>
    <div class="warnpill">⚠ LOW CONFIDENCE SAMPLE</div></div>
</div>"""
    else:
        metrics = '<div class="metrics"><div class="m"><div class="ctx">No closed trades yet.</div></div></div>'

    # ── chart selector (benchmark disabled if unavailable) ──
    bench_dis = "" if bench else "disabled"
    seg = f"""
<div class="seg" role="tablist">
  <button class="on" data-s="realized">Realized</button>
  <button data-s="hypo">Stop-adjusted</button>
  <button data-s="benchmark" {bench_dis}>Benchmark</button>
</div>"""

    # ── ledger rows (unified: open first, then closed newest-first) ──
    nmap = {(m["ticker"], m["date"]): m["n"] for m in meta}
    led_rows = ""

    for r in open_rows:
        ret = r.get("unreal_pct")
        payload = {
            "ticker": r["ticker"], "strategy": r["strategy"], "side": "LONG", "status": "OPEN",
            "entry_date": str(r.get("entry_date", ""))[:10], "exit_date": "",
            "entry": fmt_px(r.get("entry_price")), "exit": fmt_px(r.get("curr_price")) + " ·mkt",
            "ret": fmt_pct(ret), "retpos": (float(ret) >= 0 if ret is not None else True),
            "hold": hold_days(r.get("entry_date"), datetime.now().date().isoformat()),
            "reason": "—", "note": "",
        }
        led_rows += (
            f'<tr data-trade=\'{json.dumps(payload)}\'>'
            f'<td class="mut">•</td><td>{payload["entry_date"]}</td>'
            f'<td><span class="tkbadge">{r["ticker"]}</span></td><td class="side">LONG</td>'
            f'<td>{fmt_px(r.get("entry_price"))}</td><td class="mut">{fmt_px(r.get("curr_price"))}</td>'
            f'<td class="{cls_sign(ret)}">{fmt_pct(ret)}</td><td class="mut">{payload["hold"]}</td>'
            f'<td class="reason">open</td><td><span class="stat open">OPEN</span></td></tr>'
        )

    for r in sorted(closed_rows, key=lambda x: str(x.get("exit_date", "")), reverse=True):
        ed = str(r.get("exit_date", ""))[:10]
        num = nmap.get((r["ticker"], ed), "")
        note = TRADE_NOTES.get((r["ticker"], ed), "")
        ret = r.get("pnl_pct")
        fmk = '<span class="fmk">†</span>' if note else ""
        payload = {
            "ticker": r["ticker"], "strategy": r["strategy"], "side": "LONG", "status": "CLOSED",
            "entry_date": str(r.get("entry_date", ""))[:10], "exit_date": ed,
            "entry": fmt_px(r.get("entry_price")), "exit": fmt_px(r.get("exit_price")),
            "ret": fmt_pct(ret), "retpos": (float(ret) >= 0 if ret is not None else True),
            "hold": hold_days(r.get("entry_date"), r.get("exit_date")),
            "reason": r.get("exit_reason", ""), "note": note,
        }
        led_rows += (
            f'<tr data-trade=\'{json.dumps(payload)}\'>'
            f'<td class="mut">{num}</td><td>{ed}</td>'
            f'<td><span class="tkbadge">{r["ticker"]}</span>{fmk}</td><td class="side">LONG</td>'
            f'<td>{fmt_px(r.get("entry_price"))}</td><td>{fmt_px(r.get("exit_price"))}</td>'
            f'<td class="{cls_sign(ret)}">{fmt_pct(ret)}</td><td class="mut">{payload["hold"]}</td>'
            f'<td class="reason">{r.get("exit_reason","")}</td><td><span class="stat closed">CLOSED</span></td></tr>'
        )
    if not led_rows:
        led_rows = '<tr><td colspan="10" class="mut" style="text-align:center;padding:24px">No trades yet.</td></tr>'

    # ── scenario module ──
    scenario = ""
    if stats and cf:
        def pf_s(s):
            return "∞" if s["profit_factor"] == float("inf") else f'{s["profit_factor"]:.2f}'
        def drow(label, a, b, dfmt, dv):
            return (f'<tr><td>{label}</td><td>{a}</td><td class="adj">{b}</td>'
                    f'<td class="{cls_sign(dv)}">{dfmt}</td></tr>')
        cmp_rows = (
            drow("Profit factor", pf_s(stats), pf_s(cf),
                 f'{cf["profit_factor"]-stats["profit_factor"]:+.2f}', cf["profit_factor"]-stats["profit_factor"])
            + drow("Avg loss", fmt_pct(stats["avg_loss"]), fmt_pct(cf["avg_loss"]),
                   fmt_pp(cf["avg_loss"]-stats["avg_loss"]), cf["avg_loss"]-stats["avg_loss"])
            + drow("Expectancy", fmt_pct(stats["expectancy"]), fmt_pct(cf["expectancy"]),
                   fmt_pp(cf["expectancy"]-stats["expectancy"]), cf["expectancy"]-stats["expectancy"])
            + drow("Cumulative", fmt_pct(stats["curve"][-1]), fmt_pct(cf["curve"][-1]),
                   fmt_pp(cf["curve"][-1]-stats["curve"][-1]), cf["curve"][-1]-stats["curve"][-1])
        )
        scenario = f"""
<section class="sec">
  <div class="sechd"><span class="idx">03</span><h2>Scenario Analysis</h2><span class="rule"></span></div>
  <div class="scenario">
    <div class="schd"><h2 style="letter-spacing:.14em">If the stop had worked as designed</h2>
      <span class="scbadge">Hypothetical · Not realized</span></div>
    <div class="sccols">
      <div class="scfacts">
        <div class="frow"><div class="fk">What happened</div><div class="fv">One position (INTU) ran uncut past its protective stop.</div></div>
        <div class="frow"><div class="fk">Affected position</div><div class="fv"><span class="mono">INTU</span> · exited 2026-06-26 · <span class="mono neg">-13.09%</span></div></div>
        <div class="frow"><div class="fk">Bug status</div><div class="fv">June 2026 stop-expiry bug — <span class="pos">fixed</span> (persistent GTC stops + daily re-arm guard).</div></div>
        <div class="frow"><div class="fk">Assumed stop</div><div class="fv">Disaster stop fires at entry &minus;5% as designed → <span class="mono acc">-5.00%</span>.</div></div>
      </div>
      <div>
        <table class="cmp">
          <thead><tr><th>Metric</th><th>Realized</th><th>Adjusted</th><th>Delta</th></tr></thead>
          <tbody>{cmp_rows}</tbody>
        </table>
        <div style="font-family:var(--mono);font-size:10px;color:var(--mut);margin-top:9px">Adjusted figures isolate the cost of one infrastructure failure. Headline metrics on this page remain unadjusted.</div>
      </div>
    </div>
  </div>
</section>"""

    # ── chart foot / data note ──
    latest = f"{stats['curve'][-1]:+.2f}%" if stats else "—"
    chart_foot = (
        f'<span>SERIES · summed per-trade % returns, not an account equity curve</span>'
        f'<span>POINTS · {stats["n"] if stats else 0} closed trades</span>'
        f'<span>LATEST · <span class="mono {cls_sign(stats["curve"][-1]) if stats else "mut"}">{latest}</span></span>'
        f'<span class="mut">R realized · H stop-adjusted · B benchmark</span>'
    )

    # ── data payload for JS ──
    payload = {
        "realized": stats["curve"] if stats else [],
        "hypo": cf["curve"] if cf else (stats["curve"] if stats else []),
        "benchmark": bench,
        "dates": stats["dates"] if stats else [],
        "meta": meta,
        "dd": dd,
    }

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Grade — systematic swing trading terminal</title>
<meta name="description" content="Live paper-traded results of a systematic swing-trading system. Percentage metrics and public prices only; account size not disclosed.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{STYLE}</style></head>
<body><div class="wrap">

<header>
  <div class="brand">
    <div class="name"><span class="dot"></span>Systematic Swing <span class="mut mono" style="font-size:12px">01</span></div>
    <div class="sub">US EQUITIES · DAILY · CRSP 2000–2026 · MEAN-REVERSION</div>
  </div>
  <div class="hactions">
    <div class="stamp">UPDATED<br>{updated}</div>
    <span class="badge">Paper</span>
    <a class="iconbtn" href="{REPO_URL}" target="_blank" rel="noopener" title="Source code on GitHub">Source ↗</a>
    <button class="iconbtn" onclick="window.print()">Export</button>
    <button class="iconbtn" title="Settings">⚙</button>
  </div>
</header>

<div class="strip">
  <div class="cell"><div class="k">Status</div><div class="v"><span class="dot"></span><span class="pos">ACTIVE</span></div></div>
  <div class="cell"><div class="k">Active positions</div><div class="v">{n_open}</div></div>
  <div class="cell"><div class="k">Exposure</div><div class="v">LONG-ONLY</div></div>
  <div class="cell"><div class="k">Max drawdown</div><div class="v neg">{dd['val']:.2f} pp</div></div>
  <div class="cell"><div class="k">Last signal</div><div class="v">{last_signal}</div></div>
  <div class="cell"><div class="k">Data freshness</div><div class="v">{data_fresh}</div></div>
</div>

<section class="sec">
  <div class="sechd"><span class="idx">01</span><h2>Performance</h2><span class="rule"></span>
    <span class="hint">n = {stats['n'] if stats else 0}</span></div>
  {metrics}
</section>

<section class="sec">
  <div class="sechd"><span class="idx">02</span><h2>Equity Trajectory</h2><span class="rule"></span>
    <span class="hint"><kbd>R</kbd> <kbd>H</kbd> <kbd>B</kbd></span></div>
  <div class="chartgrid">
    <div class="panel chartcard">
      <div class="chart-top"><div class="mut mono" style="font-size:10px;letter-spacing:.14em">CUMULATIVE % · PER-TRADE</div>{seg}</div>
      <div class="chartwrap" id="chartwrap">
        <svg id="chart" viewBox="0 0 1000 360" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="tip" id="tip"></div>
      </div>
      <div class="chart-foot">{chart_foot}</div>
    </div>
    <div class="rail">
      <div class="rcard">
        <h3>Confidence</h3>
        <div class="rbig mono amb">{stats['n'] if stats else 0}<span style="font-size:12px;color:var(--mut)"> closed</span></div>
        <div class="warnpill" style="margin:2px 0 10px">⚠ LOW CONFIDENCE SAMPLE</div>
        <div class="rrow"><span class="k">Win rate</span><span class="v">{stats['win_rate']:.1f}%</span></div>
        <div class="rrow"><span class="k">95% Wilson CI</span><span class="v acc">{ci_lo:.0f}–{ci_hi:.0f}%</span></div>
        <div class="rrow"><span class="k" style="color:var(--mut);font-size:10px">Interval is wide at n={stats['n'] if stats else 0}; treat metrics as directional.</span><span class="v"></span></div>
      </div>
      <div class="rcard">
        <h3>Risk</h3>
        <div class="rrow"><span class="k">Max drawdown</span><span class="v neg">{dd['val']:.2f} pp</span></div>
        <div class="rrow"><span class="k">Exposure</span><span class="v">Long-only</span></div>
        <div class="rrow"><span class="k">Open positions</span><span class="v">{n_open}</span></div>
        <div class="rrow"><span class="k">Disaster stop</span><span class="v">4×ATR + GTC</span></div>
      </div>
      <div class="rcard">
        <h3>Strategy</h3>
        <div class="rrow"><span class="k">Type</span><span class="v">Mean-reversion</span></div>
        <div class="rrow"><span class="k">Signals</span><span class="v">BBands · RSI</span></div>
        <div class="rrow"><span class="k">Validation</span><span class="v">Walk-forward</span></div>
        <div class="rrow"><span class="k">Universe</span><span class="v">US equities</span></div>
        <div class="rrow"><span class="k">Data</span><span class="v">CRSP + yfinance</span></div>
      </div>
    </div>
  </div>
</section>

{scenario}

<section class="sec">
  <div class="sechd"><span class="idx">04</span><h2>Trade Ledger</h2><span class="rule"></span>
    <span class="hint mut">click a row for detail</span></div>
  <div class="ledwrap"><div class="ledscroll">
    <table class="led">
      <thead><tr>
        <th>#</th><th>Date</th><th>Ticker</th><th>Side</th><th>Entry</th><th>Exit</th>
        <th>Return</th><th>Hold</th><th>Reason</th><th>Status</th>
      </tr></thead>
      <tbody>{led_rows}</tbody>
    </table>
  </div></div>
</section>

<footer>
  <span>{SITE} · paper-traded · updated {updated}</span>
  <span>Percentage returns and public entry/exit prices only. Share counts, dollar P&amp;L, cost basis and account equity are intentionally omitted.</span>
  <span>Not investment advice · not an offer of any service. · <a href="{REPO_URL}" target="_blank" rel="noopener" style="color:var(--acc)">source ↗</a></span>
</footer>
</div>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer">
  <div class="dhd"><div class="dtk mono" id="dtk">—</div><button class="close" id="dclose">ESC ✕</button></div>
  <div id="dbody"></div>
  <div class="dnote" id="dnote" style="display:none"></div>
</aside>

<script>window.__SG={json.dumps(payload)};</script>
<script>{CHART_JS}</script>
</body></html>"""


def main() -> None:
    df = load_trades()
    stats = public_stats(df)
    cf = public_stats(apply_counterfactual(df)) if (stats and TRADE_COUNTERFACTUAL) else None
    meta = trade_meta(df)
    bench = benchmark_curve(df["entry_date"].min(), stats["dates"]) if stats else None
    open_rows = enrich_open_positions(df)
    closed_rows = build_closed_table(df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".html.tmp")
    tmp.write_text(render(stats, cf, meta, bench, open_rows, closed_rows), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Public page written -> {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
