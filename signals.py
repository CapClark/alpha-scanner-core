"""
Daily Signal Generator
Checks today's entry/exit signals on the top strategy-ticker combinations
from the last backtest scan. Run every morning before market open.

Watchlist priority:
  1. datasets/validation_results.csv  — walk-forward validated survivors (preferred)
  2. datasets/scan_results.csv        — in-sample rankings (fallback if validate.py not run)

Usage:
    python3 signals.py              # check top 50 combinations
    python3 signals.py --top 100    # check top 100
"""
import argparse
import warnings
import pandas as pd
import vectorbt as vbt
from pathlib import Path
from datetime import datetime

from strategies import STRATEGIES

warnings.filterwarnings("ignore")

CACHE_DIR        = Path("datasets/cache")
RESULTS_FILE     = Path("datasets/scan_results.csv")
VALIDATION_FILE  = Path("datasets/validation_results.csv")
LOOKBACK         = 3    # bars to look back for a fresh signal

# RSI(21) excluded — negative OOS Sharpe across all rolling windows
EXCLUDED_STRATEGIES = {"RSI(21)"}

# Survivor thresholds (must meet all three to be on the validated watchlist)
OOS_SHARPE_MIN   = 0.3
DECAY_MIN        = 0.4
MIN_WINDOWS      = 3     # combo must have appeared in at least 3 IS windows


# ── Data ───────────────────────────────────────────────────────────────────────

def load_close(ticker: str) -> pd.Series | None:
    path = CACHE_DIR / f"{ticker}_prices.csv"
    try:
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        return df["Close"].dropna()
    except Exception:
        return None


# ── Regime filter ─────────────────────────────────────────────────────────────

def get_regime() -> tuple[bool, float, float]:
    """
    Returns (is_healthy, spy_price, spy_200ma).
    Healthy = SPY above its 200-day MA → allow new BUY entries.
    Bearish = SPY below 200-day MA → suppress all new BUY signals.
    Fails open (returns True) if SPY data is unavailable.
    """
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period="2y", auto_adjust=True)["Close"].dropna()
        spy.index = spy.index.tz_localize(None)
        if len(spy) < 200:
            return True, float("nan"), float("nan")
        ma200 = float(spy.rolling(200).mean().iloc[-1])
        price = float(spy.iloc[-1])
        return price > ma200, price, ma200
    except Exception:
        return True, float("nan"), float("nan")


# ── Signal detection ───────────────────────────────────────────────────────────

def check_signal(close: pd.Series, strategy_name: str) -> str:
    """Return BUY, SELL, or HOLD based on the last LOOKBACK bars."""
    try:
        entries, exits = STRATEGIES[strategy_name](close)
        if entries.iloc[-LOOKBACK:].any():
            return "BUY"
        if exits.iloc[-LOOKBACK:].any():
            return "SELL"
        return "HOLD"
    except Exception:
        return "ERROR"


def get_indicator(close: pd.Series, strategy_name: str) -> str:
    """Return a human-readable indicator snapshot for context."""
    try:
        if "RSI" in strategy_name:
            window = 21 if "21" in strategy_name else 14
            rsi    = vbt.RSI.run(close, window=window)
            val    = round(float(rsi.rsi.iloc[-1]), 1)
            note   = " ← oversold" if val < 30 else (" ← overbought" if val > 70 else "")
            return f"RSI({window})={val}{note}"

        if "BBands" in strategy_name:
            bb    = vbt.BBANDS.run(close, window=20, alpha=2.0)
            price = float(close.iloc[-1])
            lower = float(bb.lower.iloc[-1])
            upper = float(bb.upper.iloc[-1])
            mid   = float(bb.middle.iloc[-1])
            if price < lower:
                return f"Price={price:.2f} below lower BB={lower:.2f}"
            if price > upper:
                return f"Price={price:.2f} above upper BB={upper:.2f}"
            pct = round((price - lower) / (upper - lower) * 100)
            return f"BB position={pct}% (0=lower, 100=upper)"

        if "MACD" in strategy_name:
            macd = vbt.MACD.run(close)
            diff = float(macd.macd.iloc[-1]) - float(macd.signal.iloc[-1])
            return f"MACD-Signal={diff:+.4f}"

        if "MA Cross" in strategy_name:
            fast = vbt.MA.run(close, window=50,  short_name="fast")
            slow = vbt.MA.run(close, window=200, short_name="slow")
            pct  = (float(fast.ma.iloc[-1]) / float(slow.ma.iloc[-1]) - 1) * 100
            return f"50MA vs 200MA={pct:+.2f}%"

    except Exception:
        pass
    return ""


# ── Watchlist loader ───────────────────────────────────────────────────────────

