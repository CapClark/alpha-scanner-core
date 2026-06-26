"""
Trading Bot — Alpaca Paper Trading
Reads today's signals and executes orders.

Rules:
  - $1,000 per position
  - 5% stop loss on every entry (OTO order)
  - Max 10 open positions at once
  - BUY signals → open position (if slot available + not already held)
  - SELL signals → close position (if currently held)

Usage:
    python3 bot.py            # run normally
    python3 bot.py --dry-run  # print actions without placing orders
"""
import argparse
import os
import csv
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

from signals import run as get_signals_output
import signals as sig

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY      = os.getenv("ALPACA_API_KEY")
SECRET_KEY   = os.getenv("ALPACA_SECRET_KEY")
PAPER        = True          # always paper until you change this

POSITION_SIZE  = 10_000      # USD per trade
STOP_LOSS_PCT  = 0.05        # 5% stop loss
MAX_POSITIONS  = 10          # max open positions at once
MIN_ROBUSTNESS = 50          # only act on signals above this score
TOP_N          = 50          # watchlist size (matches signals.py default)
TRADE_LOG      = Path("datasets/trade_log.csv")

TRADE_LOG_FIELDS = [
    "trade_id", "ticker", "strategy", "robustness",
    "entry_date", "entry_price", "qty",
    "exit_date", "exit_price", "pnl_usd", "pnl_pct", "exit_reason", "status",
]


# ── Alpaca clients ─────────────────────────────────────────────────────────────

def get_clients():
    trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    data    = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    return trading, data


# ── Account info ───────────────────────────────────────────────────────────────

def get_open_positions(trading: TradingClient) -> dict[str, object]:
    """Return {ticker: position} for all currently open positions."""
    positions = trading.get_all_positions()
    return {p.symbol: p for p in positions}


def get_account_summary(trading: TradingClient) -> dict:
    acct = trading.get_account()
    return {
        "equity":        float(acct.equity),
        "cash":          float(acct.cash),
        "buying_power":  float(acct.buying_power),
    }


# ── Price lookup ───────────────────────────────────────────────────────────────

def get_latest_price(data: StockHistoricalDataClient, ticker: str) -> float | None:
    """Use last trade price — matches Alpaca's base_price for OTO stop orders."""
    try:
        req   = StockLatestTradeRequest(symbol_or_symbols=ticker)
        trade = data.get_stock_latest_trade(req)
        price = float(trade[ticker].price)
        return price if price > 0 else None
    except Exception as e:
        print(f"  Price lookup failed for {ticker}: {e}")
        return None


# ── Trade log ──────────────────────────────────────────────────────────────────

def log_trade_entry(ticker: str, strategy: str, robustness: float,
                    entry_price: float, qty: int) -> None:
    """Append a new OPEN trade to trade_log.csv."""
    is_new = not TRADE_LOG.exists()
    trade_id = datetime.today().strftime("%Y%m%d") + f"_{ticker}"
    row = {
        "trade_id":    trade_id,
        "ticker":      ticker,
        "strategy":    strategy,
        "robustness":  round(robustness, 2),
        "entry_date":  datetime.today().strftime("%Y-%m-%d"),
        "entry_price": round(entry_price, 4),
        "qty":         qty,
        "exit_date":   "",
        "exit_price":  "",
        "pnl_usd":     "",
        "pnl_pct":     "",
        "exit_reason": "",
        "status":      "OPEN",
    }
    with open(TRADE_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    print(f"  Logged entry → trade_log.csv  ({trade_id})")


# ── Order execution ────────────────────────────────────────────────────────────

def place_buy(trading: TradingClient, data: StockHistoricalDataClient,
              ticker: str, strategy: str, robustness: float,
              dry_run: bool = False) -> bool:
    price = get_latest_price(data, ticker)
    if price is None:
        print(f"  SKIP {ticker} — could not get price")
        return False

    qty        = max(1, int(POSITION_SIZE / price))
    stop_price = round(price * (1 - STOP_LOSS_PCT), 2)
    cost       = round(qty * price, 2)

    print(f"  BUY  {ticker:<6}  qty={qty}  ~${cost}  stop=${stop_price}  (price~${price:.2f})")

    if dry_run:
        return True

    try:
        # OTO (one-triggers-other): marketable-limit entry + stop loss only.
        # GTC so the stop leg PERSISTS across days. Market orders can't be GTC on
        # Alpaca, so a limit a hair (0.5%) above price fills like a market order
        # while keeping the protective stop alive (a DAY OTO expires the stop at
        # the close of the entry day, leaving the position naked from day 2).
        limit_entry = round(price * 1.005, 2)
        order = LimitOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY,
            limit_price=limit_entry,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OTO,
            stop_loss=StopLossRequest(stop_price=stop_price),
        )
        trading.submit_order(order)
        log_trade_entry(ticker, strategy, robustness, price, qty)
        return True
    except Exception as e:
        print(f"  ERROR placing BUY for {ticker}: {e}")
        return False


