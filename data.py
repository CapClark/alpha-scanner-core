"""
Data fetcher — WRDS/CRSP (history) + yfinance (recent top-up)

Two modes:
  python3 data.py            → full CRSP download from START_DATE
  python3 data.py --topup    → yfinance top-up only (fills gap from last cached date to today)

Other options:
  --tickers AAPL NVDA        → specific tickers only
  --start 2010-01-01         → custom start date (full mode only)
"""
import argparse
import getpass
import os
import sys
import time
import warnings
import psycopg2
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

CACHE_DIR  = Path("datasets/cache")
START_DATE = "2000-01-01"
BATCH_SIZE = 100

WRDS_HOST = "wrds-pgdata.wharton.upenn.edu"
WRDS_PORT = 9737
WRDS_DB   = "wrds"
WRDS_USER = "ksugsvanvit"


# ── WRDS connection ────────────────────────────────────────────────────────────

class WRDSConnection:
    def __init__(self):
        password = getpass.getpass("WRDS password: ")
        print("Connecting to WRDS...")
        self._conn = psycopg2.connect(
            host=WRDS_HOST, port=WRDS_PORT, dbname=WRDS_DB,
            user=WRDS_USER, password=password,
            sslmode="require", connect_timeout=30,
        )
        print("Connected.\n")

    def raw_sql(self, query: str, date_cols: list[str] | None = None) -> pd.DataFrame:
        cur = self._conn.cursor()
        cur.execute(query)
        cols = [desc[0] for desc in cur.description]
        df   = pd.DataFrame(cur.fetchall(), columns=cols)
        if date_cols:
            for col in date_cols:
                df[col] = pd.to_datetime(df[col])
        return df

    def close(self):
        self._conn.close()


# ── Cache helpers ──────────────────────────────────────────────────────────────

def get_cached_tickers() -> list[str]:
    return sorted(f.stem.replace("_prices", "") for f in CACHE_DIR.glob("*_prices.csv"))


def load_cache(ticker: str) -> pd.Series | None:
    path = CACHE_DIR / f"{ticker}_prices.csv"
    try:
        df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
        return df["Close"].dropna().sort_index()
    except Exception:
        return None


def save_to_cache(ticker: str, series: pd.Series) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{ticker}_prices.csv"
    # Atomic write: a crash mid-write must not leave a truncated CSV that later
    # loads as "no data" and silently drops the ticker from signals.
    tmp = path.with_suffix(".csv.tmp")
    series.to_frame("Close").to_csv(tmp, index_label="timestamp")
    os.replace(tmp, path)


# ── CRSP helpers ───────────────────────────────────────────────────────────────

def tickers_to_permnos(db: WRDSConnection, tickers: list[str]) -> dict[str, int]:
    ticker_list = ", ".join(f"'{t.upper()}'" for t in tickers)
    df = db.raw_sql(f"""
        SELECT DISTINCT ON (ticker) ticker, permno
        FROM   crsp.msenames
        WHERE  ticker IN ({ticker_list})
        ORDER  BY ticker, nameendt DESC NULLS FIRST
    """)
    return dict(zip(df["ticker"], df["permno"].astype(int)))


