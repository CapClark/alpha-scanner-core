"""
Gate 0 — Portfolio Parity Backtester

The live bot (bot.py) has never been backtested with its real 5% stop-loss or
any transaction costs — signals.py/validate.py score raw entry/exit crossovers
with no stop, no costs, no portfolio constraints. This script replays the
bot's actual rules (position sizing, MAX_POSITIONS, stop-loss, regime filter)
on survivorship-bias-free CRSP daily data so we can see whether the "live"
edge survives honest accounting.

Usage:
    ./venv/bin/python backtest_parity.py --mode watchlist
    ./venv/bin/python backtest_parity.py --mode all --limit 50 --no-cost
"""
import argparse
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies import STRATEGIES

warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────
CANSLIM_DIR   = Path("/Users/kenpeeranat/Documents/strategy_grade.io/canslim-core")
CRSP_DIR      = CANSLIM_DIR / "datasets/pead/crsp_daily"
DELIST_FILE   = CANSLIM_DIR / "datasets/pead/dsedelist.parquet"
CCM_LINK_FILE = CANSLIM_DIR / "datasets/pead/ccm_link.csv"
STOCKNAMES_FILE = CANSLIM_DIR / "datasets/pead/stocknames.parquet"
DSI_FILE      = CANSLIM_DIR / "datasets/pead/dsi.parquet"
FUNDAMENTALS_DIR = CANSLIM_DIR / "datasets/fundamentals"

CACHE_DIR     = Path("datasets/cache")
VALIDATION_FILE = Path("datasets/validation_results.csv")
OUT_DIR       = Path("datasets")

# ── Bot config, mirrored from bot.py ────────────────────────────────────────
POSITION_SIZE  = 10_000
STOP_LOSS_PCT  = 0.05
MAX_POSITIONS  = 10
STARTING_CASH  = 100_000.0
EXCLUDED_STRATEGIES = {"RSI(21)"}   # blacklisted in live trading, confirmed negative OOS

LOAD_START = "2000-01-01"   # need 2000+ for 200d MA warmup
LOAD_END   = "2024-12-31"
TRADE_START = pd.Timestamp("2005-01-01")   # reported/traded window
TRADE_END   = pd.Timestamp("2024-12-31")


# ── Data loading ─────────────────────────────────────────────────────────────

def load_crsp_panel(permnos: set[int]) -> pd.DataFrame:
    """Concat the dsf_*.parquet files, filtered to needed permnos at read time
    (the full panel is 27M rows — loading it unfiltered wastes several GB)."""
    cols = ["permno", "date", "openprc", "prc", "askhi", "bidlo", "vol", "ret", "cfacpr"]
    files = sorted(CRSP_DIR.glob("dsf_*.parquet"))
    flt = [("permno", "in", sorted(permnos))]
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=cols, filters=flt)
        df = df[(df["date"] >= LOAD_START) & (df["date"] <= LOAD_END)]
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)

    panel["permno"] = panel["permno"].astype("int32")
    panel["prc"] = panel["prc"].abs()   # CRSP occasionally stores negative bid/ask-midpoint prc

    # Split-adjusted price levels for indicators/stop checks (NOT for return compounding)
    panel["adj_close"] = panel["prc"] / panel["cfacpr"]
    panel["adj_open"]  = panel["openprc"] / panel["cfacpr"]
    panel["adj_high"]  = panel["askhi"] / panel["cfacpr"]
    panel["adj_low"]   = panel["bidlo"] / panel["cfacpr"]

    panel = panel.sort_values(["permno", "date"]).reset_index(drop=True)
    return panel


def load_delistings() -> pd.DataFrame:
    df = pd.read_parquet(DELIST_FILE, columns=["permno", "dlstdt", "dlstcd", "dlret"])
    df["permno"] = df["permno"].astype("int32")
    return df


def build_market_index() -> pd.DataFrame:
    """
    CRSP value-weighted market return as a stand-in for the live bot's SPY filter.
    We're working off CRSP data here (not a live SPY feed), so vwretd (total return,
    incl. dividends) is the closest available proxy for "the market" vs 200dma.
    """
    dsi = pd.read_parquet(DSI_FILE, columns=["date", "vwretd"])
    dsi = dsi.sort_values("date").reset_index(drop=True)
    dsi["index_level"] = (1 + dsi["vwretd"]).cumprod()
    dsi["ma200"] = dsi["index_level"].rolling(200).mean()
    dsi["regime_ok"] = dsi["index_level"] > dsi["ma200"]
    return dsi.set_index("date")[["index_level", "ma200", "regime_ok"]]


