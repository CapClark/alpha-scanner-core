"""
Rolling Walk-Forward Validation
Tests strategy-ticker combos across multiple train/test windows to reduce
variance from any single split. Each window trains on expanding history
and tests on the following calendar year.

Windows (9 total — stress-tests across distinct market regimes):
    Train 2000–2005 → Test 2006  (post dot-com recovery)
    Train 2000–2007 → Test 2008  (global financial crisis)
    Train 2000–2010 → Test 2011  (recovery + Euro sovereign crisis)
    Train 2000–2014 → Test 2015  (oil crash / China slowdown)
    Train 2000–2017 → Test 2018  (vol spike / rate fear)
    Train 2000–2020 → Test 2021  (post-COVID bull)
    Train 2000–2021 → Test 2022  (rate-hike bear market)
    Train 2000–2022 → Test 2023
    Train 2000–2023 → Test 2024

Combos are ranked by their AVERAGE out-of-sample performance across all
windows they appeared in — not just one lucky/unlucky year.

Outputs:
    datasets/validation_results.csv   — aggregated survivor table (used by signals.py + bot.py)
    datasets/validation_raw.csv       — raw per-window results for inspection

Usage:
    python3 validate.py
    python3 validate.py --top 20
"""
import argparse
import warnings
import pandas as pd
import vectorbt as vbt
from pathlib import Path
from scipy import stats as scipy_stats

from strategies import STRATEGIES

warnings.filterwarnings("ignore")

CACHE_DIR       = Path("datasets/cache")
OUTPUT_AGG      = Path("datasets/validation_results.csv")
OUTPUT_RAW      = Path("datasets/validation_raw.csv")
TOP_N_IS        = 50
MIN_TRAIN_TRADES = 5
MIN_TEST_TRADES  = 2

# Rolling windows — (train_start, train_end, test_year)
# Expanding training set from 2000; test years chosen to cover distinct regimes.
WINDOWS = [
    ("2000-01-01", "2005-12-31", "2006"),  # post dot-com recovery
    ("2000-01-01", "2007-12-31", "2008"),  # global financial crisis
    ("2000-01-01", "2010-12-31", "2011"),  # recovery + Euro sovereign crisis
    ("2000-01-01", "2014-12-31", "2015"),  # oil crash / China slowdown
    ("2000-01-01", "2017-12-31", "2018"),  # vol spike / rate fear
    ("2000-01-01", "2020-12-31", "2021"),  # post-COVID bull
    ("2000-01-01", "2021-12-31", "2022"),  # rate-hike bear market
    ("2000-01-01", "2022-12-31", "2023"),
    ("2000-01-01", "2023-12-31", "2024"),
]


# ── Data ───────────────────────────────────────────────────────────────────────

def get_tickers() -> list[str]:
    return sorted(f.stem.replace("_prices", "") for f in CACHE_DIR.glob("*_prices.csv"))


def load_all_prices(tickers: list[str]) -> dict[str, pd.Series]:
    """Load all ticker price series once — sliced per window instead of re-read."""
    prices = {}
    for ticker in tickers:
        path = CACHE_DIR / f"{ticker}_prices.csv"
        try:
            df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
            s  = df["Close"].dropna().sort_index()
            if len(s) >= 252:
                prices[ticker] = s
        except Exception:
            pass
    return prices


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(portfolio) -> dict:
    stats = portfolio.stats()
    return {
        "total_return":  round(float(stats.get("Total Return [%]",  0)), 2),
        "sharpe":        round(float(stats.get("Sharpe Ratio",       0)), 3),
        "max_drawdown":  round(abs(float(stats.get("Max Drawdown [%]", 0))), 2),
        "win_rate":      round(float(stats.get("Win Rate [%]",       0)), 1),
        "trade_count":   int(stats.get("Total Trades", 0)),
        "profit_factor": round(float(stats.get("Profit Factor",      0)), 2),
    }


def robustness_score(m: dict) -> float:
    if m["trade_count"] < MIN_TRAIN_TRADES or m["sharpe"] <= 0:
        return 0.0
    pf = min(m["profit_factor"], 10)
    wr = m["win_rate"] / 100
    return round(m["trade_count"] * m["sharpe"] * wr * pf, 2)