def load_watchlist(top_n: int) -> tuple[pd.DataFrame, str]:
    """
    Load the signal watchlist. Prefers walk-forward validated survivors;
    falls back to in-sample scan_results if validation hasn't been run.
    Returns (watchlist_df, source_label).
    """
    if VALIDATION_FILE.exists():
        val = pd.read_csv(VALIDATION_FILE)
        survivors = val[
            (val["oos_sharpe"]     >= OOS_SHARPE_MIN) &
            (val["sharpe_decay"]   >= DECAY_MIN) &
            (val["oos_profitable"] == True) &
            (val["windows_tested"] >= MIN_WINDOWS) &
            (~val["strategy"].isin(EXCLUDED_STRATEGIES))
        ].sort_values("oos_sharpe", ascending=False).head(top_n).reset_index(drop=True)
        return survivors, f"validated ({len(survivors)} survivors, ranked by OOS Sharpe)"

    if RESULTS_FILE.exists():
        scan = pd.read_csv(RESULTS_FILE)
        wl = scan[
            ~scan["strategy"].isin(EXCLUDED_STRATEGIES)
        ].nlargest(top_n, "robustness_score").reset_index(drop=True)
        return wl, f"in-sample scan_results (run validate.py for better rankings)"

    return pd.DataFrame(), "none"


# ── Main ───────────────────────────────────────────────────────────────────────

def run(top_n: int = 50) -> None:
    today = datetime.today().strftime("%Y-%m-%d")
    print(f"SIGNAL GENERATOR  |  {today}")
    print("=" * 65)

    watchlist, source = load_watchlist(top_n)
    if watchlist.empty:
        print("No scan_results.csv or validation_results.csv found.")
        print("Run  python3 main.py  then  python3 validate.py  first.")
        return
    print(f"Watchlist: {source}")

    # ── Regime check ───────────────────────────────────────────────────────────
    regime_ok, spy_price, spy_ma200 = get_regime()
    import math
    if not math.isnan(spy_price):
        status = "HEALTHY ▲" if regime_ok else "BEARISH ▼"
        print(f"  Market regime: {status}  |  SPY ${spy_price:.2f}  vs  200-day MA ${spy_ma200:.2f}")
        if not regime_ok:
            print(f"  ⚠️  SPY below 200-day MA — new BUY entries suppressed")
    else:
        print(f"  Market regime: UNKNOWN (SPY data unavailable — proceeding with BUY signals)")
    print()

    # Use oos_sharpe if validated, else is_robustness/robustness_score
    score_col = "oos_sharpe" if "oos_sharpe" in watchlist.columns else "robustness_score"

    rows = []
    for _, item in watchlist.iterrows():
        ticker   = item["ticker"]
        strategy = item["strategy"]

        close = load_close(ticker)
        if close is None or len(close) < 252:
            continue

        signal    = check_signal(close, strategy)
        indicator = get_indicator(close, strategy)
        price     = round(float(close.iloc[-1]), 2)
        as_of     = close.index[-1].strftime("%Y-%m-%d")

        rows.append({
            "ticker":    ticker,
            "strategy":  strategy,
            "signal":    signal,
            "price":     price,
            "indicator": indicator,
            "as_of":     as_of,
            "score":     float(item[score_col]),
        })

    df = pd.DataFrame(rows)

    # ── BUY signals ────────────────────────────────────────────────────────────
    buys = df[df["signal"] == "BUY"].sort_values("score", ascending=False)
    if not regime_ok:
        print(f"  BUY SIGNALS  (0 actionable — {len(buys)} suppressed by bearish regime)")
        print("  " + "-" * 63)
        for _, r in buys.iterrows():
            print(f"  {r['ticker']:<6}  {r['strategy']:<22}  ${r['price']:<8}  [SUPPRESSED — bearish regime]")
        if buys.empty:
            print("  No buy signals today.")
        print()
    else:
        print(f"  BUY SIGNALS  ({len(buys)} found)")
        print("  " + "-" * 63)
        if buys.empty:
            print("  No buy signals today.\n")
        else:
            for _, r in buys.iterrows():
                print(f"  {r['ticker']:<6}  {r['strategy']:<22}  ${r['price']:<8}  {r['indicator']}")
            print()

    # ── SELL signals ───────────────────────────────────────────────────────────
    sells = df[df["signal"] == "SELL"].sort_values("score", ascending=False)
    print(f"  SELL SIGNALS  ({len(sells)} found)")
    print("  " + "-" * 63)
    if sells.empty:
        print("  No sell signals today.\n")
    else:
        for _, r in sells.iterrows():
            print(f"  {r['ticker']:<6}  {r['strategy']:<22}  ${r['price']:<8}  {r['indicator']}")
        print()

    # ── Summary ────────────────────────────────────────────────────────────────
    holds = df[df["signal"] == "HOLD"]
    print(f"  HOLD  {len(holds)} positions — no signal today")
    print(f"  Data as of: {df['as_of'].max()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate today's trading signals")
    parser.add_argument("--top", type=int, default=50, help="How many top combinations to monitor (default: 50)")
    args = parser.parse_args()

    run(top_n=args.top)