# ── Ticker -> permno mapping ─────────────────────────────────────────────────

def build_ticker_universe() -> list[str]:
    return sorted(p.name[:-len("_prices.csv")] for p in CACHE_DIR.glob("*_prices.csv"))


def map_tickers_to_permno(tickers: list[str]) -> dict[str, int]:
    """
    Local-only ticker->permno mapping (no network calls):
      1. Prefer stocknames.parquet (ticker, namedt/nameenddt) if it exists.
      2. Else fall back to fundamentals gvkey -> ccm_link.csv -> permno.
    """
    FAR_FUTURE = pd.Timestamp("2099-12-31")
    mapping: dict[str, int] = {}

    stocknames = None
    if STOCKNAMES_FILE.exists():
        try:
            stocknames = pd.read_parquet(STOCKNAMES_FILE, columns=["permno", "ticker", "namedt", "nameenddt"])
            stocknames["nameenddt_sort"] = stocknames["nameenddt"].fillna(FAR_FUTURE)
        except Exception:
            stocknames = None   # background job may still be writing this file — degrade gracefully

    ccm = pd.read_csv(CCM_LINK_FILE, dtype={"gvkey": str})
    ccm["linkenddt"] = pd.to_datetime(ccm["linkenddt"], errors="coerce")
    ccm["linkenddt_sort"] = ccm["linkenddt"].fillna(FAR_FUTURE)

    for ticker in tickers:
        # Path 1: stocknames.parquet, if available and has a match
        if stocknames is not None:
            hits = stocknames[stocknames["ticker"] == ticker]
            if not hits.empty:
                best = hits.sort_values("nameenddt_sort", ascending=False).iloc[0]
                mapping[ticker] = int(best["permno"])
                continue

        # Path 2: fundamentals gvkey -> ccm_link -> permno
        fpath = FUNDAMENTALS_DIR / f"{ticker}_qtr.csv"
        if not fpath.exists():
            continue
        try:
            fdf = pd.read_csv(fpath, dtype=str, nrows=1)
        except Exception:
            continue
        if "gvkey" not in fdf.columns or fdf.empty or pd.isna(fdf["gvkey"].iloc[0]):
            continue
        gvkey = str(fdf["gvkey"].iloc[0]).zfill(6)

        cand = ccm[ccm["gvkey"] == gvkey]
        if cand.empty:
            continue
        preferred = cand[cand["linkprim"] == "P"]
        if preferred.empty:
            preferred = cand[cand["linkprim"] == "C"]
        if preferred.empty:
            continue
        best = preferred.sort_values("linkenddt_sort", ascending=False).iloc[0]
        if pd.isna(best["permno"]):
            continue
        mapping[ticker] = int(best["permno"])

    return mapping


# ── Watchlist ────────────────────────────────────────────────────────────────

def load_watchlist_combos() -> list[tuple[str, str]]:
    """(ticker, strategy) combos matching the live bot's validated-survivor filter."""
    val = pd.read_csv(VALIDATION_FILE)
    # oos_profitable may be bool or string depending on how the CSV was written
    if val["oos_profitable"].dtype == object:
        prof = val["oos_profitable"].astype(str).str.strip().str.lower() == "true"
    else:
        prof = val["oos_profitable"].astype(bool)

    survivors = val[
        (val["oos_sharpe"] >= 0.3) &
        (val["sharpe_decay"] >= 0.4) &
        prof &
        (val["windows_tested"] >= 3) &
        (~val["strategy"].isin(EXCLUDED_STRATEGIES))
    ].sort_values("oos_sharpe", ascending=False).head(50)

    return list(zip(survivors["ticker"], survivors["strategy"]))


def all_mode_combos(tickers: list[str]) -> list[tuple[str, str]]:
    strategies = [s for s in STRATEGIES if s not in EXCLUDED_STRATEGIES]
    return [(t, s) for t in tickers for s in strategies]