def place_sell(trading: TradingClient, ticker: str,
               qty: str, dry_run: bool = False) -> bool:
    print(f"  SELL {ticker:<6}  qty={qty}  (closing position)")

    if dry_run:
        return True

    try:
        trading.close_position(ticker)
        return True
    except Exception as e:
        print(f"  ERROR closing {ticker}: {e}")
        return False


# ── Signal reader ──────────────────────────────────────────────────────────────

def read_signals(top_n: int = TOP_N) -> tuple[list[dict], list[dict]]:
    """Return (buy_signals, sell_signals) using validated watchlist if available."""
    import pandas as pd
    from pathlib import Path

    # RSI(21) confirmed negative OOS — always excluded
    EXCLUDED = {"RSI(21)"}

    validation_file = Path("datasets/validation_results.csv")
    results_file    = Path("datasets/scan_results.csv")

    if validation_file.exists():
        val = pd.read_csv(validation_file)
        watchlist = val[
            (val["oos_sharpe"]     >= 0.3) &
            (val["sharpe_decay"]   >= 0.4) &
            (val["oos_profitable"] == True) &
            (val["windows_tested"] >= 3) &
            (~val["strategy"].isin(EXCLUDED))
        ].sort_values("oos_sharpe", ascending=False).head(top_n).reset_index(drop=True)
        score_col = "oos_sharpe"
        min_score = 0.3
    elif results_file.exists():
        scan = pd.read_csv(results_file)
        watchlist = scan[
            ~scan["strategy"].isin(EXCLUDED)
        ].nlargest(top_n, "robustness_score").reset_index(drop=True)
        score_col = "robustness_score"
        min_score = MIN_ROBUSTNESS
    else:
        return [], []

    buys  = []
    sells = []

    for _, item in watchlist.iterrows():
        if float(item[score_col]) < min_score:
            continue

        ticker   = item["ticker"]
        strategy = item["strategy"]
        close    = sig.load_close(ticker)
        if close is None or len(close) < 252:
            continue

        signal = sig.check_signal(close, strategy)
        if signal == "BUY":
            buys.append({"ticker": ticker, "strategy": strategy,
                         "robustness": float(item[score_col])})
        elif signal == "SELL":
            sells.append({"ticker": ticker, "strategy": strategy,
                          "robustness": float(item[score_col])})

    # Deduplicate tickers (a ticker may appear via multiple strategies)
    seen = set()
    buys  = [b for b in buys  if not (b["ticker"] in seen or seen.add(b["ticker"]))]
    seen  = set()
    sells = [s for s in sells if not (s["ticker"] in seen or seen.add(s["ticker"]))]

    # Regime filter — suppress BUY entries when SPY is below its 200-day MA
    regime_ok, spy_price, spy_ma200 = sig.get_regime()
    if not regime_ok:
        print(f"  ⚠️  Regime filter: SPY ${spy_price:.2f} < 200-day MA ${spy_ma200:.2f} — {len(buys)} BUY(s) suppressed")
        buys = []

    return buys, sells


# ── Main ───────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    label = " [DRY RUN]" if dry_run else ""
    print(f"TRADING BOT{label}  |  {datetime.today().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    trading, data = get_clients()

    # Account summary
    acct = get_account_summary(trading)
    print(f"  Equity: ${acct['equity']:,.2f}  |  Cash: ${acct['cash']:,.2f}  |  Buying power: ${acct['buying_power']:,.2f}\n")

    # Current positions
    positions = get_open_positions(trading)
    print(f"  Open positions: {len(positions)}/{MAX_POSITIONS}  →  {list(positions.keys()) or 'none'}\n")

    # Read signals
    print("Reading signals...")
    buys, sells = read_signals()
    print(f"  {len(buys)} BUY signal(s)  |  {len(sells)} SELL signal(s)\n")

    # ── Execute SELLs first (free up slots) ────────────────────────────────────
    if sells:
        print("CLOSING POSITIONS (sell signals):")
        for s in sells:
            ticker = s["ticker"]
            if ticker in positions:
                place_sell(trading, ticker, positions[ticker].qty, dry_run)
            else:
                print(f"  SKIP {ticker:<6} — not currently held")
        print()

    # ── Execute BUYs ───────────────────────────────────────────────────────────
    # Refresh positions after sells
    positions = get_open_positions(trading)
    slots_available = MAX_POSITIONS - len(positions)

    if buys:
        print(f"OPENING POSITIONS (buy signals, {slots_available} slot(s) available):")
        opened = 0
        for b in buys:
            if opened >= slots_available:
                print(f"  SKIP {b['ticker']:<6} — max positions reached")
                continue
            if b["ticker"] in positions:
                print(f"  SKIP {b['ticker']:<6} — already held")
                continue
            if acct["buying_power"] < POSITION_SIZE:
                print(f"  SKIP {b['ticker']:<6} — insufficient buying power")
                continue
            success = place_buy(trading, data, b["ticker"], b["strategy"], b["robustness"], dry_run)
            if success:
                opened += 1
        print()

    # ── Summary ────────────────────────────────────────────────────────────────
    if not buys and not sells:
        print("No actionable signals today. Nothing to do.")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alpaca paper trading bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned orders without executing them")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