def run_strategy(close: pd.Series, name: str) -> dict | None:
    try:
        entries, exits = STRATEGIES[name](close)
        pf = vbt.Portfolio.from_signals(close, entries, exits, freq="1D")
        return compute_metrics(pf)
    except Exception:
        return None


# ── Single window ──────────────────────────────────────────────────────────────

def run_window(prices: dict[str, pd.Series],
               train_start: str, train_end: str, test_year: str) -> list[dict]:
    """Run one IS→OOS window. Returns list of per-combo result dicts."""
    test_start = f"{test_year}-01-01"
    test_end   = f"{test_year}-12-31"

    # ── IS ranking ────────────────────────────────────────────────────────────
    is_rows = []
    for ticker, full in prices.items():
        train = full.loc[train_start:train_end]
        if len(train) < 252:
            continue
        for name in STRATEGIES:
            m = run_strategy(train, name)
            if m is None or m["trade_count"] < MIN_TRAIN_TRADES:
                continue
            score = robustness_score(m)
            if score <= 0:
                continue
            is_rows.append({
                "ticker":        ticker,
                "strategy":      name,
                "is_robustness": score,
                "is_sharpe":     m["sharpe"],
                "is_win_rate":   m["win_rate"],
                "is_trades":     m["trade_count"],
            })

    if not is_rows:
        return []

    is_df  = pd.DataFrame(is_rows).sort_values("is_robustness", ascending=False)
    top_is = is_df.head(TOP_N_IS)

    # ── OOS test ──────────────────────────────────────────────────────────────
    results = []
    total_checked = len(top_is)

    for _, row in top_is.iterrows():
        ticker   = row["ticker"]
        strategy = row["strategy"]
        full     = prices.get(ticker)
        if full is None:
            continue

        test = full.loc[test_start:test_end]
        if len(test) < 30:
            # Too little test data — record as inactive
            results.append({
                "test_year":     test_year,
                "ticker":        ticker,
                "strategy":      strategy,
                "is_robustness": row["is_robustness"],
                "is_sharpe":     row["is_sharpe"],
                "oos_sharpe":    None,
                "oos_win_rate":  None,
                "oos_return":    None,
                "oos_trades":    0,
                "sharpe_decay":  None,
                "oos_profitable":False,
                "active":        False,
            })
            continue

        m = run_strategy(test, strategy)
        if m is None:
            continue

        decay = round(m["sharpe"] / row["is_sharpe"], 3) if row["is_sharpe"] != 0 else 0
        results.append({
            "test_year":     test_year,
            "ticker":        ticker,
            "strategy":      strategy,
            "is_robustness": row["is_robustness"],
            "is_sharpe":     row["is_sharpe"],
            "oos_sharpe":    m["sharpe"],
            "oos_win_rate":  m["win_rate"],
            "oos_return":    m["total_return"],
            "oos_trades":    m["trade_count"],
            "sharpe_decay":  decay,
            "oos_profitable":m["total_return"] > 0,
            "active":        m["trade_count"] >= MIN_TEST_TRADES,
        })

    # Track combos that never fired in test period
    active_count = sum(1 for r in results if r.get("active"))
    print(f"    Active rate: {active_count}/{total_checked} combos traded in {test_year}")
    return results


# ── Aggregation ────────────────────────────────────────────────────────────────