# ── Signal engine ────────────────────────────────────────────────────────────

def compute_signals(adj_close: pd.Series, strategy: str) -> tuple[pd.Series, pd.Series]:
    """STRATEGIES fns are already causal (use data up to and incl. day t) — no extra lag needed."""
    entries, exits = STRATEGIES[strategy](adj_close)
    return entries.fillna(False), exits.fillna(False)


# ── Portfolio simulation ─────────────────────────────────────────────────────

class Position:
    __slots__ = ("ticker", "strategy", "permno", "entry_date", "entry_price", "qty",
                 "stop_price", "value", "pending_exit")

    def __init__(self, ticker, strategy, permno, entry_date, entry_price, qty, stop_price):
        self.ticker = ticker
        self.strategy = strategy
        self.permno = permno
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.qty = qty
        self.stop_price = stop_price
        self.value = qty * entry_price   # mark-to-market value, updated daily
        self.pending_exit = False        # indicator exit signaled yesterday, fires at today's open


def run_backtest(combos: list[tuple[str, str]], mapping: dict[str, int],
                  panel: pd.DataFrame, delist: pd.DataFrame, regime: pd.DataFrame,
                  cost_bps: float, use_stop: bool) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Single shared portfolio replay over the union trading calendar.
    combos order = watchlist priority order (first strategy in sorted list wins ties).
    """
    nan_open_count = 0
    nan_open_total = 0

    # Preload each needed permno's series once, indexed by date, with a lookup dict per day.
    permno_by_ticker = {t: mapping[t] for t, _ in combos if t in mapping}
    needed_permnos = set(permno_by_ticker.values())
    panel = panel[panel["permno"].isin(needed_permnos)]

    per_permno = {}
    for permno, g in panel.groupby("permno", sort=False):
        g = g.set_index("date").sort_index()
        per_permno[permno] = g

    # Delisting lookup: permno -> (dlstdt, dlret, dlstcd)
    delist_map = {}
    for _, row in delist[delist["permno"].isin(needed_permnos)].iterrows():
        delist_map[row["permno"]] = (row["dlstdt"], row["dlret"], row["dlstcd"])

    # Precompute signals per (ticker, strategy) combo, restricted to that ticker's permno history
    combo_signals = {}
    for ticker, strategy in combos:
        permno = permno_by_ticker.get(ticker)
        if permno is None or permno not in per_permno:
            continue
        g = per_permno[permno]
        adj_close = g["adj_close"].dropna()
        if len(adj_close) < 210:   # not enough history to warm up 200d indicators
            continue
        try:
            entries, exits = compute_signals(adj_close, strategy)
        except Exception:
            continue
        combo_signals[(ticker, strategy)] = (entries, exits, permno)

    # Union trading calendar across all combos' permno data, restricted to full load window
    # (entries execute at t+1 open, so we need every calendar day any combo trades on).
    all_dates = sorted(set().union(*[per_permno[p].index for p in
                                      {v[2] for v in combo_signals.values()}])) if combo_signals else []
    all_dates = pd.DatetimeIndex(all_dates)

    cash = STARTING_CASH
    open_positions: dict[str, Position] = {}   # ticker -> Position
    trades = []
    equity_curve = []
    skipped_events = []

    for i, day in enumerate(all_dates):
        if day < TRADE_START or day > TRADE_END:
            # still need to walk through to keep positions/marking consistent pre-window,
            # but we only report equity/trades inside the traded window
            in_window = False
        else:
            in_window = True

        # regime lookup — fail open (allow entries) if index data missing for this date
        if day in regime.index:
            regime_ok = bool(regime.loc[day, "regime_ok"]) if not pd.isna(regime.loc[day, "regime_ok"]) else True
        else:
            regime_ok = True

        # ── 1. Process exits for currently open positions (stop first, then signal, then delist) ──
        # Priority per spec: delisting terminates the series regardless; otherwise stop is
        # checked BEFORE the indicator exit on the same day (stop takes priority).
        for ticker in list(open_positions.keys()):
            pos = open_positions[ticker]
            permno = pos.permno
            g = per_permno.get(permno)
            if g is None or day not in g.index:
                continue
            row = g.loc[day]
            exited = False

            # A pending indicator-exit signaled on a prior day fires at TODAY's open,
            # ahead of everything else that could happen today (it was already decided).
            if pos.pending_exit:
                adj_open = row["adj_open"]
                if pd.isna(adj_open):
                    adj_open = row["adj_close"]   # illiquid day, no printed open — use close as best proxy
                    nan_open_count += 1
                nan_open_total += 1
                exit_fill_price = adj_open * (1 - cost_bps / 10000)   # costs move fills against you
                exit_value = pos.qty * exit_fill_price
                cash += exit_value
                trades.append(_trade_record(pos, day, exit_fill_price, "signal", exit_value - pos.qty * pos.entry_price))
                del open_positions[ticker]
                continue

            # SERIES END — permno stops trading today. With a bad delist row
            # (dlstcd>=200) apply dlret (NaN -> -0.35 conservative). Without one,
            # still close at the last mark so the position can't linger as a
            # frozen value for the rest of the backtest.
            dl = delist_map.get(permno)
            is_last_day = (g.index[-1] == day)
            if is_last_day and day < all_dates[-1]:
                if dl is not None and dl[2] >= 200:
                    dlret = dl[1]
                    if pd.isna(dlret):
                        dlret = -0.35   # conservative standard assumption when dlret missing
                    exit_value = pos.value * (1 + dlret)
                    reason = "delisted"
                else:
                    exit_value = pos.value * (1 - cost_bps / 10000)
                    reason = "series_end"
                exit_fill_price = exit_value / pos.qty if pos.qty else 0.0
                cash += exit_value
                trades.append(_trade_record(pos, day, exit_fill_price, reason, exit_value - pos.qty * pos.entry_price))
                del open_positions[ticker]
                exited = True

            # STOP LOSS — checked before the indicator exit signal on the same day
            if not exited and use_stop and not pd.isna(row.get("adj_low", np.nan)):
                if row["adj_low"] <= pos.stop_price:
                    adj_open = row["adj_open"]
                    if pd.isna(adj_open):
                        adj_open = row["adj_close"]
                        nan_open_count += 1
                    nan_open_total += 1
                    exit_fill_price = min(pos.stop_price, adj_open)   # gap-through: worse of stop or open
                    exit_fill_price *= (1 - cost_bps / 10000)
                    exit_value = pos.qty * exit_fill_price
                    cash += exit_value
                    trades.append(_trade_record(pos, day, exit_fill_price, "stop", exit_value - pos.qty * pos.entry_price))
                    del open_positions[ticker]
                    exited = True

            # INDICATOR EXIT — mark pending, fills at next day's open
            if not exited:
                sig = combo_signals.get((ticker, pos.strategy))
                if sig is not None:
                    entries, exits, _ = sig
                    if day in exits.index and bool(exits.loc[day]):
                        pos.pending_exit = True

            if not exited:
                # mark position value forward using CRSP total return (captures divs/splits day to day)
                ret = row.get("ret", np.nan)
                if not pd.isna(ret):
                    pos.value *= (1 + ret)

        # ── 2. Process new entries (only if regime healthy, respecting MAX_POSITIONS/cash/dedupe) ──
        # Data from 2000-2004 is warmup only for indicators — the traded/reported window
        # starts 2005-01-01, so no NEW entries are allowed before that (exits/marking of any
        # already-open position would still run, but none can exist pre-window since nothing
        # can open before TRADE_START).
        if regime_ok and in_window:
            for ticker, strategy in combos:
                if ticker not in permno_by_ticker:
                    continue
                if ticker in open_positions:
                    continue   # one open position per ticker max; combos iterate in
                               # watchlist-priority order, so the first strategy that
                               # fires wins the dedupe when several signal at once
                sig = combo_signals.get((ticker, strategy))
                if sig is None:
                    continue
                entries, exits, permno = sig
                if day not in entries.index or not bool(entries.loc[day]):
                    continue
                g = per_permno[permno]
                # entries fill at t+1's open — find next trading day for this permno
                idx = g.index.searchsorted(day)
                if idx + 1 >= len(g):
                    continue
                fill_day = g.index[idx + 1]
                fill_row = g.loc[fill_day]
                adj_open = fill_row["adj_open"]
                if pd.isna(adj_open):
                    adj_open = fill_row["adj_close"]
                    nan_open_count += 1
                nan_open_total += 1

                if len(open_positions) >= MAX_POSITIONS:
                    skipped_events.append((fill_day, ticker, "portfolio full"))
                    continue

                fill_price = adj_open * (1 + cost_bps / 10000)
                qty = int(POSITION_SIZE / fill_price)
                if qty <= 0:
                    continue
                cost = qty * fill_price
                if cash < cost:
                    skipped_events.append((fill_day, ticker, "insufficient cash"))
                    continue

                cash -= cost
                pos = Position(ticker, strategy, permno, fill_day, fill_price, qty,
                                fill_price * (1 - STOP_LOSS_PCT))
                open_positions[ticker] = pos
                # NOTE: this entry executes on fill_day, one calendar step ahead of `day`;
                # we still record it against combos in signal order (dedupe handled by ticker-in-open_positions check)

        # ── 3. Daily equity mark ──
        if in_window:
            mtm = sum(p.value for p in open_positions.values())
            equity_curve.append((day, cash + mtm))

    # Force-close anything still open at sample end at its last mark so the
    # trade ledger reconciles with the final equity value.
    if len(all_dates):
        for ticker in list(open_positions.keys()):
            pos = open_positions[ticker]
            exit_value = pos.value * (1 - cost_bps / 10000)
            exit_fill_price = exit_value / pos.qty if pos.qty else 0.0
            cash += exit_value
            trades.append(_trade_record(pos, all_dates[-1], exit_fill_price, "open_at_end",
                                        exit_value - pos.qty * pos.entry_price))
            del open_positions[ticker]

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve, columns=["date", "equity"])

    diag = {
        "nan_open_count": nan_open_count,
        "nan_open_total": nan_open_total,
        "skipped_events": skipped_events,
    }
    return trades_df, equity_df, diag


def _trade_record(pos: Position, exit_date, exit_price, exit_reason, pnl) -> dict:
    return_pct = (exit_price / pos.entry_price - 1) * 100 if pos.entry_price else 0.0
    return {
        "ticker": pos.ticker,
        "strategy": pos.strategy,
        "permno": pos.permno,
        "entry_date": pos.entry_date,
        "entry_price": pos.entry_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "qty": pos.qty,
        "pnl": pnl,
        "return_pct": return_pct,
    }


# ── Stats ────────────────────────────────────────────────────────────────────

def compute_stats(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    pf = gross_win / gross_loss if gross_loss > 0 else np.inf
    win_pct = len(wins) / len(trades) * 100
    avg_win = wins["pnl"].mean() if not wins.empty else 0.0
    avg_loss = losses["pnl"].mean() if not losses.empty else 0.0
    expectancy = trades["pnl"].mean()
    total_pnl = trades["pnl"].sum()

    years = (equity["date"].max() - equity["date"].min()).days / 365.25 if len(equity) > 1 else np.nan
    end_equity = STARTING_CASH + total_pnl
    cagr = (end_equity / STARTING_CASH) ** (1 / years) - 1 if years and years > 0 else np.nan

    eq = equity.sort_values("date")["equity"]
    running_max = eq.cummax()
    drawdown = (eq - running_max) / running_max
    max_dd = drawdown.min() * 100 if len(drawdown) else np.nan

    daily_ret = eq.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else np.nan

    return dict(trades=len(trades), win_pct=win_pct, pf=pf, avg_win=avg_win, avg_loss=avg_loss,
                expectancy=expectancy, total_pnl=total_pnl, cagr=cagr, max_dd=max_dd, sharpe=sharpe)


# ── Report ───────────────────────────────────────────────────────────────────

def print_report(args, mapping_n, universe_n, trades: pd.DataFrame, equity: pd.DataFrame, diag: dict):
    print("=" * 70)
    print("GATE 0 — PARITY BACKTEST (live watchlist honest replay)")
    print("=" * 70)
    print(f"mode={args.mode}  cost_bps={0 if args.no_cost else args.cost_bps}  "
          f"stop={'OFF' if args.no_stop else 'ON'}  window={TRADE_START.date()}..{TRADE_END.date()}  "
          f"MAX_POSITIONS={MAX_POSITIONS}  POSITION_SIZE=${POSITION_SIZE:,}  limit={args.limit}")
    print(f"Ticker->permno mapping: {mapping_n}/{universe_n} tickers mapped")
    print()

    if trades.empty:
        print("No trades generated — nothing further to report.")
        return

    stats = compute_stats(trades, equity)
    print("OVERALL:")
    print(f"  trades={stats['trades']}  win%={stats['win_pct']:.1f}  PF={stats['pf']:.2f}  "
          f"avg_win=${stats['avg_win']:.2f}  avg_loss=${stats['avg_loss']:.2f}  "
          f"expectancy=${stats['expectancy']:.2f}  total_pnl=${stats['total_pnl']:,.2f}")
    print(f"  CAGR={stats['cagr']*100:.2f}%  max_dd={stats['max_dd']:.2f}%  sharpe={stats['sharpe']:.2f}")
    print()

    print("BY STRATEGY:")
    for strat, g in trades.groupby("strategy"):
        wins = g[g["pnl"] > 0]
        losses = g[g["pnl"] <= 0]
        pf = wins["pnl"].sum() / -losses["pnl"].sum() if -losses["pnl"].sum() > 0 else np.inf
        print(f"  {strat:<22}  trades={len(g):<4}  win%={len(wins)/len(g)*100:5.1f}  "
              f"PF={pf:6.2f}  total_pnl=${g['pnl'].sum():,.2f}")
    print()

    print("BY EXIT REASON:")
    for reason, g in trades.groupby("exit_reason"):
        print(f"  {reason:<10}  count={len(g):<5}  avg_pnl=${g['pnl'].mean():,.2f}")
    print()

    print("vs live realized: PF 1.11, 62% win, avg win $513, avg loss $768")
    print()

    if diag["nan_open_total"] > 0:
        pct = diag["nan_open_count"] / diag["nan_open_total"] * 100
        print(f"NOTE: NaN adj_open fallback to adj_close used {diag['nan_open_count']}/{diag['nan_open_total']} "
              f"fills ({pct:.2f}%) — illiquid days lacking a printed open.")
    if diag["skipped_events"]:
        print(f"NOTE: {len(diag['skipped_events'])} entries skipped (portfolio full / insufficient cash).")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gate 0 parity backtest of the live watchlist")
    parser.add_argument("--mode", choices=["watchlist", "all"], default="watchlist")
    parser.add_argument("--cost_bps", type=float, default=15.0)
    parser.add_argument("--no-cost", action="store_true")
    parser.add_argument("--no-stop", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cost_bps = 0.0 if args.no_cost else args.cost_bps
    use_stop = not args.no_stop

    universe = build_ticker_universe()
    if args.mode == "watchlist":
        combos = load_watchlist_combos()
        tickers_needed = sorted({t for t, _ in combos})
    else:
        tickers_needed = universe
        combos = None  # built after mapping, below

    if args.limit is not None:
        tickers_needed = tickers_needed[:args.limit]
        if combos is not None:
            combos = [(t, s) for t, s in combos if t in set(tickers_needed)]

    # Map the FULL universe (not just the watchlist) so the coverage number is
    # comparable across modes and flags mapping gaps in the whole cache.
    print("Mapping tickers to permno...")
    full_mapping = map_tickers_to_permno(universe)
    print(f"  Ticker->permno mapping: {len(full_mapping)}/{len(universe)} tickers mapped")
    unmapped_needed = [t for t in tickers_needed if t not in full_mapping]
    if unmapped_needed:
        print(f"  No permno for needed tickers: {unmapped_needed}")
    mapping = {t: full_mapping[t] for t in tickers_needed if t in full_mapping}

    if args.mode == "all":
        combos = all_mode_combos(sorted(mapping.keys()))

    print("Loading CRSP daily panel (2000-2024)...")
    panel = load_crsp_panel(set(mapping.values()))
    delist = load_delistings()
    regime = build_market_index()

    print(f"Running portfolio simulation over {len(combos)} combos...")
    trades, equity, diag = run_backtest(combos, mapping, panel, delist, regime, cost_bps, use_stop)

    print_report(args, len(full_mapping), len(universe), trades, equity, diag)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUT_DIR / f"parity_trades_{args.mode}.csv", index=False)
    equity.to_csv(OUT_DIR / f"parity_equity_{args.mode}.csv", index=False)


if __name__ == "__main__":
    main()
