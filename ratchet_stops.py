#!/usr/bin/env python3
"""Ratcheting ATR trail — raise stops as positions gain, never lower them.

Why: the fixed 5% stop lives 5% below ENTRY forever. A position up 40% (LLY) is
still "protected" at entry-5% — i.e. nearly the whole open gain is unbanked. This
job trails each position's stop up to (last_close - K*ATR14) whenever that is
higher than the current stop. Stops only move UP (ratchet), so it can never widen
risk. Runs daily after guard_stops.py (which guarantees a stop exists to raise).

  python3 ratchet_stops.py            # raise stops for real
  python3 ratchet_stops.py --dry-run  # print what would change
"""
import os
import sys

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, ReplaceOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

load_dotenv()

ATR_LEN   = 14
ATR_MULT  = 2.5          # stop trails at close - 2.5*ATR (loose enough for swing noise)
MIN_BUMP  = 0.05         # ignore sub-5-cent improvements (avoid order churn)
LIVE_STATUSES = {"OrderStatus.NEW", "OrderStatus.HELD", "OrderStatus.ACCEPTED",
                 "OrderStatus.PENDING_NEW", "OrderStatus.PARTIALLY_FILLED"}


def atr_and_close(ticker: str) -> tuple[float, float] | None:
    """ATR(14) and last close from recent daily bars."""
    try:
        h = yf.Ticker(ticker).history(period="4mo", auto_adjust=True)
    except Exception:
        return None
    if h is None or len(h) < ATR_LEN + 2:
        return None
    prev_close = h["Close"].shift(1)
    tr = pd.concat([h["High"] - h["Low"],
                    (h["High"] - prev_close).abs(),
                    (h["Low"] - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_LEN).mean().iloc[-1]
    close = h["Close"].iloc[-1]
    if pd.isna(atr) or pd.isna(close):
        return None
    return float(atr), float(close)


def current_stops(tc: TradingClient) -> dict[str, object]:
    """symbol -> live resting SELL stop order (standalone or bracket leg)."""
    stops = {}
    orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN,
                                            limit=500, nested=True))
    for o in orders:
        for x in [o, *(o.legs or [])]:
            if (str(x.side) == "OrderSide.SELL"
                    and "STOP" in str(getattr(x, "type", "")).upper()
                    and str(x.status) in LIVE_STATUSES
                    and x.stop_price is not None):
                # keep the highest existing stop per symbol
                if x.symbol not in stops or float(x.stop_price) > float(stops[x.symbol].stop_price):
                    stops[x.symbol] = x
    return stops


def main() -> int:
    dry = "--dry-run" in sys.argv
    tc = TradingClient(os.getenv("ALPACA_API_KEY"),
                       os.getenv("ALPACA_SECRET_KEY"), paper=True)
    positions = {p.symbol: p for p in tc.get_all_positions()}
    if not positions:
        print("No open positions.")
        return 0
    stops = current_stops(tc)

    print(f"RATCHET TRAIL  (close - {ATR_MULT}xATR{ATR_LEN}, raise-only{' , DRY RUN' if dry else ''})")
    print("-" * 78)
    raised = 0
    for sym, pos in sorted(positions.items()):
        cur = stops.get(sym)
        if cur is None:
            print(f"  {sym:6} no resting stop — guard_stops.py owns arming; skipped")
            continue
        ac = atr_and_close(sym)
        if ac is None:
            print(f"  {sym:6} no OHLC data — skipped")
            continue
        atr, close = ac
        cur_stop = float(cur.stop_price)
        target = round(close - ATR_MULT * atr, 2)
        entry = float(pos.avg_entry_price)
        if target <= cur_stop + MIN_BUMP:
            print(f"  {sym:6} keep  ${cur_stop:<8.2f} (trail target ${target:.2f} not higher)")
            continue
        locked = (target / entry - 1) * 100
        print(f"  {sym:6} RAISE ${cur_stop:<8.2f} -> ${target:<8.2f} "
              f"(close ${close:.2f}, ATR ${atr:.2f}, locks {locked:+.1f}% vs entry)")
        if dry:
            raised += 1
            continue
        try:
            tc.replace_order_by_id(cur.id, ReplaceOrderRequest(stop_price=target))
            raised += 1
        except Exception as e:
            msg = str(e)
            # Price-validation rejections (e.g. stale off-hours IEX quote says the new
            # stop is above "market") would fail cancel+new identically — and canceling
            # first would leave the position NAKED (2026-07-05: STE went unprotected
            # exactly this way: cancel landed as PENDING_CANCEL, the new submit was
            # rejected). Keep the old stop and let the next in-hours run retry.
            if "must be" in msg or "42210000" in msg:
                print(f"         validation rejected new stop (stale quote?) — keeping ${cur_stop}")
                continue
            # Genuinely un-replaceable order state: cancel+new, and RESTORE the old
            # stop if the new one is rejected so protection is never dropped.
            try:
                tc.cancel_order_by_id(cur.id)
                tc.submit_order(StopOrderRequest(
                    symbol=sym, qty=int(float(pos.qty)), side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC, stop_price=target))
                raised += 1
                print(f"         (replaced via cancel+new: {type(e).__name__})")
            except Exception as e2:
                print(f"         new stop rejected ({type(e2).__name__}) — restoring old ${cur_stop}")
                try:
                    tc.submit_order(StopOrderRequest(
                        symbol=sym, qty=int(float(pos.qty)), side=OrderSide.SELL,
                        time_in_force=TimeInForce.GTC, stop_price=cur_stop))
                except Exception as e3:
                    print(f"         ERROR: could not restore old stop either ({e3}); "
                          f"guard_stops --rearm will cover next run")
    print("-" * 78)
    print(f"{raised} stop(s) {'would be ' if dry else ''}raised.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
