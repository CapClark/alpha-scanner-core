"""
Alpha Scanner — Strategy Analysis Engine
Runs every strategy against every cached ticker and ranks results.
"""
import warnings
import pandas as pd
import vectorbt as vbt
from pathlib import Path
from dotenv import load_dotenv

from strategies import STRATEGIES

warnings.filterwarnings("ignore")
load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
CACHE_DIR    = Path("datasets/cache")
RESULTS_FILE = Path("datasets/scan_results.csv")
MIN_TRADES   = 5      # ignore results with too few trades
MIN_DAYS     = 252    # require at least ~1 year of history


# ── Data loading ───────────────────────────────────────────────────────────────

def get_tickers() -> list[str]:
    return sorted(f.stem.replace("_prices", "") for f in CACHE_DIR.glob("*_prices.csv"))


def load_close(ticker: str) -> pd.Series | None:
    path = CACHE_DIR / f"{ticker}_prices.csv"
    try:
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        return df["Close"].dropna()
    except Exception:
        return None


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
    """Composite score: rewards strategies with many trades, high Sharpe, and good win rate."""
    if m["trade_count"] < MIN_TRADES or m["sharpe"] <= 0:
        return 0.0
    pf = min(m["profit_factor"], 10)   # cap outliers
    wr = m["win_rate"] / 100
    return round(m["trade_count"] * m["sharpe"] * wr * pf, 2)


# ── Scanner ────────────────────────────────────────────────────────────────────

def scan_ticker(ticker: str, close: pd.Series) -> list[dict]:
    rows = []
    for name, strategy_fn in STRATEGIES.items():
        try:
            entries, exits = strategy_fn(close)
            pf      = vbt.Portfolio.from_signals(close, entries, exits, freq="1D")
            metrics = compute_metrics(pf)
            if metrics["trade_count"] < MIN_TRADES:
                continue
            rows.append({
                "ticker":           ticker,
                "strategy":         name,
                "robustness_score": robustness_score(metrics),
                **metrics,
            })
        except Exception:
            pass
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("ALPHA SCANNER | Strategy Analysis")
    print("=" * 50)

    tickers = get_tickers()
    print(f"Tickers in cache: {len(tickers)}")
    print(f"Strategies:       {len(STRATEGIES)} ({', '.join(STRATEGIES)})\n")

    all_results = []
    skipped = 0

    for i, ticker in enumerate(tickers, 1):
        close = load_close(ticker)
        if close is None or len(close) < MIN_DAYS:
            skipped += 1
            continue
        all_results.extend(scan_ticker(ticker, close))
        if i % 100 == 0:
            print(f"  {i}/{len(tickers)} tickers scanned...")

    if not all_results:
        print("No results found. Check that datasets/cache/ has price CSVs.")
        return

    df = (
        pd.DataFrame(all_results)
        .sort_values("robustness_score", ascending=False)
        .reset_index(drop=True)
    )

    df.to_csv(RESULTS_FILE, index=False)

    print(f"\nDone. {len(tickers) - skipped} tickers scanned, {skipped} skipped (< {MIN_DAYS} days).")
    print(f"{len(df)} qualifying results saved -> {RESULTS_FILE}\n")

    # ── Top combinations ───────────────────────────────────────────────────────
    cols = ["ticker", "strategy", "robustness_score", "total_return", "sharpe", "win_rate", "trade_count"]
    print("TOP 20 STRATEGY-TICKER COMBINATIONS")
    print("-" * 80)
    print(df[cols].head(20).to_string(index=False))

    # ── Strategy summary ───────────────────────────────────────────────────────
    print("\nSTRATEGY AVERAGES (across all qualifying tickers)")
    print("-" * 60)
    summary = (
        df.groupby("strategy")[["robustness_score", "total_return", "sharpe", "win_rate", "trade_count"]]
        .mean()
        .round(2)
        .sort_values("robustness_score", ascending=False)
    )
    print(summary.to_string())

    # ── Best ticker per strategy ───────────────────────────────────────────────
    print("\nBEST TICKER PER STRATEGY")
    print("-" * 60)
    best = df.loc[df.groupby("strategy")["robustness_score"].idxmax()]
    print(best[cols].sort_values("robustness_score", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
