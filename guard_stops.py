#!/usr/bin/env python3
"""Stop-loss guardrail — assert every open position has a resting protective stop.

Defends against the failure mode where a stop order silently disappears (e.g. the
2026-06 bug: DAY-order OTO stop legs expired at the close of the entry day, leaving
positions naked for weeks). Run at the end of the daily loop and/or on its own.

  python3 guard_stops.py            # report only; exit 1 if any position is naked
  python3 guard_stops.py --rearm    # also re-place a GTC stop on any naked position

Exit code is non-zero when something was unprotected, so run_daily.sh can turn that
into an alert (heartbeat /fail ping, email, etc.).
"""
import os
import sys
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import StopOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from dotenv import load_dotenv

load_dotenv()

STOP_LOSS_PCT = 0.05  # mirrors bot.py STOP_LOSS_PCT
LIVE_STATUSES = {
    "OrderStatus.NEW", "OrderStatus.HELD", "OrderStatus.ACCEPTED",
    "OrderStatus.PENDING_NEW", "OrderStatus.PARTIALLY_FILLED",
}


def covered_qty(orders, symbol: str) -> float:
    """Total shares protected by resting SELL stop orders for `symbol`
    (counts both standalone stops and bracket/OTO stop legs)."""
    q = 0.0
    for o in orders:
        for x in [o, *(o.legs or [])]:
            if (getattr(x, "symbol", None) == symbol
                    and str(x.side) == "OrderSide.SELL"
                    and "STOP" in str(getattr(x, "type", "")).upper()
                    and str(x.status) in LIVE_STATUSES):
                q += float(x.qty or 0)
    return q


def main() -> int:
    rearm = "--rearm" in sys.argv
    tc = TradingClient(os.getenv("ALPACA_API_KEY"),
                       os.getenv("ALPACA_SECRET_KEY"), paper=True)

    positions = tc.get_all_positions()
    orders = tc.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.OPEN, limit=500, nested=True))

    naked = []
    for p in positions:
        held = abs(float(p.qty))
        cov = covered_qty(orders, p.symbol)
        if cov + 1e-6 < held:
            naked.append((p, held, cov))

    if not naked:
        print(f"OK — all {len(positions)} open position(s) have a resting stop.")
        return 0

    print(f"!! UNPROTECTED: {len(naked)} of {len(positions)} position(s) lack a full stop")
    for p, held, cov in naked:
        stop = round(float(p.avg_entry_price) * (1 - STOP_LOSS_PCT), 2)
        gap = int(held - cov)
        print(f"   {p.symbol:6} held {held:g}  stop-covered {cov:g}  "
              f"-> need GTC stop ${stop} for {gap} sh")
        if rearm and gap > 0:
            try:
                tc.submit_order(StopOrderRequest(
                    symbol=p.symbol, qty=gap, side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC, stop_price=stop))
                print(f"          re-armed GTC stop @ ${stop}")
            except Exception as e:
                print(f"          ERROR re-arming: {type(e).__name__}: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
