"""
Trade Tracker — detects exits and computes P&L
Runs daily after bot.py. Checks trade_log.csv for OPEN trades,
queries Alpaca for closures (stop loss or signal exit), and updates the log.

Usage:
    python3 tracker.py          # update log + print summary
    python3 tracker.py --summary-only  # skip Alpaca check, just print stats
"""
import argparse
import os
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide

load_dotenv()

API_KEY    = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
PAPER      = True

TRADE_LOG = Path("datasets/trade_log.csv")
FIELDS = [
    "trade_id", "ticker", "strategy", "robustness",
    "entry_date", "entry_price", "qty",
    "exit_date", "exit_price", "pnl_usd", "pnl_pct", "exit_reason", "status",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_log() -> pd.DataFrame:
    if not TRADE_LOG.exists():
        return pd.DataFrame(columns=FIELDS)
    df = pd.read_csv(TRADE_LOG, dtype=str)
    for col in FIELDS:
        if col not in df.columns:
            df[col] = ""
    return df


def save_log(df: pd.DataFrame) -> None:
    df.to_csv(TRADE_LOG, index=False)


def find_exit_order(trading: TradingClient, ticker: str, entry_date: str):
    """
    Search Alpaca closed orders for a SELL-side fill on this ticker
    after the entry date. Returns the best match or None.
    """
    try:
        after_dt = datetime.strptime(entry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        orders = trading.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            symbols=[ticker],
            after=after_dt,
            limit=50,
        ))
        # Filter to filled sell-side orders only
        sells = [
            o for o in orders
            if o.side == OrderSide.SELL
            and o.filled_avg_price is not None
            and float(o.filled_avg_price) > 0
        ]
        if not sells:
            return None
        # Take the most recent fill
        sells.sort(key=lambda o: o.filled_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return sells[0]
    except Exception as e:
        print(f"  Warning: could not query orders for {ticker}: {e}")
        return None


def exit_reason(order) -> str:
    """Determine if exit was a stop loss or a strategy signal."""
    order_type = str(getattr(order, "order_type", "") or "").lower()
    order_class = str(getattr(order, "order_class", "") or "").lower()
    if "stop" in order_type:
        return "stop_loss"
    return "signal"


# ── Core update ────────────────────────────────────────────────────────────────

def update_exits(trading: TradingClient, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Check open trades against Alpaca; fill in exits. Returns updated df and count closed."""
    open_trades = df[df["status"] == "OPEN"]
    if open_trades.empty:
        return df, 0

    # Current open positions on Alpaca
    live_positions = {p.symbol for p in trading.get_all_positions()}

    closed_count = 0
    for idx, row in open_trades.iterrows():
        ticker = row["ticker"]

        # Still open on Alpaca — nothing to do
        if ticker in live_positions:
            continue

        # Not in live positions — find the exit order
        order = find_exit_order(trading, ticker, row["entry_date"])
        if order is None:
            print(f"  {ticker}: not in positions but no exit order found yet — skipping")
            continue

        exit_price  = round(float(order.filled_avg_price), 4)
        entry_price = float(row["entry_price"])
        qty         = int(row["qty"])
        pnl_usd     = round((exit_price - entry_price) * qty, 2)
        pnl_pct     = round((exit_price - entry_price) / entry_price * 100, 2)
        exit_dt     = order.filled_at.strftime("%Y-%m-%d") if order.filled_at else datetime.today().strftime("%Y-%m-%d")
        reason      = exit_reason(order)

        df.at[idx, "exit_date"]   = exit_dt
        df.at[idx, "exit_price"]  = exit_price
        df.at[idx, "pnl_usd"]     = pnl_usd
        df.at[idx, "pnl_pct"]     = pnl_pct
        df.at[idx, "exit_reason"] = reason
        df.at[idx, "status"]      = "CLOSED"

        sign = "+" if pnl_usd >= 0 else ""
        print(f"  {ticker:<6}  closed {exit_dt}  exit=${exit_price}  P&L={sign}${pnl_usd}  ({sign}{pnl_pct}%)  [{reason}]")
        closed_count += 1

    return df, closed_count


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame) -> None:
    closed = df[df["status"] == "CLOSED"].copy()
    open_  = df[df["status"] == "OPEN"]

    print(f"\n{'='*65}")
    print(f"  TRADE TRACKER SUMMARY  |  {datetime.today().strftime('%Y-%m-%d')}")
    print(f"{'='*65}")
    print(f"  Total trades:   {len(df)}  (open: {len(open_)}, closed: {len(closed)})\n")

    if closed.empty:
        print("  No closed trades yet — check back once positions start closing.")
        print()
        if not open_.empty:
            print("  OPEN POSITIONS")
            print("  " + "-" * 55)
            for _, r in open_.iterrows():
                print(f"  {r['ticker']:<6}  {r['strategy']:<24}  entered {r['entry_date']}  @ ${r['entry_price']}")
        return

    closed["pnl_usd"] = closed["pnl_usd"].astype(float)
    closed["pnl_pct"] = closed["pnl_pct"].astype(float)

    winners   = closed[closed["pnl_usd"] > 0]
    losers    = closed[closed["pnl_usd"] <= 0]
    win_rate  = round(len(winners) / len(closed) * 100, 1)
    total_pnl = round(closed["pnl_usd"].sum(), 2)
    avg_win   = round(winners["pnl_usd"].mean(), 2) if not winners.empty else 0
    avg_loss  = round(losers["pnl_usd"].mean(), 2)  if not losers.empty  else 0
    pf_denom  = abs(losers["pnl_usd"].sum())
    profit_factor = round(winners["pnl_usd"].sum() / pf_denom, 2) if pf_denom > 0 else float("inf")

    sign = "+" if total_pnl >= 0 else ""
    print(f"  Total P&L:      {sign}${total_pnl:,.2f}")
    print(f"  Win rate:       {win_rate}%  ({len(winners)}W / {len(losers)}L)")
    print(f"  Profit factor:  {profit_factor}  (>1.3 is good)")
    print(f"  Avg win:        +${avg_win:,.2f}")
    print(f"  Avg loss:       ${avg_loss:,.2f}")

    # Exit reason breakdown
    stop_count   = len(closed[closed["exit_reason"] == "stop_loss"])
    signal_count = len(closed[closed["exit_reason"] == "signal"])
    print(f"\n  Exits via stop loss:  {stop_count}")
    print(f"  Exits via signal:     {signal_count}")

    # Per-strategy breakdown
    if len(closed["strategy"].unique()) > 1:
        print(f"\n  BY STRATEGY")
        print("  " + "-" * 55)
        strat_summary = (
            closed.groupby("strategy")
            .agg(trades=("pnl_usd", "count"), total_pnl=("pnl_usd", "sum"), avg_pnl=("pnl_usd", "mean"))
            .round(2)
            .sort_values("total_pnl", ascending=False)
        )
        for strat, row in strat_summary.iterrows():
            s = "+" if row["total_pnl"] >= 0 else ""
            print(f"  {strat:<24}  {int(row['trades'])} trades  {s}${row['total_pnl']:,.2f}  avg {s}${row['avg_pnl']:,.2f}")

    # Recent closed trades
    print(f"\n  RECENT CLOSED TRADES")
    print("  " + "-" * 55)
    recent = closed.sort_values("exit_date", ascending=False).head(10)
    for _, r in recent.iterrows():
        s = "+" if float(r["pnl_usd"]) >= 0 else ""
        print(f"  {r['ticker']:<6}  {r['strategy']:<22}  {s}${float(r['pnl_usd']):>8,.2f}  ({s}{float(r['pnl_pct'])}%)  [{r['exit_reason']}]")

    # Open positions
    if not open_.empty:
        print(f"\n  OPEN POSITIONS  ({len(open_)})")
        print("  " + "-" * 55)
        for _, r in open_.iterrows():
            print(f"  {r['ticker']:<6}  {r['strategy']:<24}  entered {r['entry_date']}  @ ${r['entry_price']}")

    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def run(summary_only: bool = False) -> None:
    df = load_log()

    if not summary_only:
        open_count = len(df[df["status"] == "OPEN"])
        if open_count == 0:
            print("No open trades in log — nothing to check.")
        else:
            print(f"Checking {open_count} open trade(s) for exits...")
            trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
            df, closed = update_exits(trading, df)
            if closed:
                save_log(df)
                print(f"  {closed} trade(s) closed and logged.\n")
            else:
                print("  No new exits found.\n")

    print_summary(df)

    # Regenerate HTML dashboard after every run
    try:
        from dashboard import generate as generate_dashboard
        generate_dashboard()
    except Exception as e:
        print(f"  Dashboard generation failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track trade P&L")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary without querying Alpaca")
    args = parser.parse_args()
    run(summary_only=args.summary_only)
