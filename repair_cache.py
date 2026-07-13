"""One-shot price-cache repair — removes split-adjustment discontinuities left by
the old incremental yfinance top-up.

Background: the pre-guard top-up spliced fresh auto-adjusted bars onto the older
CRSP-basis series without re-adjusting for splits in the gap, leaving a split-
ratio cliff at the seam (e.g. OTLY's 1:20 reverse split showed as a +1,900% bar).
data.py now guards against this going forward (split_since); this script cleans
series already corrupted on a host.

It scans each cached series for a split-like cliff AFTER the CRSP pull end (the
only region the buggy top-up could touch — earlier bars are CRSP-adjusted and
correct), and re-pulls the full auto-adjusted history for any hit. The fresh pull
is split-continuous by construction, so genuine large moves (earnings crashes,
biotech pops) are preserved while artifacts vanish. Idempotent: re-pulling an
already-clean name is a harmless no-op.

  python3 repair_cache.py             # scan + repair
  python3 repair_cache.py --dry-run   # list suspects only, change nothing
  python3 repair_cache.py --crsp-end 2024-12-31
"""
import argparse
import time

import pandas as pd

from data import CACHE_DIR, START_DATE, get_cached_tickers, save_to_cache, yf_fetch

# Common split ratios a corrupt seam snaps to; real intraday moves rarely land
# this cleanly, and the permanence check below filters the ones that do.
FACTORS = [1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30]
TOL = 0.04
REVERT_WIN = 5


def _near_factor(ratio: float) -> bool:
    for f in FACTORS:
        if abs(ratio - f) / f < TOL or abs(ratio - 1 / f) / (1 / f) < TOL:
            return True
    return ratio > 1.6 or ratio < 0.625        # >60% up / >37.5% down in one day


def find_break(series: pd.Series, crsp_end: pd.Timestamp) -> str | None:
    """Return a description of the first post-crsp_end split-like cliff, else None.

    A cliff is a single-day ratio near a split factor whose level shift persists
    (median before vs after), distinguishing a permanent basis break from a spike.
    """
    r = series / series.shift(1)
    for dt, ratio in r.items():
        if pd.isna(ratio) or ratio <= 0 or dt <= crsp_end:
            continue
        if not _near_factor(ratio):
            continue
        i = series.index.get_loc(dt)
        if i < 3 or i > len(series) - 2:
            continue
        before = series.iloc[max(0, i - REVERT_WIN):i].median()
        after = series.iloc[i:i + REVERT_WIN].median()
        if before and _near_factor(after / before):
            return f"{dt.date()} ratio={ratio:.3f}"
    return None


def repair(tickers: list[str] | None, crsp_end: pd.Timestamp, dry_run: bool) -> None:
    universe = tickers if tickers else get_cached_tickers()
    suspects: list[tuple[str, str]] = []

    for t in universe:
        path = CACHE_DIR / f"{t}_prices.csv"
        try:
            s = pd.read_csv(path, index_col="timestamp", parse_dates=True)["Close"].dropna().sort_index()
        except Exception:
            continue
        if len(s) < 20:
            continue
        brk = find_break(s, crsp_end)
        if brk:
            suspects.append((t, brk))

    print(f"Scanned {len(universe)} tickers — {len(suspects)} with a post-{crsp_end.date()} split cliff.")
    for t, brk in suspects:
        print(f"  {t:8} {brk}")

    if dry_run:
        print("\n--dry-run: nothing changed.")
        return
    if not suspects:
        print("Cache is clean.")
        return

    print(f"\nRe-pulling {len(suspects)} tickers full auto-adjusted history...")
    fixed = 0
    for t, _ in suspects:
        full = yf_fetch(t, START_DATE)
        if full is None or len(full) < 100:
            print(f"  {t}: re-pull failed (kept as-is)")
            continue
        save_to_cache(t, full)
        fixed += 1
        residual = find_break(full, crsp_end)
        note = f"  [real move preserved: {residual}]" if residual else ""
        print(f"  {t}: {len(full)} bars{note}")
        time.sleep(0.15)

    print(f"\nRepaired {fixed}/{len(suspects)}.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Repair split-corrupted price cache series")
    p.add_argument("--tickers", nargs="+", help="Specific tickers (default: all cached)")
    p.add_argument("--crsp-end", default="2024-12-31", help="CRSP pull end; only scan after this date")
    p.add_argument("--dry-run", action="store_true", help="List suspects only, change nothing")
    args = p.parse_args()
    repair(args.tickers, pd.Timestamp(args.crsp_end), args.dry_run)