def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-window results into one row per (ticker, strategy)."""
    active = raw[raw["active"] == True]

    if active.empty:
        return pd.DataFrame()

    agg = (
        active.groupby(["ticker", "strategy"])
        .agg(
            windows_tested   = ("test_year", "count"),
            avg_is_robustness= ("is_robustness", "mean"),
            avg_is_sharpe    = ("is_sharpe", "mean"),
            avg_oos_sharpe   = ("oos_sharpe", "mean"),
            avg_oos_win_rate = ("oos_win_rate", "mean"),
            avg_oos_return   = ("oos_return", "mean"),
            avg_oos_trades   = ("oos_trades", "mean"),
            avg_sharpe_decay = ("sharpe_decay", "mean"),
            pct_profitable   = ("oos_profitable", "mean"),
        )
        .round(3)
        .reset_index()
    )

    # Rename to keep downstream (signals.py, bot.py) column names compatible
    agg = agg.rename(columns={
        "avg_oos_sharpe":   "oos_sharpe",
        "avg_sharpe_decay": "sharpe_decay",
        "avg_is_robustness":"is_robustness",
    })
    agg["oos_profitable"] = agg["pct_profitable"] >= 0.5

    return agg.sort_values("oos_sharpe", ascending=False).reset_index(drop=True)


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_report(agg: pd.DataFrame, raw: pd.DataFrame, top_n: int) -> None:
    print("\n" + "=" * 70)
    print("  ROLLING WALK-FORWARD RESULTS")
    print("=" * 70)

    # Active rate per window
    print("\n  ACTIVE RATE PER WINDOW")
    print("  " + "-" * 40)
    for year in raw["test_year"].unique():
        w = raw[raw["test_year"] == year]
        active = w["active"].sum()
        print(f"  {year}:  {active}/{len(w)} combos traded")

    # Filter to combos with enough windows — require ≥3 with 9 available
    eligible = agg[agg["windows_tested"] >= 3]
    survivors = eligible[
        (eligible["oos_sharpe"] > 0.3) &
        (eligible["sharpe_decay"] >= 0.4) &
        (eligible["oos_profitable"] == True)
    ]

    print(f"\n  Combos tested (≥3 windows):  {len(eligible)}")
    print(f"  Survivors (Sharpe>0.3, decay≥0.4, >50% profitable):  {len(survivors)}")

    # Performance transfer
    has_data = eligible[eligible["oos_sharpe"].notna()]
    avg_is  = round(has_data["avg_is_sharpe"].mean(), 3)
    avg_oos = round(has_data["oos_sharpe"].mean(), 3)
    avg_dec = round(has_data["sharpe_decay"].mean(), 3)
    pct_prof= round((has_data["oos_profitable"].mean()) * 100, 1)

    print(f"\n  PERFORMANCE TRANSFER (avg across all windows & combos)")
    print("  " + "-" * 50)
    print(f"  {'Metric':<22} {'In-Sample':>10} {'Out-of-Sample':>14}")
    print(f"  {'-'*22} {'-'*10} {'-'*14}")
    print(f"  {'Avg Sharpe':<22} {avg_is:>10} {avg_oos:>14}")
    print(f"  {'Avg Decay':<22} {'—':>10} {avg_dec:>14}")
    print(f"  {'% Profitable':<22} {'—':>10} {f'{pct_prof}%':>14}")

    # Rank correlation across windows
    corrs = []
    for year in raw["test_year"].unique():
        w = raw[(raw["test_year"] == year) & (raw["active"] == True)].copy()
        if len(w) < 5:
            continue
        w["is_rank"]  = w["is_robustness"].rank(ascending=False)
        w["oos_rank"] = w["oos_sharpe"].rank(ascending=False)
        r, p = scipy_stats.spearmanr(w["is_rank"], w["oos_rank"])
        corrs.append((year, round(r, 3), round(p, 3)))

    print(f"\n  RANK CORRELATION PER WINDOW")
    print("  " + "-" * 40)
    for year, r, p in corrs:
        sig = "✅ significant" if p < 0.05 else "⚠️  not significant"
        print(f"  {year}:  r={r:>6}  p={p:.3f}  {sig}")

    # Verdict
    print(f"\n  VERDICT")
    print("  " + "-" * 50)
    if avg_oos > 0.4 and avg_dec >= 0.4 and pct_prof >= 55:
        v = "✅ EDGE HOLDS     — consistent OOS performance across windows"
    elif avg_oos > 0.1 and pct_prof >= 45:
        v = "⚠️  PARTIAL EDGE  — some decay, proceed cautiously"
    else:
        v = "❌ EDGE WEAK      — significant decay, rebuild before going live"
    print(f"  {v}")

    # Strategy breakdown
    print(f"\n  STRATEGY BREAKDOWN (averaged across all windows)")
    print("  " + "-" * 70)
    print(f"  {'Strategy':<24} {'Windows':>7} {'OOS Shrp':>9} {'OOS WR%':>8} {'Decay':>7} {'% Prof':>7}")
    print(f"  {'-'*24} {'-'*7} {'-'*9} {'-'*8} {'-'*7} {'-'*7}")

    strat = (
        eligible.groupby("strategy")
        .agg(
            windows  =("windows_tested", "sum"),
            oos_sharpe=("oos_sharpe", "mean"),
            oos_wr   =("avg_oos_win_rate", "mean"),
            decay    =("sharpe_decay", "mean"),
            pct_prof =("pct_profitable", "mean"),
        )
        .round(3)
        .sort_values("oos_sharpe", ascending=False)
    )
    for s, r in strat.iterrows():
        print(f"  {s:<24} {int(r['windows']):>7} {r['oos_sharpe']:>9.3f} {r['oos_wr']:>8.1f} {r['decay']:>7.3f} {r['pct_prof']*100:>6.0f}%")

    # Top combos
    print(f"\n  TOP {top_n} COMBOS (by avg OOS Sharpe, ≥3 windows)")
    print("  " + "-" * 75)
    print(f"  {'Ticker':<7} {'Strategy':<24} {'Win':>4} {'IS Shrp':>7} {'OOS Shrp':>9} {'Decay':>7} {'%Prof':>6}")
    print(f"  {'-'*7} {'-'*24} {'-'*4} {'-'*7} {'-'*9} {'-'*7} {'-'*6}")
    for _, r in eligible.head(top_n).iterrows():
        flag = " ⚠️" if r["sharpe_decay"] < 0.3 else ""
        print(f"  {r['ticker']:<7} {r['strategy']:<24} {int(r['windows_tested']):>4} "
              f"{r['avg_is_sharpe']:>7.3f} {r['oos_sharpe']:>9.3f} "
              f"{r['sharpe_decay']:>7.3f} {r['pct_profitable']*100:>5.0f}%{flag}")

    # Survivors
    print(f"\n  SURVIVORS — {len(survivors)} combos passed all OOS filters")
    print("  " + "-" * 55)
    for _, r in survivors.head(15).iterrows():
        print(f"  {r['ticker']:<7} {r['strategy']:<24}  "
              f"OOS={r['oos_sharpe']:.3f}  decay={r['sharpe_decay']:.3f}  "
              f"{int(r['pct_profitable']*100)}% profitable")


# ── Main ───────────────────────────────────────────────────────────────────────

def run(top_n: int = 20) -> None:
    tickers = get_tickers()
    print(f"Rolling Walk-Forward Validation")
    print(f"  {len(WINDOWS)} windows × {len(tickers)} tickers × {len(STRATEGIES)} strategies")
    print(f"  Top {TOP_N_IS} IS combos tested OOS per window")
    print("=" * 70)

    print(f"\nLoading price data for {len(tickers)} tickers...")
    prices = load_all_prices(tickers)
    print(f"  {len(prices)} tickers loaded.\n")

    all_raw = []
    for i, (train_start, train_end, test_year) in enumerate(WINDOWS, 1):
        print(f"[{i}/{len(WINDOWS)}] Train {train_start[:4]}–{train_end[:4]} → Test {test_year}...")
        rows = run_window(prices, train_start, train_end, test_year)
        all_raw.extend(rows)
        print(f"    {len(rows)} combos evaluated.\n")

    raw = pd.DataFrame(all_raw)
    raw.to_csv(OUTPUT_RAW, index=False)
    print(f"Raw results saved → {OUTPUT_RAW}")

    agg = aggregate(raw)
    agg.to_csv(OUTPUT_AGG, index=False)
    print(f"Aggregated results saved → {OUTPUT_AGG}")

    print_report(agg, raw, top_n=top_n)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rolling walk-forward validation")
    parser.add_argument("--top", type=int, default=20, help="Combos to show in output (default: 20)")
    args = parser.parse_args()
    run(top_n=args.top)
