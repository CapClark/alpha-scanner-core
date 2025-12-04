import pandas as pd
import numpy as np
import vectorbt as vbt

from data_loader import get_polygon_data
from strategies import get_rsi_signals, get_bb_signals, get_sma_signals
from analyzer import run_backtest, calculate_robustness
from stability import run_parameter_stability_test


# ================================================
#               CONFIGURATION
# ================================================
TICKER = "AAPL"
STRATEGY_TYPE = "RSI"   # Options: RSI, BB, SMA
BASE_PARAM = 14         # Example: RSI length 14

print(f"🎓 ALPHA SCANNER: Generating Report Card for {TICKER} {STRATEGY_TYPE}({BASE_PARAM})...")


# ================================================
#                 LOAD DATA
# ================================================
data = get_polygon_data(TICKER, "2020-01-01", "2024-01-01")

if data is None or data.empty:
    print("❌ Error: No data found.")
    exit()


# ================================================
#     SELECT STRATEGY + PARAMETER MAPPING
# ================================================
if STRATEGY_TYPE == "RSI":
    strat_func = get_rsi_signals
    param_name = "length"
    other_params = {"oversold": 30, "overbought": 70}

elif STRATEGY_TYPE == "BB":
    strat_func = get_bb_signals
    param_name = "window"
    other_params = {"std": 2.0}

elif STRATEGY_TYPE == "SMA":
    strat_func = get_sma_signals
    param_name = "fast_window"
    other_params = {"slow_window": 200}

else:
    print("❌ Unknown strategy type.")
    exit()


# ================================================
#        BASELINE BACKTEST (Performance)
# ================================================
print("   Running baseline backtest...")

entries, exits = strat_func(data, **{param_name: BASE_PARAM}, **other_params)
pf = run_backtest(data, entries, exits)

trade_count = pf.trades.count()
print(f"   Found {trade_count} trades.")

stats = calculate_robustness(pf, min_trades=2)
if not stats:
    print(f"❌ Strategy failed min_trades threshold ({trade_count} < 2). Grade: F (Inactivity)")
    exit()


# ================================================
#        STABILITY TEST (Robustness)
# ================================================
print("   Running stability test (parameter sweep)...")

stability_results = run_parameter_stability_test(
    data,
    strat_func,
    param_name,
    BASE_PARAM,
    other_params
)


# ================================================
#          FINAL SCORING + GRADES
# ================================================
perf_score = min(100, stats["profit_factor"] * 20)
stab_score = stability_results["stability_score"]

final_score = (perf_score * 0.5) + (stab_score * 0.5)

def get_letter_grade(score):
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"

letter_grade = get_letter_grade(final_score)


# ================================================
#             PRINT REPORT CARD
# ================================================
print("\n" + "=" * 40)
print(f"📄 STRATEGY REPORT CARD: {TICKER}")
print("=" * 40)
print(f"Strategy:      {STRATEGY_TYPE} ({param_name}={BASE_PARAM})")
print(f"Total Trades:  {stats['trade_count']}")
print(f"Profit Factor: {stats['profit_factor']:.2f}")
print(f"Total Return:  {stats['total_return']:.2%}")
print("-" * 40)
print(f"Stability:     {stab_score:.1f}/100")
print(f"   (Tested {param_name} {stability_results['tested_values'][0]} → {stability_results['tested_values'][-1]})")
print("-" * 40)
print(f"FINAL SCORE:   {final_score:.1f}/100")
print(f"FINAL GRADE:   {letter_grade}")
print("=" * 40)
print("\n")

# ================================================
#      ASCII STABILITY CHART (Optional)
# ================================================
print("Stability Profile (Parameter vs Return):")

for val, ret in zip(stability_results["tested_values"], stability_results["returns"]):
    bar_len = int(max(0, ret) * 50)
    bar = "█" * bar_len
    marker = " <--- CURRENT" if val == BASE_PARAM else ""
    print(f"{val:3d}: {bar} ({ret:.1%}){marker}")