def fetch_crsp_prices(db: WRDSConnection, permnos: list[int], start_date: str) -> pd.DataFrame:
    results       = []
    total_batches = -(-len(permnos) // BATCH_SIZE)
    for i in range(0, len(permnos), BATCH_SIZE):
        batch      = permnos[i : i + BATCH_SIZE]
        permno_str = ", ".join(str(p) for p in batch)
        chunk = db.raw_sql(f"""
            SELECT permno, date,
                   abs(prc) / NULLIF(cfacpr, 0) AS close
            FROM   crsp.dsf
            WHERE  permno IN ({permno_str})
              AND  date   >= '{start_date}'
              AND  prc    IS NOT NULL
              AND  cfacpr  > 0
            ORDER  BY permno, date
        """, date_cols=["date"])
        results.append(chunk)
        print(f"  CRSP batch {i // BATCH_SIZE + 1}/{total_batches}  ({len(batch)} stocks)")
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


# ── yfinance top-up ────────────────────────────────────────────────────────────

def yf_fetch(ticker: str, start_date: str) -> pd.Series | None:
    try:
        raw = yf.Ticker(ticker).history(start=start_date, auto_adjust=True)
        if raw.empty or "Close" not in raw.columns:
            return None
        series = raw["Close"].dropna()
        series.index = series.index.tz_localize(None)
        return series if len(series) > 0 else None
    except Exception:
        return None


def split_since(ticker: str, last_date) -> bool:
    """True if yfinance records a share split AFTER last_date.

    A split in the top-up gap is the one case incremental splicing corrupts: the
    freshly fetched bars are auto-adjusted to today's basis, but the old cached
    bars are not, so concatenating them leaves a split-ratio cliff at the seam
    (e.g. OTLY 1:20 reverse split -> a fake +1,900% bar). When this is true the
    caller must re-pull the FULL history instead of splicing.
    """
    try:
        sp = yf.Ticker(ticker).splits
        if sp is None or len(sp) == 0:
            return False
        idx = sp.index.tz_localize(None)
        return bool((idx > pd.Timestamp(last_date)).any())
    except Exception:
        return False


def topup(tickers: list[str] | None = None) -> tuple[int, int]:
    """Fill the gap between last cached date and today using yfinance.

    Returns (updated, attempted). `attempted` counts tickers that genuinely
    needed a fetch (excludes already-current ones), so the caller can tell a
    total data-feed outage (attempted>0, updated==0) apart from a quiet
    everything-already-current run (attempted==0).
    """
    universe = tickers if tickers else get_cached_tickers()
    today    = datetime.today().date()
    updated   = 0
    attempted = 0

    print(f"Top-up: filling gap to {today} for {len(universe)} tickers via yfinance...\n")

    for i, ticker in enumerate(universe, 1):
        cached = load_cache(ticker)

        if cached is not None and len(cached) > 0:
            last_date = cached.index[-1].date()
            if last_date >= today - timedelta(days=1):
                continue                              # already up to date
            # Guard: a split in the gap makes incremental splicing corrupt the
            # series (seam cliff). Re-pull full auto-adjusted history instead.
            if split_since(ticker, last_date):
                attempted += 1
                full = yf_fetch(ticker, START_DATE)
                if full is not None and len(full) > 0:
                    save_to_cache(ticker, full)
                    updated += 1
                    print(f"  {ticker}: split in gap -> full re-pull ({len(full)} bars)")
                    time.sleep(0.05)
                continue
            fetch_from = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            fetch_from = START_DATE

        attempted += 1
        new_data = yf_fetch(ticker, fetch_from)
        if new_data is None or new_data.empty:
            continue

        if cached is not None:
            merged = pd.concat([cached, new_data])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        else:
            merged = new_data

        save_to_cache(ticker, merged)
        updated += 1
        time.sleep(0.05)

        if i % 50 == 0:
            print(f"  [{i}/{len(universe)}]  {updated} tickers updated so far")

    print(f"\nTop-up done. {updated} tickers extended to {today}.")
    return updated, attempted


# ── Full CRSP refresh ──────────────────────────────────────────────────────────

def refresh(tickers: list[str] | None = None, start_date: str = START_DATE) -> None:
    db = WRDSConnection()
    try:
        universe = tickers if tickers else get_cached_tickers()
        print(f"Resolving {len(universe)} tickers to PERMNOs...")
        ticker_permno = tickers_to_permnos(db, universe)
        permno_ticker = {v: k for k, v in ticker_permno.items()}

        missing = [t for t in universe if t.upper() not in ticker_permno]
        if missing:
            print(f"  No CRSP record for {len(missing)} tickers: {missing[:10]}{'...' if len(missing) > 10 else ''}")
        print(f"  {len(permno_ticker)} tickers mapped\n")

        permnos = list(permno_ticker.keys())
        print(f"Pulling CRSP prices from {start_date} for {len(permnos)} stocks...")
        prices = fetch_crsp_prices(db, permnos, start_date)

        if prices.empty:
            print("No data returned.")
            return

        saved = 0
        for permno, group in prices.groupby("permno"):
            ticker = permno_ticker.get(int(permno))
            if not ticker:
                continue
            series = group.set_index("date")["close"].dropna().sort_index()
            save_to_cache(ticker, series)
            saved += 1

        print(f"\nCRSP download done. {saved} tickers saved.")

    finally:
        db.close()

    # Automatically top up with yfinance for the recent gap
    print()
    topup(tickers=tickers)
    print("\nRun  python3 main.py  to re-scan with the updated data.")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh price cache")
    parser.add_argument("--topup",   action="store_true", help="yfinance top-up only (no CRSP download)")
    parser.add_argument("--tickers", nargs="+",           help="Specific tickers (default: all cached)")
    parser.add_argument("--start",   default=START_DATE,  help=f"Start date for full refresh (default: {START_DATE})")
    args = parser.parse_args()

    if args.topup:
        updated, attempted = topup(tickers=args.tickers)
        # Fail loud on a total data-feed outage so run_daily.sh marks the run
        # FAILED instead of letting the bot trade on stale prices under a green
        # heartbeat. attempted==0 means everything was already current (fine).
        if attempted > 0 and updated == 0:
            print(f"ERROR: top-up attempted {attempted} tickers but updated 0 - "
                  f"yfinance feed likely down. Failing loud.", file=sys.stderr)
            sys.exit(1)
    else:
        refresh(tickers=args.tickers, start_date=args.start)
