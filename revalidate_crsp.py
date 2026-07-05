#!/usr/bin/env python3
"""Survivorship-honest re-validation of every (ticker, strategy) combo on CRSP.

Why: the live watchlist (validation_results.csv, May 2026) was built on 735 CURRENT
survivors with no stop, no costs, and full-equity vectorbt sims — three flatteries at
once. It yields only 29 combos / 22 tickers, which saturates the book at ~10-13
positions (the binding deployment constraint per the sizing sweep). This script
re-scores all mapped tickers x 6 strategies on the survivorship-free CRSP panel
(delisted names included, delisting returns applied) under the DEPLOYED trade rules:
next-open fills, 4xATR disaster stop, indicator exits, 15bps/side.

Method (mirrors validate.py's expanding-window discipline):
  1. One independent trade ledger per combo (single position, own capital).
  2. For each test year in WINDOWS: rank combos by IS t-stat (trades before the
     window), take the top TOP_N_IS, evaluate them on the test year only.
  3. Aggregate per combo across windows -> validation_results_crsp.csv with the
     SAME schema/filter semantics bot.py already uses (oos_sharpe, sharpe_decay,
     oos_profitable, windows_tested).

Run:  python revalidate_crsp.py [--limit N]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_parity import (STRATEGIES, EXCLUDED_STRATEGIES, load_crsp_panel,
                             map_tickers_to_permno, build_ticker_universe,
                             load_delistings, OUT_DIR)

ATR_STOP_MULT = 4.0
COST_BPS      = 15.0
TRADE_START   = pd.Timestamp("2005-01-01")
MIN_IS_TRADES = 20          # need a real sample before a combo can rank
TOP_N_IS      = 100         # candidates per window (wider than old 50: we WANT breadth,
                            # the OOS gates do the filtering)
WINDOWS       = [2008, 2011, 2015, 2018, 2021, 2022, 2023, 2024]   # test years
MIN_PRICE     = 5.0         # tradability floor at entry
MIN_ADV       = 2e6         # 20d dollar-volume floor at entry


def combo_trades(g: pd.DataFrame, entries: pd.Series, exits: pd.Series,
                 dlret: float | None) -> list[dict]:
    """Independent single-position replay of one combo under the deployed rules."""
    dates = g.index.values
    aopen, alow  = g["adj_open"].values, g["adj_low"].values
    aclose, atr  = g["adj_close"].values, g["atr"].values
    adv          = g["adv20"].values
    ent = entries.reindex(g.index, fill_value=False).values
    exi = exits.reindex(g.index, fill_value=False).values
    cost = COST_BPS / 1e4

    trades, in_pos, pending = [], False, False
    e_px = e_i = stop = None
    for i in range(1, len(dates)):
        if in_pos:
            o = aopen[i] if np.isfinite(aopen[i]) else aclose[i]
            if pending:                                   # decided yesterday, exit at open
                x_px = o * (1 - cost)
                trades.append({"entry_date": dates[e_i], "exit_date": dates[i],
                               "ret": x_px / e_px - 1, "reason": "signal"})
                in_pos = pending = False
                continue
            if np.isfinite(alow[i]) and alow[i] <= stop:  # disaster stop, gap-through at open
                x_px = min(stop, o) * (1 - cost)
                trades.append({"entry_date": dates[e_i], "exit_date": dates[i],
                               "ret": x_px / e_px - 1, "reason": "stop"})
                in_pos = False
                continue
            if i == len(dates) - 1:                       # series end: delist or last mark
                r = (dlret if dlret is not None else 0.0)
                x_px = aclose[i] * (1 + r) * (1 - cost)
                trades.append({"entry_date": dates[e_i], "exit_date": dates[i],
                               "ret": x_px / e_px - 1,
                               "reason": "delisted" if dlret is not None else "series_end"})
                in_pos = False
                continue
            if exi[i]:
                pending = True
            continue
        # flat: yesterday's entry signal fills at today's open
        if ent[i - 1] and dates[i] >= TRADE_START.to_datetime64():
            o = aopen[i] if np.isfinite(aopen[i]) else aclose[i]
            if not np.isfinite(o) or o < MIN_PRICE:
                continue
            if np.isfinite(adv[i - 1]) and adv[i - 1] < MIN_ADV:
                continue
            e_px, e_i = o * (1 + cost), i
            a = atr[i - 1]
            stop = (o - ATR_STOP_MULT * a) if np.isfinite(a) else o * 0.90
            in_pos, pending = True, False
    return trades


def tstat(rets: np.ndarray) -> float:
    if len(rets) < 2 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(len(rets)))


def ann_sharpe(rets: np.ndarray, years: float) -> float:
    """Per-trade returns -> annualized Sharpe proxy: t-stat scaled to per-year."""
    if len(rets) < 2 or rets.std() == 0 or years <= 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(len(rets) / years))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    universe = build_ticker_universe()
    mapping = map_tickers_to_permno(universe)
    tickers = sorted(mapping)[: args.limit] if args.limit else sorted(mapping)
    print(f"tickers: {len(tickers)}  strategies: {len(STRATEGIES) - len(EXCLUDED_STRATEGIES)}")

    panel = load_crsp_panel(set(mapping[t] for t in tickers))
    delist = load_delistings()
    dl_map = {int(r.permno): (r.dlret if pd.notna(r.dlret) else -0.35)
              for r in delist.itertuples() if r.dlstcd >= 200}

    # per-permno frames with ATR + ADV (same construction as backtest_parity)
    per, ledgers = {}, {}
    for permno, g in panel.groupby("permno", sort=False):
        g = g.set_index("date").sort_index()
        pc = g["adj_close"].shift(1)
        tr = pd.concat([g["adj_high"] - g["adj_low"], (g["adj_high"] - pc).abs(),
                        (g["adj_low"] - pc).abs()], axis=1).max(axis=1)
        g["atr"] = tr.rolling(14).mean()
        g["adv20"] = (g["adj_close"] * g["vol"]).rolling(20).mean()
        per[permno] = g

    print("building per-combo trade ledgers...")
    strategies = [s for s in STRATEGIES if s not in EXCLUDED_STRATEGIES]
    for n, t in enumerate(tickers):
        g = per.get(mapping[t])
        if g is None or len(g) < 300:
            continue
        close = g["adj_close"].dropna()
        for s in strategies:
            try:
                e, x = STRATEGIES[s](close)
            except Exception:
                continue
            tr = combo_trades(g, e.fillna(False), x.fillna(False), dl_map.get(mapping[t]))
            if tr:
                ledgers[(t, s)] = pd.DataFrame(tr)
        if (n + 1) % 100 == 0:
            print(f"  {n+1}/{len(tickers)} tickers, {len(ledgers)} ledgers", flush=True)
    print(f"ledgers built: {len(ledgers)} combos with >=1 trade")

    # expanding-window IS -> OOS evaluation
    print("walk-forward evaluation...")
    from collections import defaultdict
    agg = defaultdict(lambda: {"is_sharpes": [], "oos_sharpes": [], "oos_pos": 0, "n_win": 0})
    for ty in WINDOWS:
        t0, t1 = pd.Timestamp(f"{ty}-01-01"), pd.Timestamp(f"{ty}-12-31")
        scored = []
        for key, led in ledgers.items():
            is_r = led[led.exit_date < t0]["ret"].values
            if len(is_r) < MIN_IS_TRADES:
                continue
            scored.append((tstat(is_r), key, is_r))
        scored.sort(reverse=True, key=lambda z: z[0])
        for is_t, key, is_r in scored[:TOP_N_IS]:
            led = ledgers[key]
            oos = led[(led.exit_date >= t0) & (led.exit_date <= t1)]["ret"].values
            if len(oos) < 2:
                continue                                   # inactive in the window
            yrs_is = max((t0 - TRADE_START).days / 365.25, 1e-9)
            a = agg[key]
            a["is_sharpes"].append(ann_sharpe(is_r, yrs_is))
            a["oos_sharpes"].append(ann_sharpe(oos, 1.0))
            a["oos_pos"] += int(oos.mean() > 0)
            a["n_win"] += 1

    rows = []
    for (t, s), a in agg.items():
        if a["n_win"] == 0:
            continue
        oos_sharpe = float(np.mean(a["oos_sharpes"]))
        is_sharpe = float(np.mean(a["is_sharpes"])) or 1e-9
        led = ledgers[(t, s)]
        rows.append({
            "ticker": t, "strategy": s,
            "oos_sharpe": round(oos_sharpe, 3),
            "sharpe_decay": round(max(oos_sharpe, 0) / max(is_sharpe, 1e-9), 3),
            "oos_profitable": bool(a["oos_pos"] / a["n_win"] > 0.5),
            "windows_tested": a["n_win"],
            "total_trades": len(led),
            "expectancy_bps": round(led.ret.mean() * 1e4, 1),
            "stop_rate": round((led.reason == "stop").mean(), 3),
        })
    res = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    out = OUT_DIR / "validation_results_crsp.csv"
    res.to_csv(out, index=False)

    # what would the live bot select from this file?
    sel = res[(res.oos_sharpe >= 0.3) & (res.sharpe_decay >= 0.4)
              & res.oos_profitable & (res.windows_tested >= 3)].head(50)
    print(f"\nwrote {out}  ({len(res)} scored combos)")
    print(f"bot filter would select: {len(sel)} combos / {sel.ticker.nunique()} tickers "
          f"(old watchlist: 29 combos / 22 tickers)")
    print("\nby strategy in selection:")
    if len(sel):
        print(sel.groupby("strategy").size().to_string())
        print("\ntop 15:")
        print(sel.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
